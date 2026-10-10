#!/usr/bin/env python3
"""
Weekly report section 'market' - Q1 "What happened this week?" (phase P3.0)

Overall
  benchmark (ctx.weekly['benchmark'], SPY) weekly return r_W = Cadj(s_0) / Cadj(s_-5) - 1, both
  adjusted closes from ONE yfinance fetch; equal-weight mean of r_W over ctx.universe; cross-check
  of SPY against FRED SP500 (rank 1). The cross-check compares, over the same two observation
  dates, the SPY ADJUSTED close ratio (the very figure the week statement reports) with the SP500
  price index change as known at T_c. The adjusted ratio is the right comparator: SPY's NAV accrues
  its constituents' dividends as they go ex-dividend and pays them out once a quarter, so its raw
  close drops by a whole quarter's dividends (~0.25-0.30 %) on SPY's own ex-date, whereas the price
  index drops as each constituent goes ex-dividend. Measured on stored SPY bars and FRED SP500
  since 2025 (5-session windows): in the 35 windows containing a SPY ex-date, |adjusted - SP500|
  averaged 0.035 pp (0 above 0.3 pp) and |close_raw - SP500| 0.262 pp (6 above 0.3 pp); outside
  them both series are identical. The week statement counts as cross-checked by an independent
  agreeing source (cross_checked=True) only when the FRED observations known at T_c are exactly
  s_-5 and s_0 and the STATED SPY return agrees with FRED in sign and within 0.3 percentage points.
  FRED publishes SP500 for day d on the next day, so the s_0 value is normally NOT public at T_c:
  the comparison is then made over the latest FRED window known at T_c (a data-consistency check
  of the price source) and the week's statement stays UNCERTAIN.

Per company (each ticker in ctx.universe)
  weekly return, excess vs SPY and vs its pre-declared sector ETF (ctx.weekly['sector_etf']), weekly
  volume / mean weekly volume of the 20 previous non-overlapping 5-session weeks, and
  z = (x_W - mean) / sd of the 156 previous non-overlapping 5-session excess returns vs SPY (windows
  ending s_-5, s_-10, ...; same fetches; sample sd). 'unusual' only when |z| >= the pre-declared
  thresholds['abs_excess_return_z'] (an interpretation: HEURISTIC_THRESHOLD). Timeline of the 5
  sessions: close_raw (displayed level), daily return (adjusted ratio), volume / mean daily volume of
  the same 20-week baseline.

Rules: no bar after s_0 is ever used (frames are re-truncated here and aligned to the SPY session
calendar without any fill: a missing bar is DATA UNAVAILABLE); company prices have a single rank-2
source, so their statements are UNCERTAIN (SINGLE_RANK2_SOURCE) by rule; timing words only.
"""

import math
from datetime import date

import pandas as pd

from ...market_data import session_close_utc
from ..core import SectionResult, conclude, evidence, unavailable

NAME = 'market'
QUESTIONS = [1]
Q = 1

YF_SOURCE, YF_RANK = 'yfinance', 2
FRED_SOURCE, FRED_RANK = 'FRED', 1
PRICE_BASIS = 'session close 21:00 UTC (estimate)'
HISTORY_WEEKS = 156            # z-score history: non-overlapping 5-session windows
MIN_HISTORY_WEEKS = 52         # below this the z-score is not computed
VOLUME_BASE_WEEKS = 20         # volume baseline: previous 20 non-overlapping weeks
MIN_VOLUME_BASE_WEEKS = 15
WEEK = 5
CROSS_CHECK_TOLERANCE_PP = 0.3  # spec: SPY vs FRED SP500 within 0.3 percentage points, same sign
SP500 = 'SP500'


# ---------------------------------------------------------------- shared helpers (used by risks)

def thresholds(ctx):
    return dict((getattr(ctx, 'weekly', None) or {}).get('thresholds') or {})


def thresholds_version(ctx):
    return (getattr(ctx, 'weekly', None) or {}).get('thresholds_version')


def fresh_flag(ctx, as_of, cadence):
    """True / False from ctx.freshness at the cutoff, None when unknown."""
    if as_of is None:
        return None
    status = (ctx.freshness(str(as_of)[:10], cadence) or {}).get('status')
    return True if status == 'FRESH' else False if status == 'STALE' else None


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


def prices_aligned(ctx, ticker):
    """
    ctx.prices(ticker) aligned to the session calendar tm.sessions (<= s_0), no fill.
    {'status', 'frame' (index = ISO session dates, columns close / close_raw / volume, NaN = no bar),
     'fetch', 'reason', 'dropped_after_s0'}.
    """
    p = ctx.prices(ticker)
    frame = p.get('frame')
    if p.get('status') != 'OK' or frame is None or not len(frame):
        return {'status': 'DATA UNAVAILABLE', 'frame': None, 'fetch': p.get('fetch'),
                'reason': p.get('reason') or 'no price data'}
    f = frame.copy()
    f.index = [_iso(d) for d in f.index]
    after = sum(1 for d in f.index if d > ctx.tm.s0)
    f = f[[d <= ctx.tm.s0 for d in f.index]]          # never use a bar after s_0
    f = f[~f.index.duplicated(keep='last')]
    for col in ('close', 'close_raw', 'volume'):
        if col not in f.columns:
            f[col] = float('nan')
    f = f[['close', 'close_raw', 'volume']].astype(float).reindex(ctx.tm.sessions)
    return {'status': 'OK', 'frame': f, 'fetch': p.get('fetch') or {}, 'reason': None,
            'dropped_after_s0': after}


def value(frame, col, idx):
    """Value at calendar index idx (negative allowed), None when the bar is missing."""
    if frame is None or idx < -len(frame) or idx >= len(frame):
        return None
    v = _num(frame[col].iloc[idx])
    return v if v is None or col == 'volume' or v > 0 else None


def ratio_return(frame, col, start_idx, end_idx):
    a, b = value(frame, col, start_idx), value(frame, col, end_idx)
    return None if a is None or b is None else b / a - 1


def weekly_volume_ratio(frame, end_idx, weeks=VOLUME_BASE_WEEKS, min_weeks=MIN_VOLUME_BASE_WEEKS):
    """
    (ratio, baseline mean weekly volume, n complete baseline weeks): volume of the 5 sessions
    ending at end_idx / mean volume of the `weeks` previous non-overlapping 5-session weeks.
    """
    n = len(frame)
    end = end_idx % n if end_idx < 0 else end_idx

    def week_sum(e):
        if e - WEEK + 1 < 0:
            return None
        vals = [value(frame, 'volume', i) for i in range(e - WEEK + 1, e + 1)]
        return None if any(v is None for v in vals) else sum(vals)

    current = week_sum(end)
    base = [s for s in (week_sum(end - WEEK * k) for k in range(1, weeks + 1)) if s is not None]
    if current is None or len(base) < min_weeks:
        return None, None, len(base)
    mean = sum(base) / len(base)
    return (current / mean if mean > 0 else None), mean, len(base)


def price_evidence(ctx, ticker, px, fact, as_of=None):
    as_of = as_of or ctx.tm.s0
    fetch = px.get('fetch') or {}
    return evidence(ctx.tm, YF_SOURCE, YF_RANK, f'{ticker}: {fact}', as_of=as_of,
                    published_at=session_close_utc(as_of), retrieved_at=fetch.get('retrieved_at'),
                    fetch_id=fetch.get('fetch_id'), fresh=fresh_flag(ctx, as_of, 'daily_market'),
                    basis=PRICE_BASIS)


def pct(x, digits=2):
    return None if x is None else round(100 * x, digits)


def fmt_pct(x, digits=2, unit='%'):
    return 'N/A' if x is None else f'{100 * x:+.{digits}f}{unit}'


def _std(values):
    n = len(values)
    if n < 2:
        return None
    m = sum(values) / n
    return math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))


def excess_history(frame, bench, end_idx, weeks=HISTORY_WEEKS):
    """Non-overlapping 5-session excess returns ending at end_idx - 5k, k = 1..weeks."""
    n = len(frame)
    end = end_idx % n if end_idx < 0 else end_idx
    out = []
    for k in range(1, weeks + 1):
        e = end - WEEK * k
        if e - WEEK < 0:
            break
        r = ratio_return(frame, 'close', e - WEEK, e)
        b = ratio_return(bench, 'close', e - WEEK, e)
        if r is not None and b is not None:
            out.append(r - b)
    return out


def agrees(a, b, tolerance_pp=CROSS_CHECK_TOLERANCE_PP):
    """True when two returns have the same sign and differ by <= tolerance_pp; None if one is unknown."""
    if a is None or b is None:
        return None
    same_sign = (a > 0) == (b > 0) and (a < 0) == (b < 0)
    return same_sign and abs(a - b) * 100 <= tolerance_pp


def zscore(x, history, min_n=MIN_HISTORY_WEEKS):
    if x is None or len(history) < min_n:
        return None
    sd = _std(history)
    if not sd:
        return None
    return (x - sum(history) / len(history)) / sd


# ---------------------------------------------------------------- section

def _sessions(ctx):
    return ctx.tm.sessions[-WEEK - 1], ctx.tm.s0     # s_-5, s_0


def _company(ctx, res, ticker, bench_name, bench, bench_px, thr):
    """Per-company facts; returns the weekly return (or None) for the equal-weight mean."""
    tm = ctx.tm
    s_m5, s0 = _sessions(ctx)
    px = prices_aligned(ctx, ticker)
    if px['status'] != 'OK':
        res.add(unavailable(ticker, Q, 'weekly price facts', f'yfinance prices unavailable: {px["reason"]}'))
        return None
    f = px['frame']
    missing = [s for s in [s_m5] + tm.week if value(f, 'close', tm.sessions.index(s)) is None]
    r_w = ratio_return(f, 'close', -WEEK - 1, -1)
    partial = ['PARTIAL_COVERAGE'] if r_w is not None and missing else []
    if r_w is None:
        res.add(unavailable(ticker, Q, 'weekly return',
                            f'no adjusted close for {", ".join(sorted(missing))} in the yfinance fetch '
                            '(missing bar, halt or listing gap): not filled'))
    b_w = ratio_return(bench, 'close', -WEEK - 1, -1) if bench is not None else None
    x_spy = r_w - b_w if r_w is not None and b_w is not None else None

    etf = ((ctx.weekly or {}).get('sector_etf') or {}).get(ticker)
    etf_px, e_w = None, None
    if not etf:
        res.add(unavailable(ticker, Q, 'excess return vs sector ETF',
                            'no sector ETF pre-declared for this ticker in config weekly.sector_etf'))
    else:
        etf_px = prices_aligned(ctx, etf)
        if etf_px['status'] != 'OK':
            res.add(unavailable(ticker, Q, f'excess return vs sector ETF {etf}',
                                f'yfinance prices unavailable for {etf}: {etf_px["reason"]}'))
            etf_px = None
        else:
            e_w = ratio_return(etf_px['frame'], 'close', -WEEK - 1, -1)
            if e_w is None:
                res.add(unavailable(ticker, Q, f'excess return vs sector ETF {etf}',
                                    f'{etf} has no adjusted close for s_-5 or s_0 in its fetch'))
    x_etf = r_w - e_w if r_w is not None and e_w is not None else None

    vol_ratio, vol_base, vol_weeks = weekly_volume_ratio(f, len(f) - 1)
    if vol_ratio is None:
        res.add(unavailable(ticker, Q, 'weekly volume ratio',
                            f'volume missing for a session of the week or fewer than '
                            f'{MIN_VOLUME_BASE_WEEKS} complete baseline weeks ({vol_weeks} found)'))
    history = excess_history(f, bench, len(f) - 1) if bench is not None else []
    z = zscore(x_spy, history)
    if x_spy is not None and z is None:
        res.add(unavailable(ticker, Q, 'excess-return z-score',
                            f'{len(history)} historical non-overlapping weekly excess returns '
                            f'(minimum {MIN_HISTORY_WEEKS}, target {HISTORY_WEEKS}) or zero dispersion'))
    z_thr = _num(thr.get('abs_excess_return_z'))
    if z_thr is None:
        res.add(unavailable(ticker, Q, "'unusual' flag", 'no pre-declared threshold abs_excess_return_z in '
                                                          'config weekly.thresholds'))
    unusual = None if z is None or z_thr is None else abs(z) >= z_thr

    res.table(f'{ticker} — week in figures', [
        'ticker', 'weekly return %', f'{bench_name} weekly return %', f'excess vs {bench_name} pp',
        'sector ETF', 'sector ETF weekly return %', 'excess vs sector ETF pp',
        'weekly volume / 20-week mean', f'excess-return z ({len(history)} weeks)',
        f'unusual (|z| >= {z_thr})'],
        [[ticker, pct(r_w), pct(b_w), pct(x_spy), etf, pct(e_w), pct(x_etf),
          None if vol_ratio is None else round(vol_ratio, 2), None if z is None else round(z, 2),
          None if unusual is None else ('yes' if unusual else 'no')]],
        scope=ticker, question=Q,
        note=(f'yfinance (rank 2, unofficial). Returns: adjusted close s_-5 {s_m5} -> s_0 {s0}, ratio '
              f'inside one fetch per ticker. z = (excess - mean) / sd of up to {HISTORY_WEEKS} previous '
              f'non-overlapping 5-session excess returns vs SPY. Thresholds {thresholds_version(ctx)}.'))

    # timeline of the 5 sessions
    daily_base = vol_base / WEEK if vol_base else None
    rows = []
    for s in tm.week:
        i = tm.sessions.index(s)
        r = ratio_return(f, 'close', i - 1, i)
        v = value(f, 'volume', i)
        raw = value(f, 'close_raw', i)
        rows.append([s, None if raw is None else round(raw, 4), pct(r),
                     None if v is None or not daily_base else round(v / daily_base, 2)])
    res.table(f'{ticker} — session timeline', ['session', 'close_raw (USD)', 'daily return %',
                                               'volume / 20-week mean daily volume'],
              rows, scope=ticker, question=Q,
              note='close_raw is the split-adjusted close shown as a level; daily returns are adjusted '
                   'close ratios inside one fetch. N/A = no bar from the source (never filled).')

    if r_w is not None:
        items = [price_evidence(ctx, ticker, px, f'adjusted close ratio {s_m5} -> {s0} = {fmt_pct(r_w)}')]
        parts = [f'{ticker}: weekly return {fmt_pct(r_w)} (close {s_m5} to close {s0})']
        if x_spy is not None:
            items.append(price_evidence(ctx, bench_name, bench_px,
                                        f'adjusted close ratio {s_m5} -> {s0} = {fmt_pct(b_w)}'))
            parts.append(f'excess vs {bench_name} {fmt_pct(x_spy, unit=" pp")}')
        if x_etf is not None:
            items.append(price_evidence(ctx, etf, etf_px, f'adjusted close ratio {s_m5} -> {s0} = {fmt_pct(e_w)}'))
            parts.append(f'excess vs sector ETF {etf} {fmt_pct(x_etf, unit=" pp")}')
        if z is not None:
            parts.append(f'excess-return z-score {z:+.2f} vs its last {len(history)} weeks')
        if missing:
            parts.append(f'no bar for {", ".join(missing)} (not filled)')
        res.add(conclude(ticker, Q, '; '.join(parts) + ' (yfinance, rank 2, unofficial).', items,
                         'market_fact', reason_codes=partial + (['PARTIAL_COVERAGE']
                                                                if z is not None and len(history) < HISTORY_WEEKS
                                                                else [])))
    if vol_ratio is not None:
        res.add(conclude(ticker, Q, f'{ticker}: volume over the week was {vol_ratio:.2f}x the mean weekly '
                                    f'volume of the previous {vol_weeks} weeks (yfinance, rank 2).',
                         [price_evidence(ctx, ticker, px, f'5-session volume / {vol_weeks}-week mean = '
                                                          f'{vol_ratio:.2f}')], 'market_fact'))
    if unusual:
        res.add(conclude(ticker, Q, f'{ticker}: the weekly excess return vs {bench_name} ({fmt_pct(x_spy, unit=" pp")}) '
                                    f'was large relative to its own history (|z| = {abs(z):.2f} >= '
                                    f'pre-declared {z_thr}, thresholds {thresholds_version(ctx)}).',
                         [price_evidence(ctx, ticker, px, f'excess-return z = {z:+.2f}')], 'interpretation',
                         reason_codes=['HEURISTIC_THRESHOLD']))
    return {'r_w': r_w, 'px': px, 'unusual': unusual}


def _sp500_crosscheck(ctx, res, bench_name, bench, bench_px, s_m5, s0):
    """
    {'exact': the FRED window known at T_c is s_-5 -> s_0, 'agree': True / False / None,
     'fred_r': FRED SP500 change, 'items': FRED evidence, 'row': table row}; None when no comparison
    is possible. SPY side: adjusted close ratio (see the module docstring for why not close_raw).
    """
    tm = ctx.tm
    st = ctx.fred(SP500)
    if st.get('status') != 'OK':
        res.add(unavailable('overall', Q, 'FRED SP500 cross-check', f'FRED SP500: {st.get("reason")}'))
        return None
    now = ctx.value_at(SP500, tm.cutoff)
    if not now:
        res.add(unavailable('overall', Q, 'FRED SP500 cross-check', 'no SP500 observation known at the cutoff'))
        return None
    d_c, v_c, pub_c = str(now[0])[:10], _num(now[1]), now[2]
    if d_c not in tm.sessions or tm.sessions.index(d_c) - WEEK < 0:
        res.add(unavailable('overall', Q, 'FRED SP500 cross-check',
                            f'latest SP500 observation known at the cutoff ({d_c}) is not a session of the '
                            'SPY calendar with 5 earlier sessions'))
        return None
    i_c = tm.sessions.index(d_c)
    d_p = tm.sessions[i_c - WEEK]
    known = {str(d)[:10]: _num(v) for d, v in ctx.series_at(SP500, tm.cutoff)}
    v_p = known.get(d_p)
    if not v_p or not v_c:
        res.add(unavailable('overall', Q, 'FRED SP500 cross-check',
                            f'no SP500 observation for {d_p} as known at the cutoff'))
        return None
    fred_r = v_c / v_p - 1
    col = 'adjusted close'
    spy_r = ratio_return(bench, 'close', i_c - WEEK, i_c)
    fetch = st.get('fetch') or {}
    items = [evidence(tm, FRED_SOURCE, FRED_RANK, f'SP500 {d_p} = {v_p} -> {d_c} = {v_c} ({fmt_pct(fred_r)})',
                      as_of=d_c, published_at=pub_c, retrieved_at=fetch.get('retrieved_at'),
                      fetch_id=fetch.get('fetch_id'), fresh=fresh_flag(ctx, d_c, 'daily'),
                      basis='FRED vintage date (realtime_start), end of day New York')]
    agree = agrees(spy_r, fred_r)
    diff = None if spy_r is None else abs(spy_r - fred_r) * 100
    exact = d_c == s0 and d_p == s_m5
    row = [f'{bench_name} ({col}) vs FRED SP500', d_p, d_c, pct(spy_r), pct(fred_r),
           None if diff is None else round(diff, 3),
           None if agree is None else ('yes' if agree else 'no'),
           'the week s_-5 -> s_0' if exact else 'latest FRED window known at the cutoff (not the week)']
    if spy_r is not None and not exact:
        spy_item = price_evidence(ctx, bench_name, bench_px, f'{col} ratio {d_p} -> {d_c} = {fmt_pct(spy_r)}',
                                  as_of=d_c)
        verdict = (f'agree in sign and within {CROSS_CHECK_TOLERANCE_PP} pp' if agree
                   else f'do not agree (same sign and within {CROSS_CHECK_TOLERANCE_PP} pp required)')
        res.add(conclude('overall', Q, f'Over {d_p} -> {d_c} (the latest FRED SP500 window known at the cutoff, '
                                       f'not the report week), the {bench_name} adjusted-close return {fmt_pct(spy_r)} and '
                                       f'the FRED SP500 change {fmt_pct(fred_r)} {verdict} (difference '
                                       f'{diff:.3f} pp).',
                         [spy_item] + items, 'market_fact', cross_checked=bool(agree),
                         reason_codes=[] if agree else ['CONFLICTING_SOURCES']))
    return {'exact': exact, 'agree': agree, 'fred_r': fred_r, 'items': items, 'row': row}


def build(ctx):
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    thr = thresholds(ctx)
    s_m5, s0 = _sessions(ctx)
    bench_name = (ctx.weekly or {}).get('benchmark', 'SPY')
    bench_px = prices_aligned(ctx, bench_name)
    bench = bench_px['frame'] if bench_px['status'] == 'OK' else None
    b_w = ratio_return(bench, 'close', -WEEK - 1, -1) if bench is not None else None
    if b_w is None:
        res.add(unavailable('overall', Q, f'{bench_name} weekly return',
                            bench_px.get('reason') or f'no adjusted close for {s_m5} or {s0}'))

    per = {}
    for ticker in ctx.universe:
        per[ticker] = _company(ctx, res, ticker, bench_name, bench, bench_px, thr)

    # overall
    check = _sp500_crosscheck(ctx, res, bench_name, bench, bench_px, s_m5, s0) if b_w is not None else None
    # the figure that becomes STRONGLY SUPPORTED must be the figure that was checked: b_w itself
    week_agree = agrees(b_w, check['fred_r']) if check and check['exact'] else None
    week_checked = week_agree is True
    week_conflict = week_agree is False
    returns = {t: p['r_w'] for t, p in per.items() if p and p.get('r_w') is not None}
    missing = [t for t in ctx.universe if t not in returns]
    ew = sum(returns.values()) / len(returns) if returns else None
    flagged = [t for t, p in per.items() if p and p.get('unusual')]
    assessed = [t for t, p in per.items() if p and p.get('unusual') is not None]
    srt = sorted(returns.values())
    res.table('Market week — overall', ['measure', 'value', 'detail'], [
        [f'{bench_name} weekly return % (adjusted close {s_m5} -> {s0})', pct(b_w), 'yfinance, rank 2'],
        ['equal-weight universe weekly return %', pct(ew),
         f'{len(returns)} of {len(ctx.universe)} tickers' + (f'; missing {", ".join(missing)}' if missing else '')],
        ['lowest / highest weekly return in the universe %',
         None if not srt else f'{pct(srt[0])} / {pct(srt[-1])}', None],
        [f'names with |excess z| >= {thr.get("abs_excess_return_z")}',
         None if not assessed else len(flagged), f'{len(assessed)} assessed: {", ".join(flagged) or "none"}'],
    ], question=Q, note=f'Pre-declared universe and benchmark (config weekly). Thresholds {thresholds_version(ctx)}.')
    if check:
        res.table('SPY vs FRED SP500 cross-check', ['comparison', 'from', 'to', 'SPY %', 'FRED SP500 %',
                                                    '|difference| pp', f'agree (same sign, <= {CROSS_CHECK_TOLERANCE_PP} pp)',
                                                    'window'], [check['row']], question=Q,
                  note='SPY adjusted close ratio vs the SP500 price index. SPY accrues its constituents\' '
                       'dividends and its raw close drops by a whole quarter of them on its own ex-date, while '
                       'the index drops as each constituent goes ex-dividend: the adjusted ratio tracks the '
                       'index (since 2025, SPY ex-date weeks: mean |adjusted - SP500| 0.035 pp vs 0.262 pp for '
                       'close_raw). FRED publishes SP500 for day d on the next day, so the s_0 value is normally '
                       'not public at the cutoff; the week statement is cross-checked only when the FRED window '
                       'known at the cutoff is exactly s_-5 -> s_0 and the stated SPY return agrees.')

    if b_w is not None:
        items = [price_evidence(ctx, bench_name, bench_px, f'adjusted close ratio {s_m5} -> {s0} = {fmt_pct(b_w)}')]
        if check and check['exact']:
            items += check['items']
        resolve = None if week_checked else (
            'FRED SP500 observations for s_-5 and s_0 known at the cutoff and agreeing within '
            f'{CROSS_CHECK_TOLERANCE_PP} pp (FRED publishes SP500 the next day)')
        tail = ('; FRED SP500 agrees' if week_checked else '; FRED SP500 disagrees' if week_conflict
                else '; FRED SP500 cross-check unavailable' if check is None
                else '; no FRED SP500 value for s_0 known at the cutoff')
        res.add(conclude('overall', Q, f'{bench_name} weekly return {fmt_pct(b_w)} (close {s_m5} to close {s0}; '
                                       f'yfinance, rank 2{tail}).', items, 'market_fact',
                         cross_checked=week_checked, resolve=resolve,
                         reason_codes=['CONFLICTING_SOURCES'] if week_conflict else []))
    if ew is not None:
        items = [price_evidence(ctx, t, per[t]['px'], f'adjusted close ratio {s_m5} -> {s0} = {fmt_pct(r)}')
                 for t, r in returns.items()]
        res.add(conclude('overall', Q, f'Equal-weight weekly return of the {len(ctx.universe)}-ticker universe: '
                                       f'{fmt_pct(ew)} ({len(returns)} tickers with both closes).', items,
                         'market_fact', reason_codes=['PARTIAL_COVERAGE'] if missing else []))
    else:
        res.add(unavailable('overall', Q, 'equal-weight universe weekly return',
                            'no ticker of the universe has adjusted closes for both s_-5 and s_0'))
    res.notes.append(f'Week {s_m5} close -> {s0} close; cutoff {tm.cutoff}; benchmark {bench_name}; thresholds '
                     f'{thresholds_version(ctx)}. Company price facts have a single rank-2 source '
                     '(yfinance): UNCERTAIN by rule. Timing only, no causal link is asserted.')
    return res
