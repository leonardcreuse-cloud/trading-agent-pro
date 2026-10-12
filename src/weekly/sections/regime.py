#!/usr/bin/env python3
"""
Weekly report section 'regime' - market regime at T_c (master mission P5, report part 3), rules REGIME_RULES_VERSION

Pre-declared, rule-based description of the market environment known at the cutoff (no forecast):
  trend        benchmark (SPY) close vs its SMA50 / SMA200 and the SMA200 slope over 20 sessions
               (src/technicals.py trend rule): up / down / mixed
  volatility   VIX close (FRED VIXCLS vintages known at T_c) and its percentile over the last 756 observations:
               < 20 low, > 80 high, else normal
  credit       ICE BofA US high-yield option-adjusted spread (FRED BAMLH0A0HYM2) and its change over ~63
               observations (about 3 months): > +0.50 pp widening, < -0.50 pp tightening, else stable
  curve        10-year minus 2-year Treasury spread (FRED T10Y2Y): < 0 inverted, else positive
  real yield   10-year TIPS yield (FRED DFII10) and its change over ~21 observations: > +0.25 pp rising,
               < -0.25 pp falling, else stable
The regime labels are conventions (thresholds above, not validated); they describe conditions and are
interpretations (UNCERTAIN by rule). Sections never call the wall clock and never write files.
"""

from ...database import source_rank
from ...market_data import session_close_utc
from ...technicals import analyze
from ..core import SectionResult, conclude, evidence, unavailable
from .market import fresh_flag

NAME = 'regime'
QUESTIONS = [3]
REGIME_RULES_VERSION = 'regime-v1-2026-10-12'
FRED = 'FRED'
VIX_LOOKBACK = 756
CREDIT_WINDOW, CREDIT_PP = 63, 0.50
REAL_WINDOW, REAL_PP = 21, 0.25


def _fred(ctx, sid):
    st = ctx.fred(sid) or {}
    if st.get('status') != 'OK':
        return None, f"FRED {sid}: {st.get('reason') or 'unavailable'}"
    rows = [(str(d)[:10], v) for d, v in ctx.series_at(sid, ctx.tm.cutoff) if v is not None]
    if not rows:
        return None, f'FRED {sid}: no observation known at the cutoff'
    got = ctx.value_at(sid, ctx.tm.cutoff)
    fetch = st.get('fetch') or {}
    item = evidence(ctx.tm, FRED, source_rank(FRED), f'{sid} {rows[-1][1]} ({rows[-1][0]})', as_of=rows[-1][0],
                    published_at=got[2] if got else None, retrieved_at=fetch.get('retrieved_at'),
                    fetch_id=fetch.get('fetch_id'), fresh=fresh_flag(ctx, rows[-1][0], 'daily'),
                    basis='FRED vintage known at the cutoff')
    return {'rows': rows, 'item': item}, None


def _change(rows, n):
    return None if len(rows) <= n else rows[-1][1] - rows[-1 - n][1]


def build(ctx):
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    table, readings, items = [], [], []
    bench = (getattr(ctx, 'weekly', None) or {}).get('benchmark', 'SPY')
    p = ctx.prices(bench)
    frame = p.get('frame')
    if p.get('status') == 'OK' and frame is not None and len(frame) > 220:
        a = analyze(frame)
        trend = a['price_action'].get('trend') or {}
        day = frame.index[-1].date().isoformat() if hasattr(frame.index[-1], 'date') else str(frame.index[-1])[:10]
        fetch = p.get('fetch') or {}
        items.append(evidence(tm, 'yfinance', source_rank('yfinance'), f'{bench} adjusted closes up to {day}',
                              as_of=day, published_at=session_close_utc(day), retrieved_at=fetch.get('retrieved_at'),
                              fetch_id=fetch.get('fetch_id'), fresh=fresh_flag(ctx, day, 'daily_market'),
                              basis='session close 21:00 UTC (estimate)'))
        state = trend.get('state')
        table.append(['trend', f'{bench} vs SMA50 / SMA200', state,
                      f"SMA200 {'rising' if trend.get('sma200_rising') else 'not rising'}; "
                      f"{trend.get('persistence_above_sma50_60d')}% of the last 60 sessions above SMA50"])
        readings.append(f'trend {state}')
    else:
        res.add(unavailable('overall', 3, f'{bench} trend', f"{bench} prices unavailable or shorter than 220 sessions"))
    for sid, label, rule in (('VIXCLS', 'volatility (VIX)', 'vix'), ('BAMLH0A0HYM2', 'credit (high-yield spread)', 'credit'),
                             ('T10Y2Y', 'yield curve (10y - 2y)', 'curve'), ('DFII10', 'real yield (10y TIPS)', 'real')):
        got, reason = _fred(ctx, sid) if hasattr(ctx, 'fred') else (None, 'no FRED accessor')
        if got is None:
            res.add(unavailable('overall', 3, label, reason))
            table.append([label, sid, None, reason])
            continue
        rows, items = got['rows'], items + [got['item']]
        last = rows[-1][1]
        if rule == 'vix':
            hist = [v for _, v in rows[-VIX_LOOKBACK:]]
            pct = (sum(v < last for v in hist) + 0.5 * sum(v == last for v in hist)) / len(hist) * 100
            state = 'low' if pct < 20 else 'high' if pct > 80 else 'normal'
            detail = f'VIX {last} on {rows[-1][0]}, {pct:.0f}th percentile of {len(hist)} observations'
        elif rule == 'credit':
            ch = _change(rows, CREDIT_WINDOW)
            state = None if ch is None else 'widening' if ch > CREDIT_PP else 'tightening' if ch < -CREDIT_PP else 'stable'
            detail = f'{last} pp on {rows[-1][0]}; change over {CREDIT_WINDOW} observations ' + \
                     ('n/a' if ch is None else f'{ch:+.2f} pp')
        elif rule == 'curve':
            state = 'inverted' if last < 0 else 'positive'
            detail = f'{last} pp on {rows[-1][0]}'
        else:
            ch = _change(rows, REAL_WINDOW)
            state = None if ch is None else 'rising' if ch > REAL_PP else 'falling' if ch < -REAL_PP else 'stable'
            detail = f'{last}% on {rows[-1][0]}; change over {REAL_WINDOW} observations ' + \
                     ('n/a' if ch is None else f'{ch:+.2f} pp')
        table.append([label, sid, state, detail])
        readings.append(f'{label} {state}')
    res.table(f'Market regime at T_c (rules {REGIME_RULES_VERSION})', ['dimension', 'series', 'state', 'detail'],
              table, question=3, note='Thresholds are conventions declared in src/weekly/sections/regime.py, not '
                                      'validated. A regime label describes conditions; it is not a forecast.')
    if readings and items:
        res.add(conclude('overall', 3, 'Market regime at the cutoff (pre-declared rules ' + REGIME_RULES_VERSION + '): '
                         + '; '.join(readings) + '. A description of conditions, not a forecast.', items,
                         'interpretation'))
    return res
