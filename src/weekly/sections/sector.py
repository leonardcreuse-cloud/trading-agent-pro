#!/usr/bin/env python3
"""
Weekly report section 'sector' - Q6 "What happened in the company's sector?" (phase P3.0)

Per company (ctx.universe, or the `tickers` subset passed to build)
  r_W = Cadj(s_0) / Cadj(s_-5) - 1 for the company, its pre-declared sector ETF
  (ctx.weekly['sector_etf'][t]) and each pre-declared peer (ctx.weekly['peers'][t]); both closes
  from ONE yfinance fetch per ticker, frames truncated at s_0 and aligned to the session calendar
  without any fill (a missing bar is never interpolated).
  Peer median m_W, IQR (75th - 25th percentile, linear interpolation) and the share of peers whose
  r_W has the sign of m_W. Company relative performance: r_W - r_W(ETF) and r_W - m_W.
  Sector-wide move flag (rule SECTOR_RULE_VERSION, stated in every output) is set only when ALL hold:
    (1) sign(r_W(ETF)) = sign(m_W) and neither is zero;
    (2) |r_W(ETF)| > k x sd of the ETF's previous non-overlapping 5-session returns (up to 156 weeks,
        windows ending s_-5, s_-10, ...; sample sd; at least MIN_HISTORY_WEEKS), k = 1 by default;
    (3) at least 2/3 of the peers with a return share that sign, compared on counts
        (same x den >= num x peers with a return), so exactly 2/3 passes.
  k and the minimum share come from config weekly.thresholds ('sector_wide_abs_etf_sigma',
  'sector_wide_min_peer_share') when present, else the spec defaults below (labelled as such). The
  share should be declared as a fraction ("2/3" or [2, 3]: exact). A decimal (e.g. 0.6667) is
  compared with an absolute tolerance DECIMAL_SHARE_TOL = 0.0005, so a rounding of a fraction
  (0.667, 0.6667 for 2/3) never turns '>= 2/3' into '> 2/3'; distinct shares of up to 40 peers differ
  by more than 0.0006, so no lower share is let through. An invalid declared value makes the flag
  DATA UNAVAILABLE (never a silent default).
  SEC SIC code and description from ctx.filings(t) (submissions feed): the official industry label.
  The feed shows the CURRENT code only (no SIC history) and the time that value became public is
  unknown: it is evidence only when the feed was retrieved at or before the cutoff (published_at
  NULL, retrieved_at <= T_c). A feed retrieved after the cutoff (the usual case) gives no SIC
  conclusion: the code is shown in the table labelled 'current, not point-in-time' and the SIC at
  the cutoff is DATA UNAVAILABLE.

Overall
  every SPDR sector ETF of ctx.weekly['all_sector_etfs'] (full pre-declared list, never only the
  ones that moved): r_W, benchmark r_W, excess, 156-week sd, r_W / sd.

Evidence rules (docs/DATA_POLICY.md): yfinance prices are a single rank-2 source -> market_fact,
UNCERTAIN (SINGLE_RANK2_SOURCE); the sector-wide flag is a heuristic label -> interpretation
(HEURISTIC_THRESHOLD); the SIC code is rank 1 when the feed was retrieved before the cutoff
(freshness unknown: the code may change between retrieval and the cutoff). 'The sector move
explains the company move' is never stated: at most 'coincided with' as an interpretation.
ETF holdings are unavailable (mechanical co-movement cannot be excluded) and the peer lists were
chosen in 2026 (selection / survivorship bias). Sections never call the wall clock, never write
files and never download outside ctx.
"""

import math
import statistics
from datetime import date
from fractions import Fraction

import numpy as np
import pandas as pd

from ...common import to_utc_iso
from ...database import source_rank
from ...market_data import session_close_utc
from ...sec_parser import SEC_SOURCE
from ..core import SectionResult, conclude, evidence, unavailable

NAME = 'sector'
QUESTIONS = [6]
Q = 6

YF_SOURCE = 'yfinance'
YF_RANK = source_rank(YF_SOURCE)
SEC_RANK = source_rank(SEC_SOURCE)
PRICE_BASIS = 'session close 21:00 UTC (estimate)'
WEEK = 5
HISTORY_WEEKS = 156
MIN_HISTORY_WEEKS = 52
MIN_PEERS = 2

SECTOR_RULE_VERSION = 'sector-wide-v1-2026-10-07'
DEFAULT_ETF_SIGMA = 1.0          # spec default: |ETF return| > 1 x its 156-week sd
DEFAULT_PEER_SHARE = '2/3'       # spec default: >= 2/3 of peers share the sign (exact fraction)
SIGMA_KEY, SHARE_KEY = 'sector_wide_abs_etf_sigma', 'sector_wide_min_peer_share'
DECIMAL_SHARE_TOL = Fraction(5, 10000)   # decimal share thresholds: absolute tolerance (fractions are exact)

PEER_BIAS = ('peer lists and sector ETFs were pre-declared in config weekly (chosen in 2026): '
             'survivorship and selection bias (delisted or since-reclassified names are absent)')
HOLDINGS_GAP = ('ETF holdings are not available to this system: whether the company (or a peer) is held '
                'by its sector ETF, and with what weight, is unknown, so mechanical co-movement cannot be '
                'excluded')
NO_CAUSALITY = ('timing only: a sector move that coincided with the company move is not stated to explain '
                'it; no causal link is established')
SIC_ITEM = 'SEC SIC code at the cutoff'


# ---------------------------------------------------------------- helpers

def _num(value):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) or math.isinf(value) else value


def _iso(day):
    if isinstance(day, str):
        return day[:10]
    if isinstance(day, date):
        return day.isoformat()[:10]
    return pd.Timestamp(day).date().isoformat()


def _sign(x):
    return 0 if x is None or x == 0 else (1 if x > 0 else -1)


def pct(x, digits=2):
    return None if x is None else round(100 * x, digits)


def fmt_pct(x, digits=2, unit='%'):
    return 'N/A' if x is None else f'{100 * x:+.{digits}f}{unit}'


def fresh_flag(ctx, as_of, cadence):
    if as_of is None:
        return None
    status = (ctx.freshness(str(as_of)[:10], cadence) or {}).get('status')
    return True if status == 'FRESH' else False if status == 'STALE' else None


def thresholds_version(ctx):
    return (getattr(ctx, 'weekly', None) or {}).get('thresholds_version')


def parse_share(value):
    """
    Minimum peer share as {'min': Fraction, 'tol': Fraction, 'text': str}; raises ValueError.
    "2/3" or [2, 3]: exact fraction (tol 0). A decimal (0.6667, "0.6667") is compared with the absolute
    tolerance DECIMAL_SHARE_TOL, so 2/3 >= 0.6667 - 0.0005 passes and 0.7 still rejects 2/3.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(f'not a share: {value!r}')
    try:
        if isinstance(value, (list, tuple)):
            if len(value) != 2 or not all(isinstance(x, int) and not isinstance(x, bool) for x in value):
                raise ValueError('expected [numerator, denominator] integers')
            num, den = value
            frac, tol, text = Fraction(num, den), Fraction(0), f'{num}/{den}'
        elif isinstance(value, str) and '/' in value:
            num, den = (int(x.strip()) for x in value.split('/'))
            frac, tol, text = Fraction(num, den), Fraction(0), f'{num}/{den}'
        elif isinstance(value, (int, float, str)):
            text = str(value).strip()
            frac = Fraction(text)
            tol = Fraction(0) if frac.denominator == 1 else DECIMAL_SHARE_TOL
            if tol:
                text += f' (decimal: compared with tolerance {float(tol):g}, i.e. share >= {float(frac - tol):.6g})'
        else:
            raise ValueError(f'unsupported type {type(value).__name__}')
    except ZeroDivisionError as e:
        raise ValueError('zero denominator') from e
    if not 0 < frac <= 1:
        raise ValueError(f'{value!r} is not in (0, 1]')
    return {'min': frac, 'tol': tol, 'text': text}


def share_met(same, n, share):
    """True when same / n >= the declared minimum share (exact rational comparison)."""
    return bool(n) and same is not None and Fraction(same, n) >= share['min'] - share['tol']


def rule_params(ctx):
    """{'k', 'share', 'source', 'error'} of the sector-wide rule (error: invalid declared value)."""
    thr = (getattr(ctx, 'weekly', None) or {}).get('thresholds') or {}
    version = thresholds_version(ctx)
    src, errors = [], []
    k = DEFAULT_ETF_SIGMA
    if SIGMA_KEY in thr:
        k = _num(thr.get(SIGMA_KEY))
        if k is None or k <= 0:
            errors.append(f'config weekly.thresholds.{SIGMA_KEY} = {thr.get(SIGMA_KEY)!r} is not a positive number')
            k = None
        src.append(f'k from config thresholds {version}')
    else:
        src.append(f'k = {DEFAULT_ETF_SIGMA:g} (spec default; not in config weekly.thresholds)')
    share = parse_share(DEFAULT_PEER_SHARE)
    if SHARE_KEY in thr:
        try:
            share = parse_share(thr.get(SHARE_KEY))
        except ValueError as e:
            errors.append(f'config weekly.thresholds.{SHARE_KEY} = {thr.get(SHARE_KEY)!r} is invalid ({e})')
            share = None
        src.append(f'peer share from config thresholds {version}')
    else:
        src.append(f'peer share {DEFAULT_PEER_SHARE} (spec default; not in config weekly.thresholds)')
    return {'k': k, 'share': share, 'source': '; '.join(src), 'error': '; '.join(errors) or None}


def rule_text(k, share):
    k_txt = 'k (invalid in config)' if k is None else f'{k:g}'
    share_txt = 'a minimum share (invalid in config)' if share is None else share['text']
    return (f'rule {SECTOR_RULE_VERSION}: flag set only when sign(ETF r_W) = sign(peer median r_W) (both '
            f'non-zero), |ETF r_W| > {k_txt} x the sd of its previous non-overlapping 5-session returns (up to '
            f'{HISTORY_WEEKS} weeks, minimum {MIN_HISTORY_WEEKS}), and at least {share_txt} of the peers with '
            'a return share that sign (compared on counts)')


def series(ctx, ticker):
    """
    {'status', 'close' (pd.Series indexed by tm.sessions, NaN = no bar), 'fetch', 'reason'}:
    adjusted closes of ONE fetch, truncated at s_0 (bars after s_0 are never used), not filled.
    """
    try:
        p = ctx.prices(ticker)
    except Exception as e:  # noqa: BLE001 - surfaced as DATA UNAVAILABLE
        return {'status': 'DATA UNAVAILABLE', 'close': None, 'fetch': None,
                'reason': f'{type(e).__name__}: {e}'}
    frame = p.get('frame')
    if p.get('status') != 'OK' or frame is None or not len(frame) or 'close' not in frame:
        return {'status': 'DATA UNAVAILABLE', 'close': None, 'fetch': p.get('fetch'),
                'reason': p.get('reason') or 'no adjusted close in the yfinance fetch'}
    f = frame.copy()
    f.index = [_iso(d) for d in f.index]
    f = f[[d <= ctx.tm.s0 for d in f.index]]
    f = f[~f.index.duplicated(keep='last')]
    close = pd.to_numeric(f['close'], errors='coerce').reindex(ctx.tm.sessions)
    return {'status': 'OK', 'close': close, 'fetch': p.get('fetch') or {}, 'reason': None}


def _close(close, i):
    if close is None or i < 0 or i >= len(close):
        return None
    v = _num(close.iloc[i])
    return v if v is not None and v > 0 else None


def _ret(close, a, b):
    x, y = _close(close, a), _close(close, b)
    return None if x is None or y is None else y / x - 1


def weekly(ctx, px):
    """(r_W, sessions of the week with no bar) for an aligned series."""
    if px['status'] != 'OK':
        return None, []
    close = px['close']
    n = len(close)
    missing = [s for i, s in zip(range(n - WEEK - 1, n), ctx.tm.sessions[-WEEK - 1:])
               if _close(close, i) is None]
    return _ret(close, n - WEEK - 1, n - 1), missing


def history_sd(px, weeks=HISTORY_WEEKS):
    """(sample sd, n) of non-overlapping 5-session returns ending s_-5, s_-10, ... (current week excluded)."""
    if px['status'] != 'OK':
        return None, 0
    close = px['close']
    end = len(close) - 1
    rets = []
    for k in range(1, weeks + 1):
        e = end - WEEK * k
        if e - WEEK < 0:
            break
        r = _ret(close, e - WEEK, e)
        if r is not None:
            rets.append(r)
    if len(rets) < MIN_HISTORY_WEEKS:
        return None, len(rets)
    sd = statistics.stdev(rets)
    return (sd if sd > 0 else None), len(rets)


def _get(ctx, cache, ticker):
    """Aligned series, weekly return and missing week bars of a ticker (one ctx.prices call per run)."""
    if ticker not in cache:
        px = series(ctx, ticker)
        r, miss = weekly(ctx, px)
        cache[ticker] = {'px': px, 'r': r, 'missing': miss}
    return cache[ticker]


def price_evidence(ctx, ticker, px, fact):
    fetch = px.get('fetch') or {}
    s0 = ctx.tm.s0
    return evidence(ctx.tm, YF_SOURCE, YF_RANK, f'{ticker}: {fact}', as_of=s0,
                    published_at=session_close_utc(s0), retrieved_at=fetch.get('retrieved_at'),
                    fetch_id=fetch.get('fetch_id'), fresh=fresh_flag(ctx, s0, 'daily_market'),
                    basis=PRICE_BASIS)


def peer_stats(returns):
    """median, IQR, count of peers with the median's sign (None when the median is zero), peers with a return."""
    vals = [r for r in returns if r is not None]
    if len(vals) < MIN_PEERS:
        return None, None, None, len(vals)
    med = statistics.median(vals)
    q1, q3 = np.percentile(vals, [25, 75])
    s = _sign(med)
    same = sum(1 for v in vals if _sign(v) == s) if s else None
    return med, float(q3 - q1), same, len(vals)


def sector_flag(r_etf, sd_etf, med, same, n_peers, k, share):
    """
    (flag True/False/None, list of failed conditions, list of missing inputs). same / n_peers: peers with
    the median's sign / peers with a return; share: parse_share() result (compared on counts).
    """
    missing = [name for name, v in (('ETF weekly return', r_etf), ('ETF 156-week sd', sd_etf),
                                    ('peer median', med)) if v is None]
    if missing:
        return None, [], missing
    failed = []
    if _sign(r_etf) == 0 or _sign(med) == 0 or _sign(r_etf) != _sign(med):
        failed.append(f'sign(ETF {fmt_pct(r_etf)}) != sign(peer median {fmt_pct(med)}) or one is zero')
    if not abs(r_etf) > k * sd_etf:
        failed.append(f'|ETF r_W| {abs(r_etf) * 100:.2f}% <= {k:g} x sd {sd_etf * 100:.2f}%')
    if not share_met(same, n_peers, share):
        failed.append(f'peers with the median sign {"N/A" if same is None else same}/{n_peers} below the minimum '
                      f'share {share["text"]}')
    return not failed, failed, []


# ---------------------------------------------------------------- per company

def _sic(ctx, res, ticker):
    """
    Table row [sic, description, status at the cutoff, retrieved_at, fetch_id]. The submissions feed
    shows only the current SIC and the time that value became public is unknown (published_at NULL):
    it is evidence only when the feed was retrieved at or before the cutoff.
    """
    tm = ctx.tm
    try:
        feed = ctx.filings(ticker)
    except Exception as e:  # noqa: BLE001 - one source must not stop the section
        res.add(unavailable(ticker, Q, SIC_ITEM, f'SEC submissions feed: {type(e).__name__}: {e}'))
        return [None, None, None, None, None]
    if not feed or feed.get('status') != 'OK':
        res.add(unavailable(ticker, Q, SIC_ITEM,
                            f'SEC submissions feed unavailable: {(feed or {}).get("reason") or "no reason given"}'))
        return [None, None, None, None, None]
    fetch = feed.get('fetch') or {}
    retrieved = to_utc_iso(fetch.get('retrieved_at'))
    sic, desc = feed.get('sic') or None, feed.get('sic_description') or None
    row = [sic, desc, None, retrieved, fetch.get('fetch_id')]
    if not sic:
        res.add(unavailable(ticker, Q, SIC_ITEM, 'no SIC code in the SEC submissions feed'))
        return row
    if retrieved is None or retrieved > tm.cutoff:
        when = 'at an unknown time' if retrieved is None else f'at {retrieved}, after the cutoff {tm.cutoff}'
        row[2] = (f'current SIC (retrieved {retrieved or "at an unknown time"}, after the cutoff); not '
                  'point-in-time, not used in any conclusion')
        res.add(unavailable(ticker, Q, SIC_ITEM,
                            f'the submissions feed was retrieved {when} and shows only the current SIC (no SIC '
                            'history; the time that value became public is unknown); no point-in-time SIC (filing '
                            'header ASSIGNED-SIC) is parsed by this system; the current code is shown in the table '
                            'for reference only'))
        return row
    row[2] = 'feed retrieved before the cutoff (SIC as of retrieval)'
    item = evidence(tm, SEC_SOURCE, SEC_RANK, f'{ticker}: SIC {sic} ({desc}) in the SEC submissions feed retrieved {retrieved}',
                    as_of=retrieved[:10], published_at=None, retrieved_at=retrieved, fetch_id=fetch.get('fetch_id'),
                    fresh=None,
                    basis=('time the SIC value became public unknown (the feed has no SIC history): published_at '
                           'NULL, availability = retrieval time, before the cutoff'))
    res.add(conclude(ticker, Q, f'{ticker}: official industry label (SEC EDGAR, rank 1) in the submissions feed '
                                f'retrieved {retrieved}, before the cutoff: SIC {sic} — {desc}.',
                     [item], 'official_fact',
                     resolve='the SIC code in the header of a filing accepted before the cutoff (not parsed by '
                             'this system); the code can change between retrieval and the cutoff'))
    return row


def _company(ctx, res, ticker, params, cache):
    tm = ctx.tm
    weekly_cfg = getattr(ctx, 'weekly', None) or {}
    s_m5, s0 = tm.sessions[-WEEK - 1], tm.s0
    k, min_share = params['k'], params['share']
    rule = rule_text(k, min_share)

    def get(t):
        return _get(ctx, cache, t)

    comp = get(ticker)
    r_c = comp['r']
    if comp['px']['status'] != 'OK':
        res.add(unavailable(ticker, Q, 'company weekly return', f'yfinance prices unavailable: {comp["px"]["reason"]}'))
    elif r_c is None:
        res.add(unavailable(ticker, Q, 'company weekly return',
                            f'no adjusted close for {", ".join(comp["missing"])} in the yfinance fetch (not filled)'))

    etf = (weekly_cfg.get('sector_etf') or {}).get(ticker)
    e, r_e, sd_e, n_sd = None, None, None, 0
    if not etf:
        res.add(unavailable(ticker, Q, 'sector ETF weekly return', 'no sector ETF pre-declared in config weekly.sector_etf'))
    else:
        e = get(etf)
        r_e = e['r']
        sd_e, n_sd = history_sd(e['px'])
        if e['px']['status'] != 'OK':
            res.add(unavailable(ticker, Q, f'sector ETF {etf} weekly return',
                                f'yfinance prices unavailable for {etf}: {e["px"]["reason"]}'))
        elif r_e is None:
            res.add(unavailable(ticker, Q, f'sector ETF {etf} weekly return',
                                f'{etf}: no adjusted close for {", ".join(e["missing"])} (not filled)'))
        if e['px']['status'] == 'OK' and sd_e is None:
            res.add(unavailable(ticker, Q, f'sector ETF {etf} {HISTORY_WEEKS}-week sd of weekly returns',
                                f'{n_sd} non-overlapping weekly returns before the week (minimum {MIN_HISTORY_WEEKS}) '
                                'or zero dispersion'))

    peers = list(weekly_cfg.get('peers', {}).get(ticker) or [])
    peer_rows, peer_r = [], {}
    if not peers:
        res.add(unavailable(ticker, Q, 'peer weekly returns', 'no peer list pre-declared in config weekly.peers'))
    for p in peers:
        g = get(p)
        if g['px']['status'] != 'OK':
            res.add(unavailable(ticker, Q, f'peer {p} weekly return', f'yfinance prices unavailable: {g["px"]["reason"]}'))
        elif g['r'] is None:
            res.add(unavailable(ticker, Q, f'peer {p} weekly return',
                                f'no adjusted close for {", ".join(g["missing"])} (not filled)'))
        peer_r[p] = g['r']
    med, iqr, same, n_avail = peer_stats(list(peer_r.values()))
    if peers and med is None:
        res.add(unavailable(ticker, Q, 'peer median / IQR',
                            f'{n_avail} of {len(peers)} peers have a weekly return (minimum {MIN_PEERS})'))
    for p in peers:
        r = peer_r[p]
        peer_rows.append([p, pct(r), {1: '+', -1: '-', 0: '0'}[_sign(r)] if r is not None else None,
                          None if r is None or med is None or not _sign(med) else
                          ('yes' if _sign(r) == _sign(med) else 'no'),
                          ', '.join(get(p)['missing']) or None])
    res.table(f'{ticker} — peers (pre-declared)', ['peer', 'weekly return %', 'sign', 'same sign as peer median',
                                                   'sessions with no bar (s_-5..s_0)'], peer_rows,
              scope=ticker, question=Q,
              note=(f'Peers from config weekly.peers; {PEER_BIAS}. yfinance (rank 2, unofficial): adjusted close '
                    f'{s_m5} -> {s0}, ratio inside one fetch per ticker, no fill. Every pre-declared peer is listed.'))

    rel_e = None if r_c is None or r_e is None else r_c - r_e
    rel_m = None if r_c is None or med is None else r_c - med
    if params['error']:
        flag, failed, flag_missing = None, [], []
        res.add(unavailable(ticker, Q, 'sector-wide move flag', f'rule parameters invalid: {params["error"]}; {rule}'))
    else:
        flag, failed, flag_missing = sector_flag(r_e, sd_e, med, same, n_avail, k, min_share)
    partial_peers = bool(peers) and n_avail < len(peers)
    partial_week = any(get(t)['missing'] for t in [ticker] + ([etf] if etf else []) + peers
                       if get(t)['r'] is not None)
    if flag is None and etf and peers and not params['error']:
        res.add(unavailable(ticker, Q, 'sector-wide move flag', f'inputs missing: {", ".join(flag_missing)}; {rule}'))

    summary = [ticker, pct(r_c), etf, pct(r_e), None if sd_e is None else round(100 * sd_e, 2),
               None if r_e is None or not sd_e else round(r_e / sd_e, 2), f'{n_avail}/{len(peers)}',
               pct(med), None if iqr is None else round(100 * iqr, 2),
               None if med is None or not _sign(med) else f'{same}/{n_avail}', None if rel_e is None else round(100 * rel_e, 2),
               None if rel_m is None else round(100 * rel_m, 2),
               None if flag is None else ('yes' if flag else 'no'), '; '.join(failed) or None]

    # conclusions: measurements (market_fact) then the heuristic label (interpretation)
    items, parts = [], []
    if r_c is not None:
        items.append(price_evidence(ctx, ticker, comp['px'], f'adjusted close ratio {s_m5} -> {s0} = {fmt_pct(r_c)}'))
        parts.append(f'{ticker} weekly return {fmt_pct(r_c)}')
    if r_e is not None:
        items.append(price_evidence(ctx, etf, e['px'], f'adjusted close ratio {s_m5} -> {s0} = {fmt_pct(r_e)}'))
        parts.append(f'sector ETF {etf} {fmt_pct(r_e)}')
        if rel_e is not None:
            parts.append(f'relative to {etf} {fmt_pct(rel_e, unit=" pp")}')
    peer_items = [price_evidence(ctx, p, get(p)['px'], f'adjusted close ratio {s_m5} -> {s0} = {fmt_pct(r)}')
                  for p, r in peer_r.items() if r is not None]
    if med is not None:
        items += peer_items
        parts.append(f'peer median {fmt_pct(med)} ({n_avail} of {len(peers)} peers: '
                     f'{", ".join(f"{p} {fmt_pct(r)}" for p, r in peer_r.items() if r is not None)}; IQR '
                     f'{100 * iqr:.2f} pp; {same if same is not None else "N/A"} of {n_avail} share the median sign)')
        if rel_m is not None:
            parts.append(f'relative to the peer median {fmt_pct(rel_m, unit=" pp")}')
    if items:
        codes = ['PARTIAL_COVERAGE'] if partial_peers or partial_week else []
        res.add(conclude(ticker, Q, f'{ticker} sector week ({s_m5} close -> {s0} close): ' + '; '.join(parts)
                         + ' (yfinance, rank 2, unofficial).', items, 'market_fact', reason_codes=codes))
    if flag is not None:
        flag_items = [price_evidence(ctx, etf, e['px'], f'adjusted close ratio {s_m5} -> {s0} = {fmt_pct(r_e)}; '
                                                       f'sd of {n_sd} previous weekly returns = {100 * sd_e:.2f}%')]
        flag_items += peer_items
        codes = ['HEURISTIC_THRESHOLD'] + (['PARTIAL_COVERAGE'] if partial_peers or partial_week else [])
        if flag:
            text = (f'{ticker}: sector-wide move flag SET for the week ({etf} {fmt_pct(r_e)}, {abs(r_e) / sd_e:.2f} '
                    f'sd; peer median {fmt_pct(med)}; {same} of {n_avail} peers share the sign) — {rule}.')
            if r_c is not None:
                flag_items.insert(0, items[0])
                text += (f' {ticker}\'s weekly return {fmt_pct(r_c)} coincided with this sector-wide move; '
                         f'{NO_CAUSALITY}.')
        else:
            text = (f'{ticker}: sector-wide move flag NOT set for the week ({"; ".join(failed)}) — {rule}.')
        res.add(conclude(ticker, Q, text, flag_items, 'interpretation', reason_codes=codes))
    return summary


# ---------------------------------------------------------------- overall

def _overall_etfs(ctx, res, cache):
    tm = ctx.tm
    s_m5, s0 = tm.sessions[-WEEK - 1], tm.s0
    weekly_cfg = getattr(ctx, 'weekly', None) or {}
    bench_name = weekly_cfg.get('benchmark', 'SPY')
    etfs = list(weekly_cfg.get('all_sector_etfs') or [])
    if not etfs:
        res.add(unavailable('overall', Q, 'sector ETF table', 'no ETF list pre-declared in config weekly.all_sector_etfs'))
        return

    def get(t):
        return _get(ctx, cache, t)

    bench = get(bench_name)
    r_b = bench['r']
    if r_b is None:
        res.add(unavailable('overall', Q, f'{bench_name} weekly return',
                            bench['px']['reason'] or f'no adjusted close for {", ".join(bench["missing"])} (not filled)'))
    rows, items, parts, missing = [], [], [], []
    for t in etfs:
        g = get(t)
        sd, n_sd = history_sd(g['px'])
        r = g['r']
        if r is None:
            missing.append(t)
            res.add(unavailable('overall', Q, f'sector ETF {t} weekly return',
                                g['px']['reason'] or f'no adjusted close for {", ".join(g["missing"])} (not filled)'))
        else:
            items.append(price_evidence(ctx, t, g['px'], f'adjusted close ratio {s_m5} -> {s0} = {fmt_pct(r)}'))
            parts.append(f'{t} {fmt_pct(r)}' + ('' if r_b is None else f' ({fmt_pct(r - r_b, unit=" pp")} vs {bench_name})'))
        rows.append([t, pct(r), pct(r_b), None if r is None or r_b is None else round(100 * (r - r_b), 2),
                     None if sd is None else round(100 * sd, 2), None if r is None or not sd else round(r / sd, 2),
                     n_sd, ', '.join(g['missing']) or None])
    res.table('Sector ETFs vs benchmark — week', ['ETF', 'weekly return %', f'{bench_name} weekly return %',
                                                  f'excess vs {bench_name} pp', f'sd of weekly returns % (up to {HISTORY_WEEKS} weeks)',
                                                  'weekly return / sd', 'weeks in sd', 'sessions with no bar'],
              rows, question=Q,
              note=(f'Full pre-declared list (config weekly.all_sector_etfs), not only the ETFs that moved. yfinance '
                    f'(rank 2, unofficial): adjusted close {s_m5} -> {s0}, ratio inside one fetch per ticker; sd over '
                    f'the previous non-overlapping 5-session returns. Thresholds {thresholds_version(ctx)}.'))
    if items:
        if r_b is not None:
            items.insert(0, price_evidence(ctx, bench_name, bench['px'], f'adjusted close ratio {s_m5} -> {s0} = '
                                                                        f'{fmt_pct(r_b)}'))
        head = f'Sector ETF weekly returns ({s_m5} close -> {s0} close)'
        head += f', {bench_name} {fmt_pct(r_b)}: ' if r_b is not None else ': '
        res.add(conclude('overall', Q, head + '; '.join(parts) + ' (yfinance, rank 2, unofficial).', items,
                         'market_fact', reason_codes=['PARTIAL_COVERAGE'] if missing else []))


# ---------------------------------------------------------------- section

def build(ctx, tickers=None):
    """tickers: optional subset of ctx.universe (default: the whole universe)."""
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    params = rule_params(ctx)
    k, min_share, param_src = params['k'], params['share'], params['source']
    universe = list(tickers) if tickers is not None else list(ctx.universe)
    cache = {}

    _overall_etfs(ctx, res, cache)
    summaries, sic_rows = [], []
    for t in universe:
        summaries.append(_company(ctx, res, t, params, cache))
        sic_rows.append([t] + _sic(ctx, res, t))

    res.table('Sector-relative performance by company', [
        'ticker', 'weekly return %', 'sector ETF', 'ETF weekly return %', 'ETF sd of weekly returns %',
        'ETF return / sd', 'peers with a return', 'peer median %', 'peer IQR pp', 'peers with the median sign',
        'relative to ETF pp', 'relative to peer median pp', 'sector-wide flag', 'conditions not met'],
        summaries, question=Q,
        note=(f'{rule_text(k, min_share)} ({param_src}). Thresholds {thresholds_version(ctx)}. The flag is a '
              f'heuristic label (UNCERTAIN). {NO_CAUSALITY[0].upper() + NO_CAUSALITY[1:]}. {HOLDINGS_GAP}. '
              f'{PEER_BIAS[0].upper() + PEER_BIAS[1:]}.'))
    res.table('Official industry label (SEC SIC)', ['ticker', 'SIC code', 'SIC description', 'status at the cutoff',
                                                    'submissions feed retrieved at', 'fetch id'], sic_rows,
              question=Q,
              note=('SEC EDGAR submissions feed (rank 1). The feed shows the current SIC only (no history) and the '
                    'time that value became public is unknown: a code is used as evidence only when the feed was '
                    'retrieved before the cutoff (freshness unknown); a feed retrieved after the cutoff gives the '
                    'current code, shown for reference only and not point-in-time. SIC is coarse: same-industry '
                    'companies can sit in different codes (e.g. software vs computer equipment).'))
    res.add(unavailable('overall', Q, 'sector ETF holdings', HOLDINGS_GAP))
    res.add(unavailable('overall', Q, 'peer SIC codes and peer SEC events in the window',
                        'not retrieved by this section: it reads the SEC submissions feed of the report companies '
                        'only (SEC request budget); peer filings are not examined'))
    res.notes.append(f'Week {tm.sessions[-WEEK - 1]} close -> {tm.s0} close; cutoff {tm.cutoff}; thresholds '
                     f'{thresholds_version(ctx)}; {rule_text(k, min_share)} ({param_src}).')
    res.notes.append(f'{PEER_BIAS[0].upper() + PEER_BIAS[1:]}. {HOLDINGS_GAP}. Prices: single rank-2 source '
                     f'(yfinance): UNCERTAIN by rule. {NO_CAUSALITY[0].upper() + NO_CAUSALITY[1:]}.')
    return res
