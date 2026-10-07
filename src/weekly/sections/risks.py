#!/usr/bin/env python3
"""
Weekly report section 'risks' - Q8 "What risks increased?" (phase P3.0)

A FULL pre-declared indicator table per company, each indicator computed as known at T_p (previous
cutoff) and at T_c (cutoff); decreases and unchanged rows are shown too (no selection).

  sigma20          annualised sd (sqrt 252) of the 20 daily log returns ending s_0 / ending s_-5
                   (adjusted closes, one yfinance fetch). Rule: relative change >= sigma20_change_rel.
  drawdown         close / max(close over the 252 sessions ending at s) - 1, s = s_0 / s_-5.
                   Rule: drawdown at T_c <= drawdown_new_low_pct (%) and deeper than at T_p.
  volume ratio     volume of the 5 sessions ending s_0 (s_-5) / mean of the 20 previous weeks.
                   Rule: ratio at T_c >= volume_ratio and higher than at T_p.
  debt / D-E       ctx.sec.fundamentals(ticker, known_at=T) (stored SEC XBRL facts, rank 1).
  insider sales    discretionary (no Rule 10b5-1 box) open-market sales (code S) over the 90 days
                   ending T_c / T_p from stored Form 4 events (published_at windows): USD value and
                   distinct sellers (first reporting owner of each filing).
  red-flag filings 8-K items 4.01, 4.02, 1.05, 3.01, 2.05, 2.06 and NT 10-K / NT 10-Q accepted in
                   P = (T_p, T_c] vs the previous week. Rule: any red-flag filing in P.
Debt, D/E and insider rows have no pre-declared threshold in config v1: they are shown and marked
"not assessed" unless the optional keys of OPTIONAL_THRESHOLDS are added to weekly.thresholds.

Market rows: VIXCLS, BAMLH0A0HYM2, NFCI, STLFSI4 (FRED, rank 1) as known at T_c and T_p (vintages).
Rule (documented in the table note): increase > 1 sample sd of the Friday-to-Friday changes (last
observation of each week) of the series as known at T_p (at least 26 weekly changes).

Levels: price measurements are market_fact (single rank-2 source -> UNCERTAIN by rule), SEC and FRED
measurements are official_fact; the judgement "risk increased for X" is ALWAYS an interpretation.
risk_score is NOT IMPLEMENTED (no risk model).
"""

import json
import math
from datetime import date, datetime, timedelta

from ...common import end_of_us_trading_day_utc, to_utc_iso
from ..core import SectionResult, conclude, evidence, unavailable
from .market import (WEEK, _num, _std, fresh_flag, prices_aligned, price_evidence, thresholds,
                     thresholds_version, value, weekly_volume_ratio)

NAME = 'risks'
QUESTIONS = [8]
Q = 8

SEC_SOURCE, SEC_RANK = 'SEC EDGAR', 1
FRED_SOURCE, FRED_RANK = 'FRED', 1
FORM4_METRIC = 'form4:transaction'
INSIDER_DAYS = 90
SIGMA_WINDOW = 20
DRAWDOWN_WINDOW = 252
ANNUALISATION = 252
MIN_WEEKLY_CHANGES = 26
RED_FLAG_ITEMS = {
    '4.01': 'change in certifying accountant',
    '4.02': 'non-reliance on previously issued financial statements',
    '1.05': 'material cybersecurity incident',
    '3.01': 'delisting notice or failure to satisfy a listing rule',
    '2.05': 'costs associated with exit or disposal activities',
    '2.06': 'material impairments',
}
RED_FLAG_FORMS = ('NT 10-K', 'NT 10-Q', 'NT 10-K/A', 'NT 10-Q/A')
EIGHT_K_FORMS = ('8-K', '8-K/A')
STRESS_SERIES = (
    ('VIXCLS', 'daily', 'CBOE Volatility Index (VIX), close'),
    ('BAMLH0A0HYM2', 'daily', 'ICE BofA US High Yield option-adjusted spread (%)'),
    ('NFCI', 'weekly', 'Chicago Fed National Financial Conditions Index'),
    ('STLFSI4', 'weekly', 'St. Louis Fed Financial Stress Index'),
)
# Not in config v1-2026-10-07: used only if the owner adds them to weekly.thresholds.
OPTIONAL_THRESHOLDS = {
    'debt_to_equity_change_abs': 'D/E at T_c - D/E at T_p >= value',
    'debt_change_rel': 'debt at T_c / debt at T_p - 1 >= value',
    'insider_sale_value_ratio': 'discretionary sales at T_c >= value x sales at T_p (with insider_sale_min_usd)',
    'insider_sale_min_usd': 'discretionary sales at T_c >= value USD (with insider_sale_value_ratio)',
    'discretionary_sellers_change_abs': 'distinct discretionary sellers at T_c - at T_p >= value',
}
NOT_ASSESSED = 'not assessed: no pre-declared threshold'


def _yes(flag):
    return None if flag is None else ('yes' if flag else 'no') if isinstance(flag, bool) else flag


def _r(x, n=4):
    return None if x is None else round(x, n)


def _fmt(x, spec='.2f', suffix=''):
    return 'N/A' if x is None else f'{x:{spec}}{suffix}'


# ---------------------------------------------------------------- price indicators

def sigma20(frame, end):
    if end - SIGMA_WINDOW < 0:
        return None
    closes = [value(frame, 'close', i) for i in range(end - SIGMA_WINDOW, end + 1)]
    if any(c is None for c in closes):
        return None
    sd = _std([math.log(b / a) for a, b in zip(closes, closes[1:])])
    return None if sd is None else sd * math.sqrt(ANNUALISATION)


def drawdown(frame, end):
    if end - DRAWDOWN_WINDOW + 1 < 0:
        return None
    closes = [value(frame, 'close', i) for i in range(end - DRAWDOWN_WINDOW + 1, end + 1)]
    if any(c is None for c in closes):
        return None
    return closes[-1] / max(closes) - 1


def _price_rows(ctx, res, ticker, thr):
    tm = ctx.tm
    px = prices_aligned(ctx, ticker)
    names = ('sigma20 (annualised, %)', 'drawdown vs 252-session max (%)', '5-session volume ratio')
    if px['status'] != 'OK':
        for n in names:
            res.add(unavailable(ticker, Q, n, f'yfinance prices unavailable: {px["reason"]}'))
        return [_row(n, None, None, None, 'N/A', None, 'yfinance (rank 2)') for n in names], []
    f = px['frame']
    e_c, e_p = len(f) - 1, len(f) - 1 - WEEK
    rows, parts = [], []

    s_c, s_p = sigma20(f, e_c), sigma20(f, e_p)
    rel = s_c / s_p - 1 if s_c is not None and s_p else None
    t = _num(thr.get('sigma20_change_rel'))
    flag = None if rel is None else (NOT_ASSESSED if t is None else rel >= t)
    rows.append(_row(names[0], _r(s_p and 100 * s_p, 2), _r(s_c and 100 * s_c, 2),
                     None if rel is None else f'{100 * rel:+.1f}% relative',
                     f'relative change >= {t}' if t is not None else NOT_ASSESSED, flag, 'yfinance (rank 2)'))
    if rel is None:
        res.add(unavailable(ticker, Q, names[0], f'fewer than {SIGMA_WINDOW + 1} consecutive adjusted closes '
                                                 'ending s_0 or s_-5 (missing bars are not filled)'))
    else:
        parts.append(f'sigma20 {100 * s_p:.1f}% -> {100 * s_c:.1f}% ({100 * rel:+.1f}% relative; rule >= '
                     f'{_fmt(t and 100 * t, ".0f", "%")}: {_yes(flag)})')

    d_c, d_p = drawdown(f, e_c), drawdown(f, e_p)
    t = _num(thr.get('drawdown_new_low_pct'))
    flag = None if d_c is None or d_p is None else (NOT_ASSESSED if t is None else (100 * d_c <= t and d_c < d_p))
    rows.append(_row(names[1], _r(d_p and 100 * d_p, 2), _r(d_c and 100 * d_c, 2),
                     None if d_c is None or d_p is None else f'{100 * (d_c - d_p):+.2f} pp',
                     f'<= {t}% at T_c and deeper than at T_p' if t is not None else NOT_ASSESSED, flag,
                     'yfinance (rank 2)'))
    if flag is None:
        res.add(unavailable(ticker, Q, names[1], f'fewer than {DRAWDOWN_WINDOW} consecutive adjusted closes '
                                                 'ending s_0 or s_-5 (missing bars are not filled)'))
    else:
        parts.append(f'drawdown {100 * d_p:.1f}% -> {100 * d_c:.1f}% (rule <= {t}% and deeper: {_yes(flag)})')

    v_c = weekly_volume_ratio(f, e_c)[0]
    v_p = weekly_volume_ratio(f, e_p)[0]
    t = _num(thr.get('volume_ratio'))
    flag = None if v_c is None or v_p is None else (NOT_ASSESSED if t is None else (v_c >= t and v_c > v_p))
    rows.append(_row(names[2], _r(v_p, 2), _r(v_c, 2), None if flag is None else f'{v_c - v_p:+.2f}',
                     f'>= {t} at T_c and higher than at T_p' if t is not None else NOT_ASSESSED, flag,
                     'yfinance (rank 2)'))
    if flag is None:
        res.add(unavailable(ticker, Q, names[2], 'volume missing in a week or fewer than 15 complete '
                                                 'baseline weeks'))
    else:
        parts.append(f'5-session volume ratio {v_p:.2f} -> {v_c:.2f} (rule >= {t} and higher: {_yes(flag)})')

    items = []
    if parts:
        item = price_evidence(ctx, ticker, px, f'indicators ending s_-5 {tm.sessions[-WEEK - 1]} and s_0 '
                                               f'{tm.s0} from one fetch: ' + '; '.join(parts))
        items.append(item)
        res.add(conclude(ticker, Q, f'{ticker} price-based risk indicators, T_p -> T_c: ' + '; '.join(parts)
                         + ' (yfinance, rank 2, unofficial).', [item], 'market_fact'))
    return rows, items


def _row(name, at_p, at_c, change, rule, flag, source):
    return {'indicator': name, 'p': at_p, 'c': at_c, 'change': change, 'rule': rule, 'flag': flag,
            'source': source}


# ---------------------------------------------------------------- SEC fundamentals

def _xbrl_published(ctx, ticker, tags, as_of, known_at):
    """Latest publication instant of the balance-sheet facts used (stored XBRL rows), or None."""
    pubs = []
    for tag in tags or []:
        try:
            rows = ctx.db.series(ticker, f'xbrl:{tag}', known_at=known_at, source=SEC_SOURCE,
                                 start=as_of, end=as_of)
        except Exception:  # noqa: BLE001 - provenance lookup only
            continue
        pubs += [r.get('published_at') for _, r in rows if r.get('published_at')]
    return max(pubs) if pubs else None


def _fundamental_rows(ctx, res, ticker, thr):
    tm = ctx.tm
    names = ('debt-to-equity (SEC XBRL)', 'debt (SEC XBRL, USD)')
    fc = ctx.sec.fundamentals(ticker, known_at=tm.cutoff) or {}
    fp = ctx.sec.fundamentals(ticker, known_at=tm.previous_cutoff) or {}
    if fc.get('status') != 'OK' and fc.get('debt') is None:
        reason = fc.get('reason') or 'SEC fundamentals unavailable'
        for n in names:
            res.add(unavailable(ticker, Q, n, reason))
        return [_row(n, None, None, None, 'N/A', None, 'SEC EDGAR (rank 1)') for n in names], []
    rows, parts = [], []
    de_c, de_p = _num(fc.get('debt_to_equity')), _num(fp.get('debt_to_equity'))
    t = _num(thr.get('debt_to_equity_change_abs'))
    ch = de_c - de_p if de_c is not None and de_p is not None else None
    flag = None if ch is None else (NOT_ASSESSED if t is None else ch >= t)
    rows.append(_row(names[0], de_p, de_c, None if ch is None else f'{ch:+.3f}',
                     f'change >= {t}' if t is not None else NOT_ASSESSED, flag, 'SEC EDGAR (rank 1)'))
    if de_c is None:
        res.add(unavailable(ticker, Q, names[0] + ' at T_c', fc.get('reason') or 'not computable'))
    if de_p is None:
        res.add(unavailable(ticker, Q, names[0] + ' at T_p', fp.get('reason') or 'not computable'))

    db_c, db_p = _num(fc.get('debt')), _num(fp.get('debt'))
    t2 = _num(thr.get('debt_change_rel'))
    rel = db_c / db_p - 1 if db_c is not None and db_p else None
    flag2 = None if rel is None else (NOT_ASSESSED if t2 is None else rel >= t2)
    rows.append(_row(names[1], db_p, db_c, None if rel is None else f'{100 * rel:+.1f}% relative',
                     f'relative change >= {t2}' if t2 is not None else NOT_ASSESSED, flag2, 'SEC EDGAR (rank 1)'))
    if db_c is None:
        res.add(unavailable(ticker, Q, names[1] + ' at T_c', fc.get('reason') or 'no recognised debt concept'))

    bsd_c, bsd_p = fc.get('balance_sheet_date'), fp.get('balance_sheet_date')
    if de_c is not None or db_c is not None:
        parts.append(f'debt-to-equity {_fmt(de_p, ".3f")} (balance sheet {bsd_p}, as known at T_p) -> '
                     f'{_fmt(de_c, ".3f")} (balance sheet {bsd_c}, as known at T_c)')
        parts.append(f'debt USD {_fmt(db_p and db_p / 1e9, ".3f")} bn -> {_fmt(db_c and db_c / 1e9, ".3f")} bn')
        if bsd_c != bsd_p:
            parts.append('a new balance sheet became public between T_p and T_c')
    items = []
    if parts:
        tags = [fc.get('equity_tag')] + list(fc.get('debt_tags') or [])
        pub = _xbrl_published(ctx, ticker, [x for x in tags if x], bsd_c, tm.cutoff)
        fetch = fc.get('fetch') or {}
        item = evidence(tm, SEC_SOURCE, SEC_RANK, f'{ticker}: ' + '; '.join(parts), as_of=bsd_c,
                        published_at=pub, retrieved_at=fetch.get('retrieved_at') if pub else None,
                        fetch_id=fetch.get('fetch_id'),
                        fresh=fresh_flag(ctx, pub, 'quarterly_filing') if pub else None,
                        basis='latest acceptance time of the XBRL facts used' if pub
                        else 'publication time not found in stored XBRL facts')
        items.append(item)
        rules = [r for r in (t, t2) if r is not None]
        res.add(conclude(ticker, Q, f'{ticker} balance-sheet indicators: ' + '; '.join(parts)
                         + ('' if rules else '; no pre-declared threshold, change not assessed') + ' (SEC XBRL).',
                         [item], 'official_fact'))
    return rows, items


# ---------------------------------------------------------------- insider sales

def _minus_days(instant, days):
    return to_utc_iso(datetime.fromisoformat(instant) - timedelta(days=days))


def _insider_window(ctx, ticker, end):
    start = _minus_days(end, INSIDER_DAYS)
    events = ctx.db.events(ticker, FORM4_METRIC, published_from=start, published_to=end, source=SEC_SOURCE)
    txns, bad = [], 0
    for e in events:
        try:
            t = json.loads(e.get('value_text') or '')
        except (TypeError, ValueError):
            bad += 1
            continue
        if not isinstance(t, dict):
            bad += 1
            continue
        txns.append(t)
    disc = [t for t in txns if t.get('code') == 'S' and t.get('rule_10b5_1') is not True]
    valued = [_num(t.get('value_usd')) for t in disc]
    sellers = {(t.get('owners') or [t.get('accession')])[0] for t in disc}
    return {'start': start, 'end': end, 'value': round(sum(v for v in valued if v is not None), 2),
            'no_value': sum(1 for v in valued if v is None), 'sellers': len(sellers), 'sales': len(disc),
            'accessions': {t.get('accession') for t in txns if t.get('accession')}, 'bad': bad,
            'n_txns': len(txns)}


def _insider_rows(ctx, res, ticker, thr, feed):
    tm = ctx.tm
    names = ('discretionary insider sales, 90 days (USD)', 'distinct discretionary sellers, 90 days')
    stored = ctx.db.events(ticker, FORM4_METRIC, source=SEC_SOURCE)
    if not stored:
        for n in names:
            res.add(unavailable(ticker, Q, n, f'no Form 4 transaction stored for {ticker}: not ingested'))
        return [_row(n, None, None, None, 'N/A', None, 'SEC EDGAR Form 4 (rank 1)') for n in names], []
    earliest = min(e['available_at'] for e in stored if e.get('available_at'))
    w_c = _insider_window(ctx, ticker, tm.cutoff)
    w_p = _insider_window(ctx, ticker, tm.previous_cutoff)
    codes, notes = [], []
    for label, w in (('T_p', w_p), ('T_c', w_c)):
        if w['start'] < earliest:
            codes.append('PARTIAL_COVERAGE')
            notes.append(f'the 90-day window ending {label} starts {w["start"]}, before the earliest stored '
                         f'transaction ({earliest})')
        if w['no_value']:
            codes.append('PARTIAL_COVERAGE')
            notes.append(f'{w["no_value"]} discretionary sale(s) without a USD value in the window ending {label}')
        if w['bad']:
            codes.append('PARTIAL_COVERAGE')
            notes.append(f'{w["bad"]} unreadable stored transaction(s) in the window ending {label}')
    fresh = None
    if feed.get('status') == 'OK':
        fresh = True if feed.get('retrieved_after_cutoff') else None
        listed = [f for f in feed.get('filings') or [] if f.get('published_at')]
        oldest = min((f['published_at'] for f in listed), default=None)
        for label, w in (('T_p', w_p), ('T_c', w_c)):
            f4 = {f['accession_number'] for f in listed if f.get('form') == '4'
                  and w['start'] < f['published_at'] <= w['end']}
            unmatched = f4 - w['accessions']
            if oldest is None or oldest > w['start']:
                codes.append('PARTIAL_COVERAGE')
                notes.append(f'the SEC submissions feed does not reach back to the start of the window ending {label}')
            if unmatched:
                codes.append('PARTIAL_COVERAGE')
                notes.append(f'{len(unmatched)} of {len(f4)} Form 4 filings listed by SEC in the window ending '
                             f'{label} have no stored non-derivative transaction (derivative-only filings or '
                             'documents not ingested: not distinguishable from stored data)')
    else:
        notes.append(f'SEC submissions feed unavailable ({feed.get("reason")}): Form 4 coverage not verified')

    rows = []
    t_ratio, t_min = _num(thr.get('insider_sale_value_ratio')), _num(thr.get('insider_sale_min_usd'))
    flag = (NOT_ASSESSED if t_ratio is None or t_min is None
            else (w_c['value'] >= t_ratio * w_p['value'] and w_c['value'] >= t_min))
    rows.append(_row(names[0], w_p['value'], w_c['value'], f'{w_c["value"] - w_p["value"]:+,.0f}',
                     f'>= {t_ratio}x T_p and >= {t_min} USD' if flag != NOT_ASSESSED else NOT_ASSESSED, flag,
                     'SEC EDGAR Form 4 (rank 1)'))
    t_s = _num(thr.get('discretionary_sellers_change_abs'))
    flag_s = NOT_ASSESSED if t_s is None else (w_c['sellers'] - w_p['sellers'] >= t_s)
    rows.append(_row(names[1], w_p['sellers'], w_c['sellers'], f'{w_c["sellers"] - w_p["sellers"]:+d}',
                     f'change >= {t_s}' if t_s is not None else NOT_ASSESSED, flag_s, 'SEC EDGAR Form 4 (rank 1)'))
    fact = (f'{ticker}: discretionary open-market sales (no Rule 10b5-1 box) over the 90 days ending T_p: '
            f'USD {w_p["value"]:,.0f}, {w_p["sales"]} transaction(s), {w_p["sellers"]} distinct seller(s); ending '
            f'T_c: USD {w_c["value"]:,.0f}, {w_c["sales"]} transaction(s), {w_c["sellers"]} distinct seller(s)')
    item = evidence(tm, SEC_SOURCE, SEC_RANK, fact, as_of=tm.cutoff[:10], published_at=tm.cutoff,
                    retrieved_at=(feed.get('fetch') or {}).get('retrieved_at'),
                    fetch_id=(feed.get('fetch') or {}).get('fetch_id'), fresh=fresh,
                    basis='window aggregate: every included Form 4 was accepted by the window end; coverage '
                          'checked against the SEC submissions feed retrieved after the cutoff')
    assessed = flag != NOT_ASSESSED or flag_s != NOT_ASSESSED
    res.add(conclude(ticker, Q, fact + ('' if assessed else '; no pre-declared threshold, change not assessed')
                     + (f' (coverage: {"; ".join(notes)})' if notes else '') + ' (SEC Form 4).',
                     [item], 'official_fact', reason_codes=codes,
                     resolve='complete Form 4 ingestion for both windows' if codes else None))
    return rows, [item]


# ---------------------------------------------------------------- red-flag filings

def red_flag(filing):
    """Description of the red flag carried by a filing, or None."""
    form = (filing.get('form') or '').strip()
    if form in RED_FLAG_FORMS:
        return form
    if form in EIGHT_K_FORMS:
        hits = [i for i in filing.get('items') or [] if i in RED_FLAG_ITEMS]
        if hits:
            return f'{form} item ' + ', '.join(f'{i} ({RED_FLAG_ITEMS[i]})' for i in hits)
    return None


def _red_flag_rows(ctx, res, ticker, feed):
    tm = ctx.tm
    name = 'red-flag SEC filings in the week (count)'
    if feed.get('status') != 'OK':
        res.add(unavailable(ticker, Q, name, f'SEC submissions feed unavailable: {feed.get("reason")}'))
        return [_row(name, None, None, None, 'any red-flag filing in P', None, 'SEC EDGAR (rank 1)')], []
    t_pp = end_of_us_trading_day_utc(tm.sessions[-2 * WEEK - 1])
    listed = [f for f in feed.get('filings') or [] if f.get('published_at')]
    oldest = min((f['published_at'] for f in listed), default=None)

    def window(lo, hi):
        return [f for f in listed if lo < f['published_at'] <= hi]
    cur, prev = window(tm.previous_cutoff, tm.cutoff), window(t_pp, tm.previous_cutoff)
    flags_c = [(f, red_flag(f)) for f in cur if red_flag(f)]
    flags_p = [(f, red_flag(f)) for f in prev if red_flag(f)]
    no_items = [f for f in cur if f.get('form') in EIGHT_K_FORMS and not f.get('items')]
    codes = []
    if oldest is None or oldest > tm.previous_cutoff:
        codes.append('PARTIAL_COVERAGE')
    if no_items:
        codes.append('PARTIAL_COVERAGE')
    prev_count = None if oldest is None or oldest > t_pp else len(flags_p)
    row = _row(name, prev_count, len(flags_c), None if prev_count is None else f'{len(flags_c) - prev_count:+d}',
               'any red-flag filing in P = (T_p, T_c]', bool(flags_c), 'SEC EDGAR (rank 1)')
    fetch = feed.get('fetch') or {}
    items = []
    if flags_c:
        for f, desc in flags_c:
            items.append(evidence(tm, SEC_SOURCE, SEC_RANK,
                                  f'{ticker}: {desc}, accession {f.get("accession_number")}, filing date '
                                  f'{f.get("filing_date")}', as_of=f.get('filing_date'),
                                  published_at=f['published_at'], retrieved_at=fetch.get('retrieved_at'),
                                  fetch_id=fetch.get('fetch_id'),
                                  fresh=fresh_flag(ctx, f['published_at'], 'quarterly_filing'),
                                  basis=f.get('published_at_basis')))
        res.add(conclude(ticker, Q, f'{ticker}: red-flag SEC filing(s) accepted in the week: '
                         + '; '.join(f'{d} (accepted {f["published_at"]})' for f, d in flags_c)
                         + ' (SEC EDGAR, rank 1).', items, 'official_fact', reason_codes=codes))
    elif not feed.get('retrieved_after_cutoff'):
        res.add(unavailable(ticker, Q, 'absence of red-flag filings in the week',
                            'the SEC submissions feed was retrieved before the cutoff: a negative fact needs a '
                            'fetch made after the cutoff covering the whole window'))
    else:
        item = evidence(tm, SEC_SOURCE, SEC_RANK,
                        f'{ticker}: {len(cur)} filings accepted in (T_p, T_c], none with a red-flag form or 8-K item',
                        as_of=tm.cutoff[:10], published_at=tm.cutoff, retrieved_at=fetch.get('retrieved_at'),
                        fetch_id=fetch.get('fetch_id'), fresh=True,
                        basis='negative fact over window P, from the SEC submissions feed retrieved after the cutoff')
        items.append(item)
        extra = (f'; {len(no_items)} 8-K without item codes in the feed' if no_items else '')
        res.add(conclude(ticker, Q, f'{ticker}: no red-flag SEC filing (8-K items {", ".join(RED_FLAG_ITEMS)}; '
                                    f'NT 10-K / NT 10-Q) was accepted in (T_p, T_c] ({len(cur)} filing(s) in the '
                                    f'window{extra}; SEC EDGAR, rank 1).', [item], 'official_fact',
                         reason_codes=codes))
    return [row], items


# ---------------------------------------------------------------- market stress (FRED)

def weekly_changes(points):
    """Friday-to-Friday changes of the last observation of each week (consecutive weeks only)."""
    weeks = {}
    for d, v in sorted(points, key=lambda p: str(p[0])[:10]):
        v = _num(v)
        if v is None:
            continue
        day = date.fromisoformat(str(d)[:10])
        weeks[day + timedelta(days=(4 - day.weekday()) % 7)] = v
    keys = sorted(weeks)
    return [weeks[b] - weeks[a] for a, b in zip(keys, keys[1:]) if (b - a).days == 7]


def _stress_rows(ctx, res):
    tm = ctx.tm
    rows, items, flagged = [], [], []
    for sid, cadence, label in STRESS_SERIES:
        st = ctx.fred(sid)
        if st.get('status') != 'OK':
            res.add(unavailable('overall', Q, f'{sid} ({label})', f'FRED: {st.get("reason")}'))
            rows.append([sid, label] + [None] * 8 + [None])
            continue
        now, prev = ctx.value_at(sid, tm.cutoff), ctx.value_at(sid, tm.previous_cutoff)
        if not now or not prev:
            res.add(unavailable('overall', Q, f'{sid} ({label})',
                                f'no observation known at {"the cutoff" if not now else "the previous cutoff"}'))
            rows.append([sid, label] + [None] * 8 + [None])
            continue
        (d_c, v_c, pub_c), (d_p, v_p, pub_p) = now, prev
        d_c, d_p, v_c, v_p = str(d_c)[:10], str(d_p)[:10], _num(v_c), _num(v_p)
        changes = weekly_changes(ctx.series_at(sid, tm.previous_cutoff))
        sd = _std(changes) if len(changes) >= MIN_WEEKLY_CHANGES else None
        delta = v_c - v_p if v_c is not None and v_p is not None else None
        revised = {str(d)[:10]: _num(v) for d, v in ctx.series_at(sid, tm.cutoff, start=d_p)}.get(d_p)
        revision = revised - v_p if revised is not None and v_p is not None else None
        new_obs = d_c != d_p
        if delta is None:
            flag = None
        elif not new_obs:
            flag = False
        else:
            flag = None if sd is None else delta > sd
        if sd is None:
            res.add(unavailable('overall', Q, f'{sid} increase rule', f'{len(changes)} weekly changes in the '
                                f'history known at T_p (minimum {MIN_WEEKLY_CHANGES})'))
        if flag:
            flagged.append(sid)
        rows.append([sid, label, d_p, v_p, d_c, v_c, _r(delta), _r(sd), len(changes), _r(revision),
                     _yes(flag) if new_obs else 'no (no new observation)'])
        codes = []
        if new_obs and delta and revision and abs(revision) >= abs(delta):
            codes.append('FIRST_PRINT_WITHIN_REVISION_NOISE')
        fetch = st.get('fetch') or {}
        fact = (f'{sid} {d_p} = {v_p} (published {pub_p}, as known at T_p) -> {d_c} = {v_c} (published '
                f'{pub_c}, as known at T_c)')
        item = evidence(tm, FRED_SOURCE, FRED_RANK, fact, as_of=d_c, published_at=pub_c,
                        retrieved_at=fetch.get('retrieved_at'), fetch_id=fetch.get('fetch_id'),
                        fresh=fresh_flag(ctx, d_c, cadence), basis='FRED vintage date, end of day New York')
        items.append(item)
        if not new_obs:
            text = f'{sid}: no new observation between T_p and T_c (latest {d_c} = {v_c})'
        elif delta is None:
            text = f'{sid}: {d_p} -> {d_c}, change not computable (missing value)'
        else:
            verdict = ('rule not assessed' if sd is None else
                       f'{"beyond" if flag else "not beyond"} the rule increase > 1 sd of weekly changes '
                       f'({sd:.4g}, {len(changes)} weeks as known at T_p)')
            text = f'{sid}: {v_p} ({d_p}) -> {v_c} ({d_c}), change {delta:+.4g}; {verdict}'
        if revision:
            text += f'; the {d_p} value was revised by {revision:+.4g} between T_p and T_c'
            if new_obs and delta is not None:
                text += f' (change vs the revised value: {v_c - revised:+.4g})'
        res.add(conclude('overall', Q, text + ' (FRED, rank 1).', [item], 'official_fact', reason_codes=codes))
    res.table('Market stress indicators (FRED, rank 1)',
              ['series', 'description', 'obs date (T_p)', 'value (T_p)', 'obs date (T_c)', 'value (T_c)', 'change',
               '1 sd of weekly changes (known at T_p)', 'weekly changes used', 'revision of the T_p obs by T_c',
               'increased'], rows, question=Q,
              note=('Values as known at T_p and at T_c (FRED vintages). Rule (documented, not validated): increased = '
                    'change > 1 sample standard deviation of the Friday-to-Friday changes (last observation of each '
                    f'week) of the series as known at T_p, at least {MIN_WEEKLY_CHANGES} changes. Higher = more '
                    'stress for all four series. FIRST_PRINT_WITHIN_REVISION_NOISE when the T_p observation was '
                    f'revised by at least the size of the change. Thresholds {thresholds_version(ctx)}.'))
    if items:
        text = (f'Market stress indicators beyond their rule this week: {", ".join(flagged)}' if flagged
                else 'No market stress indicator was beyond its rule this week')
        res.add(conclude('overall', Q, text + '. Reading this as a change in market risk is an interpretation '
                         '(no validated risk model).', items, 'interpretation', reason_codes=['HEURISTIC_THRESHOLD']))
    return flagged


# ---------------------------------------------------------------- section

def build(ctx):
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    thr = thresholds(ctx)
    flag_counts = {}
    for ticker in ctx.universe:
        feed = ctx.filings(ticker) or {}
        rows, items = [], []
        for part in (_price_rows(ctx, res, ticker, thr), _fundamental_rows(ctx, res, ticker, thr),
                     _insider_rows(ctx, res, ticker, thr, feed), _red_flag_rows(ctx, res, ticker, feed)):
            rows += part[0]
            items += part[1]
        res.table(f'{ticker} — risk indicators (T_p vs T_c)',
                  ['indicator', 'as known at T_p', 'as known at T_c', 'change', 'pre-declared rule', 'increased',
                   'source'],
                  [[r['indicator'], r['p'], r['c'], r['change'], r['rule'], _yes(r['flag']), r['source']]
                   for r in rows], scope=ticker, question=Q,
                  note=(f'Full pre-declared table (decreases and unchanged rows included). T_p = {tm.previous_cutoff}, '
                        f'T_c = {tm.cutoff}. Thresholds {thresholds_version(ctx)}: {json.dumps(thr, sort_keys=True)}. '
                        'Rows without a pre-declared threshold are shown but not assessed. Risk indicators have not '
                        'been shown to predict losses.'))
        beyond = [r['indicator'] for r in rows if r['flag'] is True]
        assessed = [r['indicator'] for r in rows if isinstance(r['flag'], bool)]
        not_assessed = [r['indicator'] for r in rows if r['flag'] == NOT_ASSESSED]
        missing = [r['indicator'] for r in rows if r['flag'] is None]
        for r in rows:
            c = flag_counts.setdefault(r['indicator'], [0, 0])
            if isinstance(r['flag'], bool):
                c[1] += 1
                c[0] += r['flag']
        if not items:
            res.add(unavailable(ticker, Q, 'risk judgement', 'no risk indicator could be computed'))
            continue
        tail = (f'{len(assessed)} indicators assessed' + (f'; not assessed (no threshold): {", ".join(not_assessed)}'
                                                          if not_assessed else '')
                + (f'; unavailable: {", ".join(missing)}' if missing else ''))
        if beyond:
            text = (f'{ticker}: indicators beyond their pre-declared rule between T_p and T_c: {", ".join(beyond)} '
                    f'({tail}). Whether {ticker}\'s risk increased is an interpretation: no validated risk model.')
        else:
            text = (f'{ticker}: no assessed indicator was beyond its pre-declared rule between T_p and T_c ({tail}). '
                    'This does not show that risk did not increase: interpretation, no validated risk model.')
        res.add(conclude(ticker, Q, text, items, 'interpretation',
                         reason_codes=['HEURISTIC_THRESHOLD'] + (['PARTIAL_COVERAGE'] if missing else [])))

    flagged_market = _stress_rows(ctx, res)
    res.table('Companies per flag', ['indicator', 'companies beyond the rule', 'companies assessed'],
              [[k, v[0], v[1]] for k, v in flag_counts.items()]
              + [['market stress series beyond the rule', len(flagged_market), len(STRESS_SERIES)]],
              question=Q, note=f'Thresholds {thresholds_version(ctx)}.')
    res.add(unavailable('overall', Q, 'risk_score', 'NOT IMPLEMENTED: no risk model exists (risk engine is phase '
                                                    'P3.1); no aggregate risk score is computed'))
    res.add(unavailable('overall', Q, 'options implied volatility', 'not ingested: no options data source is '
                        'wired into the pipeline (Yahoo options endpoint and cboe.com were unreachable from this '
                        'machine when probed on 2026-10-07)'))
    res.add(unavailable('overall', Q, 'short interest', 'not ingested: no short-interest source is wired into the '
                        'pipeline (FINRA hosts blocked and Yahoo quoteSummary unauthorised when probed on 2026-10-07)'))
    res.notes.append(f'T_p = {tm.previous_cutoff}, T_c = {tm.cutoff}; thresholds {thresholds_version(ctx)}. Optional '
                     f'threshold keys honoured if added to config: {", ".join(OPTIONAL_THRESHOLDS)}. Timing only: no '
                     'causal link and no prediction is asserted.')
    return res
