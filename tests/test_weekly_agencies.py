"""Weekly report section 'agencies' (Q3, Q5) - offline tests on an isolated database.

All values below are SYNTHETIC (logic tests only, never in a report).
"""

from datetime import datetime

import pandas as pd

from src.database import Database, freshness
from src.weekly.core import STRONG, TimeModel
from src.weekly.sections import agencies

ALL_SESSIONS = [d.date().isoformat() for d in pd.bdate_range(end='2026-10-16', periods=400)]
CUTOFF = '2026-10-17T12:00:00+00:00'      # s_0 = 2026-10-16, T_c = 2026-10-17T05:00Z, T_p = 2026-10-10T05:00Z


class Ctx:
    def __init__(self, db):
        self.tm = TimeModel(ALL_SESSIONS, CUTOFF, '2026-10-18T10:00:00+00:00')
        self.db, self.universe, self.weekly = db, [], {}

    def freshness(self, as_of, cadence, at=None):
        return freshness(as_of, cadence, now=datetime.fromisoformat(at or self.tm.cutoff))


def put(db, source, entity, period, value, retrieved, published=None, unit='index'):
    fetch = dict(db.record_fetch(source, f'test:{entity}:{retrieved}', status='OK'), retrieved_at=retrieved)
    db.upsert_observations(fetch, [{'entity': entity, 'metric': 'value', 'as_of_date': period, 'value': value,
                                    'unit': unit, 'published_at': published,
                                    'published_at_basis': 'test basis' if published else 'retrieval time'}])


def build(db):
    return agencies.build(Ctx(db)).as_dict()


def statement(out, entity):
    return next((c for c in out['conclusions'] if f'({entity})' in c['statement']), None)


def test_new_periods_only_for_series_collected_before_the_previous_cutoff():
    db = Database()
    # BLS CPI: collected daily since September; the September value is first retrieved inside the window
    put(db, 'BLS', 'BLS:CUSR0000SA0', '2026-07-01', 332.8, '2026-09-20T12:00:00+00:00')
    put(db, 'BLS', 'BLS:CUSR0000SA0', '2026-08-01', 334.1, '2026-09-20T12:00:00+00:00')
    put(db, 'BLS', 'BLS:CUSR0000SA0', '2026-09-01', 335.0, '2026-10-14T13:00:00+00:00')
    # BLS unemployment rate: first collected inside the window (older periods included): no "new" statement
    put(db, 'BLS', 'BLS:LNS14000000', '2026-08-01', 4.1, '2026-10-12T12:00:00+00:00', unit='%')
    put(db, 'BLS', 'BLS:LNS14000000', '2026-09-01', 4.2, '2026-10-12T12:00:00+00:00', unit='%')
    # BEA GDP: Q1 known at T_p (table of 2026-09-01), Q2 published in the window (table of 2026-10-14)
    put(db, 'BEA', 'BEA:A191RL', '2026-01-01', 2.5, '2026-09-05T12:00:00+00:00', '2026-09-02T05:00:00+00:00', '%')
    put(db, 'BEA', 'BEA:A191RL', '2026-04-01', 2.2, '2026-10-15T12:00:00+00:00', '2026-10-15T05:00:00+00:00', '%')
    # a value retrieved after the cutoff is never used
    put(db, 'BLS', 'BLS:CUSR0000SA0', '2026-10-01', 999.0, '2026-10-17T13:00:00+00:00')
    out = build(db)

    cpi = statement(out, 'BLS:CUSR0000SA0')
    assert cpi['level'] == STRONG and '335 index for the period starting 2026-09-01' in cpi['statement']
    assert 'first retrieved by the daily collection in the window' in cpi['statement']
    assert 'release date is not established' in cpi['statement'] and '999' not in cpi['statement']
    assert 'previous period (2026-08-01) 334.1' in cpi['statement']
    assert statement(out, 'BLS:LNS14000000') is None
    gdp = statement(out, 'BEA:A191RL')
    assert 'published in the window (BEA table date)' in gdp['statement'] and gdp['question'] == 3
    t5 = next(t for t in out['tables'] if 'labour and income' in t['title'])
    row = next(r for r in t5['rows'] if r[0] == 'BLS:LNS14000000')
    assert row[-1] == 'first collected in the window (release date not established)'
    reasons = {(u['question'], u['item']): u['reason'] for u in out['unavailable']}
    eia = reasons[(3, 'EIA series read directly from the agency')]
    assert 'count from their retrieval' in eia and 'python main.py collect' in eia
