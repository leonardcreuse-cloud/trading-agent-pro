"""Weekly report section 'positioning' (Q1, Q8) - offline tests on an isolated database.

All COT, Cboe, FINRA and option values below are SYNTHETIC: they exist only to check point-in-time,
rule and evidence-level logic and never reach a report.
"""

from datetime import date, datetime, timedelta

import pandas as pd

from src import external_sources as ex
from src.common import end_of_us_trading_day_utc
from src.database import Database, freshness
from src.weekly.core import STRONG, UNCERTAIN, TimeModel
from src.weekly.sections import positioning

ALL_SESSIONS = [d.date().isoformat() for d in pd.bdate_range(end='2026-10-09', periods=400)]
CUTOFF = '2026-10-10T12:00:00+00:00'      # s_0 = 2026-10-09, T_c = 2026-10-10T05:00Z, T_p = 2026-10-03T05:00Z
GENERATED = '2026-10-11T21:00:00+00:00'
CAUSAL = ('because', 'due to', 'drove', 'driven by', 'caused')


class Ctx:
    def __init__(self, db, universe=('AAA', 'BBB')):
        self.tm = TimeModel(ALL_SESSIONS, CUTOFF, GENERATED)
        self.db, self.universe, self.weekly = db, list(universe), {'thresholds_version': 'test-v1'}

    def freshness(self, as_of, cadence, at=None):
        return freshness(as_of, cadence, now=datetime.fromisoformat(at or self.tm.cutoff))


def store(db, source, rows, retrieved_at):
    """Synthetic rows from one fake fetch retrieved at `retrieved_at` (published_at as given in the rows)."""
    fetch = dict(db.record_fetch(source, f'test:{source}:{retrieved_at}', status='OK'), retrieved_at=retrieved_at)
    return db.upsert_observations(fetch, rows)


def cot_history(db):
    tuesdays = [date(2026, 10, 13) - timedelta(weeks=k) for k in range(41)][::-1]      # ends with a bait 10-13
    rows = []
    for i, d in enumerate(tuesdays):
        lev = -400_000 + (1_000 if i % 2 else -1_000)        # alternating +-2,000 changes: sd ~ 2,000
        if d == date(2026, 10, 6):
            lev = -380_000                                   # +21,000 vs 09-29: large
        if d == date(2026, 10, 13):
            lev = 0                                          # released 10-16: after the cutoff (bait)
        asset = 900_000 + (1_000 if i % 2 else -1_000)
        if d == date(2026, 10, 6):
            asset = rows[-1]['value']                        # unchanged vs 09-29: not large
        base = {'entity': 'COT:13874A', 'as_of_date': d.isoformat(), 'published_at': ex.cot_release(d),
                'published_at_basis': ex.COT_BASIS, 'unit': 'contracts'}
        rows += [{**base, 'metric': 'open_interest', 'value': 2_000_000},
                 {**base, 'metric': 'leveraged_funds_net', 'value': lev},
                 {**base, 'metric': 'asset_managers_net', 'value': asset}]
    store(db, 'CFTC', rows, '2026-10-20T00:00:00+00:00')


def cboe_history(db):
    rows = []
    for i, s in enumerate(ALL_SESSIONS[-60:]):
        week = ALL_SESSIONS.index(s) // 5
        value = 0.9 if s >= '2026-10-05' else 0.8 + (0.01 if week % 2 else 0.0)
        rows.append({'entity': 'CBOE', 'metric': 'put_call_total', 'as_of_date': s, 'value': value, 'unit': 'ratio',
                     'published_at': end_of_us_trading_day_utc(s), 'published_at_basis': ex.CBOE_BASIS})
    store(db, 'Cboe', rows, '2026-10-11T20:00:00+00:00')


def finra_history(db):
    rows, d = [], date(2024, 1, 15)
    settlements = []
    while d <= date(2026, 10, 15):
        settlements.append(d)
        d = d.replace(day=28) + timedelta(days=4) if d.day == 15 else (d + timedelta(days=15)).replace(day=15)
    settlements = [s if s.day == 15 else (s.replace(day=1) - timedelta(days=1)) for s in settlements]
    for i, s in enumerate(sorted(set(settlements))):
        shares = 10_000_000 + (50_000 if i % 2 else -50_000)
        if s == date(2026, 9, 30):
            shares = 12_000_000                              # +2,050,000 vs 09-15: large
        base = {'entity': 'AAA', 'as_of_date': s.isoformat(), 'published_at': ex.finra_dissemination(s),
                'published_at_basis': ex.FINRA_BASIS}
        rows += [{**base, 'metric': 'short_interest_shares', 'value': shares, 'unit': 'shares'},
                 {**base, 'metric': 'short_interest_days_to_cover', 'value': 2.5, 'unit': 'days'}]
    store(db, 'FINRA', rows, '2026-10-20T00:00:00+00:00')


def options_history(db):
    def snap(day, iv):
        return [{'entity': 'AAA', 'metric': 'opt_atm_iv_30d', 'as_of_date': day, 'value': iv, 'published_at': None,
                 'published_at_basis': 'snapshot: retrieval time'},
                {'entity': 'AAA', 'metric': 'opt_put_call_oi_60d', 'as_of_date': day, 'value': 0.8,
                 'published_at': None, 'published_at_basis': 'snapshot: retrieval time'}]
    store(db, 'yfinance', snap('2026-10-02', 0.50), '2026-10-02T22:00:00+00:00')
    store(db, 'yfinance', snap('2026-10-09', 0.55), '2026-10-09T22:00:00+00:00')
    store(db, 'yfinance', snap('2026-10-09', 0.99), '2026-10-11T20:00:00+00:00')         # after the cutoff (bait)


def build(**kw):
    db = Database()
    for fill in (cot_history, cboe_history, finra_history, options_history):
        fill(db)
    return positioning.build(Ctx(db, **kw)).as_dict()


def statements(out):
    return [c['statement'] for c in out['conclusions']]


def test_cot_report_known_at_each_cutoff_and_the_rule():
    out = build()
    assert out['name'] == 'positioning' and out['questions'] == [1, 8]
    c = next(c for c in out['conclusions'] if c['statement'].startswith('CFTC COT, E-mini S&P 500'))
    assert 'report of 2026-10-06 vs 2026-09-29' in c['statement'] and c['level'] == STRONG
    assert 'leveraged funds -380,000 (change +21,000, +1.05% of open interest)' in c['statement']
    t = next(t for t in out['tables'] if t['title'].startswith('CFTC Commitments of Traders'))
    rows = {r[1]: dict(zip(t['columns'], r)) for r in t['rows'] if r[0] == 'E-mini S&P 500 (CME)'}
    assert rows['leveraged funds']['report (known at T_c)'] == '2026-10-06'      # the 10-13 report is not public
    assert rows['leveraged funds']['large (|change| > 1 sd)'] == 'yes'
    assert rows['asset managers']['large (|change| > 1 sd)'] == 'no'
    summary = next(c for c in out['conclusions'] if c['statement'].startswith('Large week-to-week changes'))
    assert 'E-mini S&P 500 (CME) leveraged funds (+21,000)' in summary['statement']
    assert summary['kind'] == 'interpretation' and 'HEURISTIC_THRESHOLD' in summary['reason_codes']
    items = {u['item'] for u in out['unavailable']}
    assert 'CFTC COT, Gold (COMEX)' in items                                      # no report stored


def test_cboe_weekly_means_known_at_each_cutoff():
    out = build()
    c = next(c for c in out['conclusions'] if c['statement'].startswith('Cboe put/call ratios'))
    assert 'total 0.81 -> 0.9' in c['statement'] or 'total 0.8 -> 0.9' in c['statement']
    assert c['level'] == STRONG and c['kind'] == 'official_fact'
    t = next(t for t in out['tables'] if t['title'].startswith('Cboe put/call ratios'))
    total = dict(zip(t['columns'], next(r for r in t['rows'] if r[0] == 'total')))
    assert total['sessions (T_c)'] == 5 and total['week mean (known at T_c)'] == 0.9
    assert total['large (|change| > 1 sd)'] == 'not assessed'                     # 11 complete weeks < 26


def test_finra_short_interest_and_option_snapshots():
    out = build()
    si = next(c for c in out['conclusions'] if c['statement'].startswith('AAA: FINRA short interest'))
    assert 'at settlement 2026-09-30 vs 9,950,000 at 2026-09-15: change +2,050,000 (+20.6%)' in si['statement']
    assert 'larger than 1 sd' in si['statement'] and si['level'] == STRONG
    assert '(2.5 days to cover)' in si['statement']
    summary = next(c for c in out['conclusions'] if c['statement'].startswith('Short interest changed'))
    assert summary['kind'] == 'interpretation' and 'AAA' in summary['statement']
    iv = next(c for c in out['conclusions'] if c['statement'].startswith('AAA: ATM implied volatility'))
    assert '55.0%' in iv['statement'] and '99.0%' not in iv['statement']           # retrieved after T_c: unused
    assert '50.0% in the snapshot known at T_p (2026-10-02), change +5.0 points' in iv['statement']
    assert iv['level'] == UNCERTAIN and 'SINGLE_RANK2_SOURCE' in iv['reason_codes']
    reasons = {(u['scope'], u['item']): u['reason'] for u in out['unavailable']}
    assert 'python main.py collect' in reasons[('BBB', 'short interest (FINRA)')]
    assert 'retrieved at or before the cutoff' in reasons[('BBB', 'option implied volatility (yfinance snapshot)')]
    for s in statements(out):
        assert not any(w in s.lower() for w in CAUSAL), s


def test_no_new_settlement_between_cutoffs():
    db = Database()
    finra_history(db)
    ctx = Ctx(db, universe=('AAA',))
    ctx.tm = TimeModel(ALL_SESSIONS, '2026-10-08T12:00:00+00:00', GENERATED)   # T_c 10-08, T_p 10-01
    out = positioning.build(ctx).as_dict()
    si = next(c for c in out['conclusions'] if c['statement'].startswith('AAA: no new FINRA'))
    assert 'latest 2026-09-15' in si['statement']
