#!/usr/bin/env python3
"""
Weekly report section 'agencies' - official agency data read directly from BLS, BEA and EIA (Q3 macro and
commodities, Q5 socio-economic) (phase P4.1).

Data: observations stored by `python main.py collect` (src/agency_apis.py), entities 'BLS:<id>', 'BEA:<code>',
'EIA:<series>'; this section downloads nothing. Each declared series is read as known at T_c and at T_p
(COALESCE(published_at, retrieved_at) <= T):
  BLS and EIA values carry no publication time: they are known from their retrieval, so a release counts at T_c
    only when a collect run retrieved it before the cutoff (run collect daily);
  BEA values are dated by their table's "LastRevised" date (end of day New York).
For each series: the latest period known at T_c, its value, the previous period's value in the same vintage
and their difference (values as published, no transformation). A period is "new in the window" only when the
series was already collected before T_p (some version known at T_p) and that period was not: for BEA it was
published in the window (table date); for BLS and EIA it was first RETRIEVED by the daily collection in the
window, which does not establish its release date. A series first collected in the window gets no statement.
Statements are official facts (rank 1); other series are listed in the table only. No consensus, surprise or
materiality is assessed; the FRED tables of the macro section remain the vintage-consistent view.
"""

from datetime import date, datetime

from ...agency_apis import BEA_TABLES, BLS_SERIES, EIA_ROUTES
from ..core import SectionResult, conclude, evidence, unavailable
from .market import fresh_flag

NAME = 'agencies'
QUESTIONS = [3, 5]
COLLECT_HINT = '`python main.py collect` stores these values; run it daily'
SOURCES = {'BLS': 'BLS', 'BEA': 'BEA', 'EIA': 'EIA'}
# entity -> (question, cadence for freshness of the period, label); labels and units come from agency_apis
LABOUR = ('LNS14000000', 'LNS11300000', 'CES0000000001', 'CES0500000003', 'CES0500000013', 'JTS000000000000000JOL')
DECLARED = {}
for _sid, (_label, _unit) in BLS_SERIES.items():
    DECLARED[f'BLS:{_sid}'] = (5 if _sid in LABOUR else 3, 'monthly', _label)
for _table, (_freq, _codes) in BEA_TABLES.items():
    for _code, (_label, _unit, _mult) in _codes.items():
        DECLARED[f'BEA:{_code}'] = (5 if _table == 'T20600' else 3, 'quarterly' if _freq == 'Q' else 'monthly',
                                    _label)
for _route, (_freq, _series) in EIA_ROUTES.items():
    for _sid, _label in _series.items():
        DECLARED[f'EIA:{_sid}'] = (3, 'daily' if _freq == 'daily' else 'weekly', _label)
# Freshness of a period: age of its start date (monthly 80 days, weekly 14, daily 7); a quarter is fresh
# when its first day is less than 200 days old (quarterly GDP is first released ~1 month after the quarter).
QUARTERLY_MAX_DAYS = 200


def _known(db, entity, source, known_at):
    """[(period, row)] of `entity` as known at `known_at` (one version per period)."""
    return [(d, r) for d, r in db.series(entity, 'value', known_at=known_at, source=source) if r['value'] is not None]


def _fresh(ctx, as_of, cadence):
    if cadence == 'quarterly':
        age = (datetime.fromisoformat(ctx.tm.cutoff).date() - date.fromisoformat(as_of)).days
        return age <= QUARTERLY_MAX_DAYS
    return fresh_flag(ctx, as_of, cadence)


def _fmt(v):
    return f'{v:,.0f}' if abs(v) >= 1000 else f'{v:,.3f}'.rstrip('0').rstrip('.')


def build(ctx):
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    rows = {3: [], 5: []}
    missing = {}
    for entity, (q, cadence, label) in DECLARED.items():
        agency = entity.split(':')[0]
        now = _known(ctx.db, entity, SOURCES[agency], tm.cutoff)
        if not now:
            missing.setdefault((q, agency), []).append(entity)
            rows[q].append([entity, label, None, None, None, None, None, None, 'not known at the cutoff'])
            continue
        before = {d for d, _ in _known(ctx.db, entity, SOURCES[agency], tm.previous_cutoff)}
        (d_c, r_c), prev = now[-1], (now[-2] if len(now) > 1 else None)
        new = bool(before) and d_c not in before
        diff = r_c['value'] - prev[1]['value'] if prev else None
        unit = r_c.get('unit') or ''
        status = ('known at T_p' if d_c in before else
                  'first collected in the window (release date not established)' if not before else
                  'published in the window' if agency == 'BEA' else 'first retrieved in the window')
        rows[q].append([entity, label, d_c, r_c['value'], unit, prev[0] if prev else None,
                        prev[1]['value'] if prev else None, None if diff is None else round(diff, 4), status])
        if not new:
            continue
        item = evidence(tm, agency, 1, f'{entity} {d_c} = {r_c["value"]}', as_of=d_c,
                        published_at=r_c['published_at'], retrieved_at=r_c['retrieved_at'], fetch_id=r_c['fetch_id'],
                        fresh=_fresh(ctx, d_c, cadence), basis=r_c['published_at_basis'])
        when = ('published in the window (BEA table date)' if agency == 'BEA' else
                f'first retrieved by the daily collection in the window ({agency} gives no publication time, so the '
                'release date is not established here)')
        text = (f'{agency} {label} ({entity}): {_fmt(r_c["value"])} {unit} for the period starting {d_c}, {when}'
                + (f'; previous period ({prev[0]}) {_fmt(prev[1]["value"])} in the same vintage, difference '
                   f'{diff:+,.4g}' if prev else '') + f' ({agency}, rank 1).')
        res.add(conclude('overall', q, text, [item], 'official_fact'))
    for (q, agency), entities in missing.items():
        reason = (f'no value known at the cutoff for {len(entities)} {agency} series ({", ".join(entities[:6])}'
                  + (', ...' if len(entities) > 6 else '') + ')')
        if agency in ('BLS', 'EIA'):
            reason += (f'; {agency} values carry no publication time and count from their retrieval, so only a '
                       'collect run before the cutoff makes them admissible')
        res.add(unavailable('overall', q, f'{agency} series read directly from the agency',
                            f'{reason}; {COLLECT_HINT}'))
    columns = ['series', 'description', 'latest period known at T_c', 'value', 'unit', 'previous period',
               'previous value (same vintage)', 'difference', 'status']
    note = ('Values as published by the agency (BLS, BEA, EIA; rank 1), read as known at the cutoff. BLS and EIA give '
            'no publication time (known from retrieval); BEA tables are dated by their LastRevised date. No '
            'consensus, surprise or materiality is assessed.')
    res.table('Official agency data — prices, output and energy (BLS, BEA, EIA)', columns, rows[3], question=3,
              note=note)
    res.table('Official agency data — labour and income (BLS, BEA)', columns, rows[5], question=5, note=note)
    res.notes.append(f'T_p = {tm.previous_cutoff}, T_c = {tm.cutoff}. Data from `python main.py collect`; nothing is '
                     'downloaded by this section. Economy-wide data: no company-level attribution; timing only.')
    return res
