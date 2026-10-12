#!/usr/bin/env python3
"""
Weekly report section 'commodities' - Q3 "What changed in the macro environment?" (master mission P1)

Pre-declared commodity series (COMMODITIES), each with its source and rank:
  official (rank 1, FRED vintages known at T_c / T_p): EIA daily spot prices (WTI, Brent, Henry Hub), IMF monthly
    global prices (copper, aluminium, nickel, iron ore, zinc, uranium, coal, EU natural gas, wheat, corn, metal and
    all-commodity indexes), BLS producer price index for hot-rolled steel, BLS import price index of nonmonetary gold
  secondary (rank 2, yfinance continuous front-month futures, closes up to s_0): gold, silver, copper, platinum.
    A continuous futures series rolls from one contract to the next: a roll can create a jump that is not a price
    move (stated in every output).
For each: latest value known at T_c with its date, change vs the value known at T_p, change over ~1, 3 and 12
months (by observation date), and the percentile of the latest value in the history held (descriptive).
Unavailable by design (no allowed source): rare earths (NdPr), lithium, cobalt; LBMA gold (licensed; removed from
FRED); exchange settlement prices (CME / LME data are licensed).

Company exposure (EXPOSURE): a pre-declared map from companies of the configured universe to the commodities
whose prices plausibly affect them, with the mechanism and its basis. It is an interpretation (kind
'interpretation', UNCERTAIN by rule): no sensitivity is estimated and no company move is attributed to a
commodity move. Sections never call the wall clock and never write files.
"""

import bisect
from datetime import date, timedelta

from ...common import to_utc_iso
from ...database import source_rank
from ..core import SectionResult, conclude, evidence, unavailable

NAME = 'commodities'
QUESTIONS = [3]
FRED, YF = 'FRED', 'yfinance'

# id: (label, unit, source kind, cadence)
COMMODITIES = {
    'DCOILWTICO': ('Crude oil WTI, Cushing spot (EIA)', 'USD/barrel', 'fred', 'daily'),
    'DCOILBRENTEU': ('Crude oil Brent, Europe spot (EIA)', 'USD/barrel', 'fred', 'daily'),
    'DHHNGSP': ('Natural gas, Henry Hub spot (EIA)', 'USD/MMBtu', 'fred', 'daily'),
    'PNGASEUUSDM': ('Natural gas, EU (IMF)', 'USD/MMBtu', 'fred', 'monthly'),
    'PCOALAUUSDM': ('Coal, Australia (IMF)', 'USD/metric ton', 'fred', 'monthly'),
    'PCOPPUSDM': ('Copper (IMF)', 'USD/metric ton', 'fred', 'monthly'),
    'PALUMUSDM': ('Aluminium (IMF)', 'USD/metric ton', 'fred', 'monthly'),
    'PNICKUSDM': ('Nickel (IMF)', 'USD/metric ton', 'fred', 'monthly'),
    'PZINCUSDM': ('Zinc (IMF)', 'USD/metric ton', 'fred', 'monthly'),
    'PIORECRUSDM': ('Iron ore (IMF)', 'USD/dry metric ton', 'fred', 'monthly'),
    'PURANUSDM': ('Uranium (IMF)', 'USD/pound', 'fred', 'monthly'),
    'WPU101704': ('Hot-rolled steel, producer price index (BLS)', 'index 1982 = 100', 'fred', 'monthly'),
    'IR14270': ('Nonmonetary gold, import price index (BLS)', 'index', 'fred', 'monthly'),
    'PWHEAMTUSDM': ('Wheat (IMF)', 'USD/metric ton', 'fred', 'monthly'),
    'PMAIZMTUSDM': ('Corn (IMF)', 'USD/metric ton', 'fred', 'monthly'),
    'PMETAINDEXM': ('Metals price index (IMF)', 'index 2016 = 100', 'fred', 'monthly'),
    'PALLFNFINDEXM': ('All-commodity price index (IMF)', 'index 2016 = 100', 'fred', 'monthly'),
    'GC=F': ('Gold, front-month futures (COMEX, via yfinance)', 'USD/troy ounce', 'futures', 'daily_market'),
    'SI=F': ('Silver, front-month futures (COMEX, via yfinance)', 'USD/troy ounce', 'futures', 'daily_market'),
    'HG=F': ('Copper, front-month futures (COMEX, via yfinance)', 'USD/pound', 'futures', 'daily_market'),
    'PL=F': ('Platinum, front-month futures (NYMEX, via yfinance)', 'USD/troy ounce', 'futures', 'daily_market'),
}
NO_SOURCE = (
    ('rare earth prices (NdPr oxide and others)', 'no free official price series; published by price-reporting '
     'agencies under licence (and by producers in their filings as realised prices, as text)'),
    ('lithium prices (carbonate / hydroxide)', 'no free official price series; exchange and price-reporting data '
     'are licensed'),
    ('cobalt price', 'not in the IMF series on FRED; no other allowed source'),
    ('LBMA gold price', 'licensed and withdrawn from FRED; gold is shown from front-month futures (secondary) and '
     'the BLS import price index instead'),
)
# company: [(commodity ids, mechanism, basis)]
EXPOSURE = {
    'XOM': [(('DCOILWTICO', 'DCOILBRENTEU', 'DHHNGSP'), 'upstream revenue and margins move with realised oil and '
             'gas prices', '10-K: oil and natural gas production and sales')],
    'CVX': [(('DCOILWTICO', 'DCOILBRENTEU', 'DHHNGSP'), 'upstream revenue and margins move with realised oil and '
             'gas prices', '10-K: oil and natural gas production and sales')],
    'FCX': [(('PCOPPUSDM', 'HG=F', 'GC=F'), 'revenue moves with copper and gold prices', '10-K: copper, gold and '
             'molybdenum mining')],
    'NUE': [(('WPU101704', 'PIORECRUSDM'), 'steel selling prices versus raw-material costs', '10-K: steel '
             'production from scrap and iron units')],
    'ALB': [((), 'revenue moves with lithium prices (no allowed price source)', '10-K: lithium producer')],
    'MP': [((), 'revenue moves with rare-earth (NdPr) prices (no allowed price source)', '10-K: rare-earth '
            'mining and processing')],
    'DE': [(('PMAIZMTUSDM', 'PWHEAMTUSDM'), 'farm income, and so demand for agricultural equipment, moves with crop '
            'prices', '10-K: agricultural equipment segment')],
    'CAT': [(('PCOPPUSDM', 'PIORECRUSDM', 'PCOALAUUSDM'), 'mining equipment demand follows mining activity',
             '10-K: resource industries segment')],
    'BA': [(('PALUMUSDM',), 'aluminium is an input cost (contracts and hedges dampen it)', 'aerospace materials')],
    'LMT': [(('PALUMUSDM', 'PNICKUSDM'), 'aluminium and nickel alloys are input costs (largely contract-passed)',
             'defence aerospace materials')],
}
MONTHS = {'1m': 30, '3m': 91, '12m': 365}


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _change(series, day, days):
    """(change % between the value of `day` and the latest value on or before day - days) or None."""
    dates = [d for d, _ in series]
    target = (date.fromisoformat(day) - timedelta(days=days)).isoformat()
    i = bisect.bisect_right(dates, target) - 1
    if i < 0:
        return None
    base, now = series[i][1], dict(series)[day]
    return None if not base else round((now / base - 1) * 100, 2)


def _shown(v):
    return f'{v:,.0f}' if abs(v) >= 1e4 else f'{v:,.2f}' if abs(v) >= 1 else f'{v:.4f}'


def _signed(v):
    return 'n/a' if v is None else f'{v:+.2f}%'


def _percentile(series, value):
    vals = [v for _, v in series]
    if len(vals) < 12 or value is None:
        return None
    return round((sum(v < value for v in vals) + 0.5 * sum(v == value for v in vals)) / len(vals) * 100, 1)


def _fred(ctx, sid):
    st = ctx.fred(sid) or {}
    if st.get('status') != 'OK':
        return None, f"FRED {sid}: {st.get('reason') or 'unavailable'}"
    out = {}
    for which, instant in (('c', ctx.tm.cutoff), ('p', ctx.tm.previous_cutoff)):
        rows = [(str(d)[:10], _num(v)) for d, v in ctx.series_at(sid, instant)]
        out[which] = [(d, v) for d, v in rows if v is not None]
    if not out['c']:
        return None, f'FRED {sid}: no observation known at the cutoff'
    got = ctx.value_at(sid, ctx.tm.cutoff)
    out['published_at'] = got[2] if got else None
    out['fetch'] = st.get('fetch') or {}
    return out, None


def _futures(ctx, ticker):
    p = ctx.prices(ticker)
    frame = p.get('frame')
    if p.get('status') != 'OK' or frame is None or not len(frame):
        return None, f"{ticker}: {p.get('reason') or 'no price data'}"
    rows = [(d.date().isoformat() if hasattr(d, 'date') else str(d)[:10], _num(v)) for d, v in frame['close'].items()]
    rows = [(d, v) for d, v in rows if v is not None and v > 0]
    if not rows:
        return None, f'{ticker}: no close up to s_0'
    prev = [r for r in rows if r[0] <= ctx.tm.previous_week[-1]]
    return {'c': rows, 'p': prev, 'fetch': p.get('fetch') or {}}, None


def build(ctx, series=None):
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    selected = list(series or COMMODITIES)
    rows, facts = [], {}
    for cid in selected:
        label, unit, kind, cadence = COMMODITIES[cid]
        got, reason = (_fred(ctx, cid) if kind == 'fred' else _futures(ctx, cid)) if hasattr(ctx, 'fred') \
            else (None, 'no data accessor')
        if got is None:
            res.add(unavailable('overall', 3, label, reason))
            rows.append([label, 'FRED' if kind == 'fred' else 'yfinance', None, None, None, None, None, None, None,
                         reason])
            continue
        day, value = got['c'][-1]
        prev = got['p'][-1] if got['p'] else None
        week = None if not prev or not prev[1] else round((value / prev[1] - 1) * 100, 2)
        changes = {k: _change(got['c'], day, d) for k, d in MONTHS.items()}
        pct = _percentile(got['c'], value)
        rows.append([label, 'FRED' if kind == 'fred' else 'yfinance (rank 2)', unit, day, round(value, 4),
                     None if not prev else f'{_shown(prev[1])} ({prev[0]})', week, changes['1m'], changes['3m'],
                     f"12m {changes['12m']}; percentile {pct} of {len(got['c'])} obs"])
        fetch = got['fetch']
        status = (ctx.freshness(day, cadence) or {}).get('status')
        fresh = True if status == 'FRESH' else False if status == 'STALE' else None
        if kind == 'fred':
            item = evidence(tm, FRED, source_rank(FRED), f'{label}: {value} {unit} ({day})', as_of=day,
                            published_at=got['published_at'], retrieved_at=fetch.get('retrieved_at'),
                            fetch_id=fetch.get('fetch_id'), fresh=fresh, basis='FRED vintage known at the cutoff')
            kind_out, codes = 'official_fact', []
        else:
            from ...market_data import session_close_utc
            item = evidence(tm, YF, source_rank(YF), f'{label}: {value} {unit} ({day})', as_of=day,
                            published_at=session_close_utc(day), retrieved_at=fetch.get('retrieved_at'),
                            fetch_id=fetch.get('fetch_id'), fresh=fresh, basis='session close 21:00 UTC (estimate)')
            kind_out, codes = 'market_fact', []
        facts[cid] = (label, value, unit, day, week, changes, item)
        text = (f'{label}: {_shown(value)} {unit} ({day}, latest known at the cutoff)'
                + (f'; {week:+.2f}% vs the value known at T_p ({prev[0]})' if week is not None and prev[0] != day
                   else '; no newer observation than at T_p' if prev and prev[0] == day else '')
                + ''.join(f'; {k} {v:+.2f}%' for k, v in changes.items() if v is not None)
                + ('. Continuous front-month futures: a contract roll can create a jump that is not a price move.'
                   if kind == 'futures' else '.'))
        res.add(conclude('overall', 3, text, [item], kind_out, reason_codes=codes))
    res.table('Commodities: latest values known at T_c', ['commodity', 'source', 'unit', 'date', 'value',
                                                          'value known at T_p (date)', 'change vs T_p (%)',
                                                          '~1 month (%)', '~3 months (%)', 'other'], rows,
              question=3, note='Official series are FRED vintages (EIA, IMF, BLS) known at each cutoff; monthly IMF '
                               'series are published with a lag of several weeks. Futures are a secondary source '
                               '(yfinance, continuous front month). Percentile: position of the latest value in the '
                               'observations held (descriptive).')
    for item, reason in NO_SOURCE:
        res.add(unavailable('overall', 3, item, reason))
    for t in ctx.universe:
        for ids, mechanism, basis in EXPOSURE.get(t, []):
            have = [facts[i] for i in ids if i in facts]
            if not ids or not have:
                res.add(unavailable(t, 3, f'{t}: commodity exposure ({mechanism})',
                                    'no allowed price source for the commodity' if not ids
                                    else 'commodity series unavailable at the cutoff'))
                continue
            moves = '; '.join(f"{lab} {_signed(wk)} vs T_p, 3m {_signed(ch['3m'])}" for lab, _, _, _, wk, ch, _ in have)
            res.add(conclude(t, 3, f'{t}: pre-declared commodity exposure: {mechanism} (basis: {basis}). Latest '
                                   f'moves: {moves}. Interpretation: the direction and size of any effect on the '
                                   'company are not estimated, and no price move is attributed to it.',
                             [x[6] for x in have], 'interpretation'))
    res.notes.append('Commodity prices are economy-wide facts; links to companies are pre-declared interpretations '
                     '(EXPOSURE in src/weekly/sections/commodities.py), never estimated sensitivities.')
    res.notes.append(f'Window (T_p, T_c] = ({tm.previous_cutoff}, {to_utc_iso(tm.cutoff)}].')
    return res
