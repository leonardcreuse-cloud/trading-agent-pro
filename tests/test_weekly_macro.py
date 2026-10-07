"""Weekly report section 'macro' (Q3, Q4, Q5) - offline tests on a fake context.

Every FRED observation and vintage below is SYNTHETIC: it exists only to check the vintage, revision-noise,
point-in-time and evidence-level logic and never reaches a report.
"""

import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.common import end_of_us_trading_day_utc as eod
from src.common import to_utc_iso
from src.database import Database, freshness
from src.weekly.context import Context
from src.weekly.core import STRONG, UNAVAILABLE, UNCERTAIN, LookAheadError, TimeModel
from src.weekly.sections import macro

ALL_SESSIONS = [d.date().isoformat() for d in pd.bdate_range(end='2026-10-09', periods=900)]
CUTOFF = '2026-10-07T12:00:00+00:00'          # s_0 = 2026-10-06, T_c = 2026-10-07T05:00Z, T_p = 2026-09-30T05:00Z
T_C = '2026-10-07T05:00:00+00:00'
T_P = '2026-09-30T05:00:00+00:00'
RETRIEVED = '2026-10-07T13:00:00+00:00'       # fake fetches are made after the cutoff
WEEKLY = {'thresholds_version': 'test-v1', 'thresholds': {'abs_excess_return_z': 2.0}}
CAUSAL = ('because', 'due to', 'drove', 'driven by', 'on the back of', 'caused', 'triggered', 'sparked',
          'fueled', 'thanks to', 'in response to', 'as a result', 'sent shares')


# ---------------------------------------------------------------- synthetic FRED store

class Store:
    def __init__(self):
        self.rows = defaultdict(list)          # sid -> [(obs, value, published_at)] in storage order

    def add(self, sid, obs, value, vintage):
        self.rows[sid].append((obs, float(value), eod(vintage)))


def add_daily(store, sid, start, end, f, lag=1, weekdays=True):
    d = date.fromisoformat(start)
    while d <= date.fromisoformat(end):
        if not weekdays or d.weekday() < 5:
            store.add(sid, d.isoformat(), f(d), (d + timedelta(days=lag)).isoformat())
        d += timedelta(days=1)


def months(start, end):
    y, m = map(int, start[:7].split('-'))
    out = []
    while f'{y:04d}-{m:02d}' <= end[:7]:
        out.append(f'{y:04d}-{m:02d}-01')
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def next_month(obs, day):
    y, m = int(obs[:4]), int(obs[5:7])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return f'{y:04d}-{m:02d}-{day:02d}'


class FakeCtx:
    """Same accessor contract as weekly.context.Context, over the synthetic store."""

    def __init__(self, store, status=None, retrieved=RETRIEVED, weekly=None, buggy=False):
        self.tm = TimeModel(ALL_SESSIONS, CUTOFF, CUTOFF)
        self.store, self.status, self.retrieved = store, status or {}, retrieved
        self.weekly = weekly if weekly is not None else WEEKLY
        self.buggy = buggy                     # accessor that ignores known_at (to test the look-ahead guard)
        self.calls = []

    def fred(self, sid):
        self.calls.append(sid)
        if sid in self.status:
            return {'status': UNAVAILABLE, 'fetch': None, 'reason': self.status[sid]}
        if sid not in self.store.rows:
            return {'status': UNAVAILABLE, 'fetch': {'fetch_id': 3}, 'reason': 'FRED HTTP 400: The series does not exist.'}
        return {'status': 'OK', 'fetch': {'fetch_id': 11, 'retrieved_at': self.retrieved}, 'reason': None}

    def _known(self, sid, instant):
        k = '9999' if self.buggy else to_utc_iso(instant)
        best = {}
        for obs, v, pub in sorted(self.store.rows[sid], key=lambda r: r[2]):
            if pub <= k:
                best[obs] = (v, pub)
        return best

    def value_at(self, sid, instant):
        b = self._known(sid, instant)
        if not b:
            return None
        obs = max(b)
        return obs, b[obs][0], b[obs][1]

    def series_at(self, sid, instant, start=None):
        b = self._known(sid, instant)
        return [(o, b[o][0]) for o in sorted(b) if start is None or o >= start]

    def first_release(self, sid):
        out = {}
        for obs, _, pub in self.store.rows[sid]:
            out[obs] = min(out.get(obs, pub), pub)
        return out

    def vintages(self, sid, known_at):
        k = to_utc_iso(known_at)
        return sorted([r for r in self.store.rows[sid] if r[2] <= k], key=lambda r: (r[0], r[2]))

    def freshness(self, as_of, cadence):
        return freshness(as_of, cadence, now=datetime.fromisoformat(self.tm.cutoff))


# ---------------------------------------------------------------- datasets

def dgs10(store, sid='DGS10'):
    base = date(2026, 6, 1)
    add_daily(store, sid, '2026-06-01', '2026-10-07', lambda d: 4.0 + 0.01 * (d - base).days)


def nfci(store):
    fridays = [date(2026, 1, 2) + timedelta(days=7 * k) for k in range(40)]
    for k, f in enumerate(fridays):
        if f > date(2026, 10, 2):
            break
        store.add('NFCI', f.isoformat(), -0.5 + 0.002 * k, (f + timedelta(days=5)).isoformat())
    store.add('NFCI', '2026-06-05', -0.5 + 0.002 * 22 + 0.05, '2026-06-24')     # one revision of +0.05


def cpi(store):
    """CPIAUCSL: index 300 x 1.002^k, month m first published on the 12th of m+1, except Sep 2026 first
    published 2026-10-01 (inside the window) together with revisions of Aug 2026 (+0.3) and Sep 2025 (-0.2);
    Oct 2026 is published 2026-11-12 (after the cutoff)."""
    ms = months('2024-08', '2026-10')
    level = {m: 300 * 1.002 ** k for k, m in enumerate(ms)}
    for m in ms:
        store.add('CPIAUCSL', m, level[m], '2026-10-01' if m == '2026-09-01' else next_month(m, 12))
    store.add('CPIAUCSL', '2026-08-01', level['2026-08-01'] + 0.3, '2026-10-01')
    store.add('CPIAUCSL', '2025-09-01', level['2025-09-01'] - 0.2, '2026-10-01')
    return level


PAYEMS_FIRST = [('2025-10', 158000, '2025-11-07'), ('2025-11', 158100, '2025-12-05'), ('2025-12', 158200, '2026-01-09'),
                ('2026-01', 158300, '2026-02-06'), ('2026-02', 158400, '2026-03-06'), ('2026-03', 158500, '2026-04-03'),
                ('2026-04', 158600, '2026-05-08'), ('2026-05', 158700, '2026-06-05'), ('2026-06', 158800, '2026-07-02'),
                ('2026-07', 158900, '2026-08-07'), ('2026-08', 159000, '2026-09-04')]


def payems(store, sep=159080):
    for m, v, vint in PAYEMS_FIRST:
        store.add('PAYEMS', m + '-01', v, vint)
    store.add('PAYEMS', '2026-03-01', 158540, '2026-05-08')       # revision +40 (change revision 40)
    store.add('PAYEMS', '2026-08-01', 159050, '2026-10-02')       # revision +50 (change revision 50)
    store.add('PAYEMS', '2026-09-01', sep, '2026-10-02')          # first print inside the window


def unrate(store, sep=4.5):
    for m in months('2025-10', '2026-08'):
        store.add('UNRATE', m, 4.2, next_month(m, 5))
    store.add('UNRATE', '2026-02-01', 4.3, '2026-04-05')           # revision: change revision 0.1
    store.add('UNRATE', '2026-09-01', sep, '2026-10-02')


def icsa(store, last=240000):
    sat = [date(2026, 5, 2) + timedelta(days=7 * k) for k in range(22)]
    for s in sat:
        if s > date(2026, 9, 26):
            break
        v = last if s == date(2026, 9, 26) else 200000
        store.add('ICSA', s.isoformat(), v, (s + timedelta(days=5)).isoformat())
    store.add('ICSA', '2026-08-01', 202000, '2026-08-13')           # revision: change revision 2000


def target(store, change=True):
    def up(d):
        return 4.00 if change and d >= date(2026, 10, 1) else 4.25
    add_daily(store, 'DFEDTARU', '2026-06-01', '2026-10-06', up, weekdays=False)
    add_daily(store, 'DFEDTARL', '2026-06-01', '2026-10-06', lambda d: up(d) - 0.25, weekdays=False)


def epu(store):
    base = date(2026, 6, 1)
    d = base
    while d <= date(2026, 10, 6):
        first = 100 + ((d - base).days % 7) * 10
        store.add('USEPUINDXD', d.isoformat(), first, (d + timedelta(days=1)).isoformat())
        store.add('USEPUINDXD', d.isoformat(), first + 30, (d + timedelta(days=2)).isoformat())
        d += timedelta(days=1)


def find(res, prefix, question=None):
    out = [c for c in res.conclusions if c['statement'].startswith(prefix)
           and (question is None or c['question'] == question)]
    assert out, f'no conclusion starting with {prefix!r}'
    return out[0]


def table(res, title_start):
    for t in res.tables:
        if t['title'].startswith(title_start):
            return t
    raise AssertionError(f'no table {title_start!r}')


def row(t, sid):
    for r in t['rows']:
        if r[0] == sid or (len(r) > 1 and r[1] == sid):
            return dict(zip(t['columns'], r))
    raise AssertionError(f'no row {sid}')


# ---------------------------------------------------------------- tests

def test_time_model_used_by_the_fake():
    tm = FakeCtx(Store()).tm
    assert (tm.s0, tm.cutoff, tm.previous_cutoff) == ('2026-10-06', T_C, T_P)
    assert tm.sessions[-6] == '2026-09-29' and tm.sessions[-11] == '2026-09-22'


def test_daily_values_as_known_and_weekly_means():
    store = Store()
    dgs10(store)
    ctx = FakeCtx(store)
    res = macro.build(ctx, series=['DGS10'])
    r = row(table(res, 'Macro indicators'), 'DGS10')
    # obs dated d is published with vintage d+1: 2026-10-06 (vintage 10-07) is NOT known at T_c
    assert r['obs (T_c)'] == '2026-10-05' and r['obs (T_p)'] == '2026-09-28'
    assert r['value as known at T_c'] == pytest.approx(5.26) and r['value as known at T_p'] == pytest.approx(5.19)
    assert r['delta (T_c - T_p)'] == pytest.approx(0.07)
    assert r['revision of a previously published value'] == 'no' and r['largest revision in stored vintages'] == 0
    assert r['new release in window (first publication)'].startswith('yes: 5 obs')
    c = find(res, 'DGS10 (')
    assert c['level'] == STRONG and c['kind'] == 'official_fact' and c['reason_codes'] == []
    assert 'difference +0.07 pp' in c['statement'] and 'beyond revision noise' in c['statement']
    assert all(e['source'] == 'FRED' and e['rank'] == 1 and e['published_at'] <= T_C for e in c['evidence'])
    assert r['level'] == STRONG
    vals = [r for r in table(res, 'Daily macro series')['rows'] if r[0] == 'DGS10'][0]
    # week (09-29, 10-06] known at T_c: 09-30, 10-01, 10-02, 10-05; previous week known at T_p: 09-23..09-28
    assert vals[1] == pytest.approx((5.21 + 5.22 + 5.23 + 5.26) / 4) and vals[2] == 4
    assert vals[3] == pytest.approx((5.14 + 5.15 + 5.16 + 5.19) / 4) and vals[4] == 4
    assert vals[5] == pytest.approx((5.14 + 5.15 + 5.16 + 5.19 + 5.20) / 5) and vals[6] == 5
    assert vals[9] == 'yes'


def test_revised_weekly_series_within_revision_noise_is_uncertain():
    store = Store()
    nfci(store)
    res = macro.build(FakeCtx(store), series=['NFCI'])
    r = row(table(res, 'Macro indicators'), 'NFCI')
    assert r['obs (T_c)'] == '2026-09-25' and r['obs (T_p)'] == '2026-09-18'
    assert r['delta (T_c - T_p)'] == pytest.approx(0.002)
    assert r['largest revision in stored vintages'] == pytest.approx(0.05)
    assert r['beyond revision noise'] == 'no'
    c = find(res, 'NFCI (')
    assert c['level'] == UNCERTAIN and c['reason_codes'] == ['FIRST_PRINT_WITHIN_REVISION_NOISE']
    assert 'within revision noise' in c['statement']


def test_yoy_is_computed_within_one_vintage_and_excludes_post_cutoff_releases():
    store = Store()
    level = cpi(store)
    res = macro.build(FakeCtx(store), series=['CPIAUCSL'])
    r = row(table(res, 'Macro indicators'), 'CPIAUCSL')
    yoy_c = ((level['2026-09-01']) / (level['2025-09-01'] - 0.2) - 1) * 100     # revised base, T_c vintage
    yoy_p = (level['2026-08-01'] / level['2025-08-01'] - 1) * 100             # unrevised August, T_p vintage
    assert r['obs (T_c)'] == '2026-09' and r['obs (T_p)'] == '2026-08'     # Oct 2026 (published 11-12) excluded
    assert r['value as known at T_c'] == pytest.approx(round(yoy_c, 4))
    assert r['value as known at T_p'] == pytest.approx(round(yoy_p, 4))
    assert r['new release in window (first publication)'].startswith('yes: 1 obs (latest 2026-09')
    assert r['revision of a previously published value'].startswith('yes: 2 obs')
    # largest YoY revision: Aug 2026 (+0.3 on the index) vs Sep 2025 (-0.2 on the index)
    rev_aug = 0.3 / level['2025-08-01'] * 100
    rev_sep25 = 0.2 / level['2024-09-01'] * 100
    noise = max(rev_aug, rev_sep25)
    assert r['largest revision in stored vintages'] == pytest.approx(round(noise, 4))
    c = find(res, 'CPIAUCSL (')
    beyond = abs(yoy_c - yoy_p) > noise
    assert c['level'] == (STRONG if beyond else UNCERTAIN)
    assert c['reason_codes'] == ([] if beyond else ['FIRST_PRINT_WITHIN_REVISION_NOISE'])
    assert 'within one vintage' in c['statement']
    assert all(e['published_at'] <= T_C for e in c['evidence'])


def test_release_first_print_change_revisions_and_noise():
    store = Store()
    payems(store)
    res = macro.build(FakeCtx(store), series=['PAYEMS'])
    r = row(table(res, 'Socio-economic indicators'), 'PAYEMS')
    assert r['new release in window'] == 'yes' and r['period'] == '2026-09'
    assert r['first print'] == 159080 and r['first published'] == '2026-10-02 (FRED vintage)'
    assert r['prior period (T_c vintage)'] == 159050                  # revised August, T_c vintage
    assert r['change vs prior period (T_c vintage)'] == 30
    assert r['largest revision of that change in stored vintages'] == 50     # August change 100 -> 150
    assert r['beyond revision noise'] == 'no'
    assert r['revisions vs T_p vintage'].startswith('yes: 1 obs')
    c = find(res, 'PAYEMS (')
    assert c['level'] == UNCERTAIN and c['reason_codes'] == ['FIRST_PRINT_WITHIN_REVISION_NOISE']
    assert c['evidence'][0]['published_at'] == eod('2026-10-02')
    rev = find(res, 'PAYEMS: 1 previously published')
    assert rev['level'] == STRONG and '159,000 thousand -> 159,050 thousand' in rev['statement']
    assert r['level'] == UNCERTAIN


def test_release_beyond_noise_is_strongly_supported():
    store = Store()
    payems(store, sep=159300)
    res = macro.build(FakeCtx(store), series=['PAYEMS'])
    c = find(res, 'PAYEMS (')
    assert c['level'] == STRONG and c['reason_codes'] == [] and '+250 thousand' in c['statement']


def test_no_new_release_statement_and_stale_series():
    store = Store()
    for m in months('2025-06', '2026-07'):
        store.add('GEPUCURRENT', m, 200 + int(m[5:7]), next_month(m, 10))
    for m in months('2025-06', '2026-08'):
        store.add('UMCSENT', m, 50 + int(m[5:7]) / 10, next_month(m, 25))
    res = macro.build(FakeCtx(store), series=['GEPUCURRENT', 'UMCSENT'])
    g = find(res, 'GEPUCURRENT (', question=4)
    assert 'no new observation first published in the window' in g['statement']
    assert g['level'] == UNCERTAIN and 'STALE_AT_CUTOFF' in g['reason_codes']      # July obs is 98 days old
    u = find(res, 'UMCSENT (')
    assert u['statement'].startswith('UMCSENT (University of Michigan consumer sentiment): no new release in the window')
    assert 'delay of about one month' in u['statement']
    assert u['level'] == UNCERTAIN and u['reason_codes'] == ['TIMESTAMP_AMBIGUOUS']
    assert any(x['item'].startswith('current University of Michigan') for x in res.unavailable)


def test_freshness_is_that_of_the_series_at_the_cutoff():
    """PCE-like lag: at T_p the latest month (July) is 91 days old, at T_c August is 67 days old: the series is
    FRESH at T_c, so the comparison is not marked stale; a series stale at T_c is (GEPUCURRENT test)."""
    store = Store()
    for k, m in enumerate(months('2025-01', '2026-08')):
        store.add('PCEPI', m, 125 * 1.002 ** k, '2026-09-30' if m == '2026-08-01' else next_month(m, 28))
    res = macro.build(FakeCtx(store), series=['PCEPI'])
    c = find(res, 'PCEPI (')
    assert 'STALE_AT_CUTOFF' not in c['reason_codes'] and len(c['evidence']) == 2
    assert all(e['fresh_at_cutoff'] is True for e in c['evidence'])
    r = row(table(res, 'Macro indicators'), 'PCEPI')
    assert r['obs (T_p)'] == '2026-07' and r['obs (T_c)'] == '2026-08'


def test_target_range_change_and_no_change():
    store = Store()
    target(store, change=True)
    res = macro.build(FakeCtx(store), series=list(macro.TARGET))
    c = find(res, 'The federal funds target range changed')
    assert c['level'] == STRONG and c['kind'] == 'official_fact'
    assert '4.00-4.25% for 2026-09-28 as known at T_p' in c['statement'] and '3.75-4.00% for 2026-10-05' in c['statement']
    assert 'DFEDTARU 4.25 -> 4.00 from obs 2026-10-01, first published 2026-10-02 (FRED vintage)' in c['statement']
    assert row(table(res, 'Macro indicators'), 'DFEDTARU')['level'] == STRONG

    store = Store()
    target(store, change=False)
    res = macro.build(FakeCtx(store), series=list(macro.TARGET))
    c = find(res, 'No change of the federal funds target range')
    assert c['level'] == STRONG
    assert not [x for x in res.conclusions if x['statement'].startswith('DFEDTAR')]


def test_epu_weekly_means_heavily_revised_are_uncertain_and_not_events():
    store = Store()
    epu(store)
    res = macro.build(FakeCtx(store), series=['USEPUINDXD'])
    c = find(res, 'USEPUINDXD (', question=4)
    assert c['level'] == UNCERTAIN and 'FIRST_PRINT_WITHIN_REVISION_NOISE' in c['reason_codes']
    assert 'not geopolitical events' in c['statement']
    r = table(res, 'Policy-uncertainty indices')['rows'][0]
    assert r[7] == 30                                   # largest revision of a daily value
    assert 'n 6' in r[3] and 'n 6' in r[4]              # 6 values dated in each week known at each cutoff
    items = {u['item'] for u in res.unavailable if u['question'] == 4}
    assert any(i.startswith('Caldara-Iacoviello') for i in items)
    assert any(i.startswith('GDELT') for i in items)
    assert any(i.startswith('official primary documents') for i in items)
    reasons = ' '.join(u['reason'] for u in res.unavailable if u['question'] == 4)
    assert 'matteoiacoviello.com' in reasons and 'gdeltproject.org' in reasons
    fomc = [u for u in res.unavailable if u['item'].startswith('FOMC meeting calendar')]
    assert fomc and 'federalreserve.gov' in fomc[0]['reason'] and 'release 326' in fomc[0]['reason']


def test_labour_block_interpretation_and_claims_four_week_average():
    store = Store()
    unrate(store)
    icsa(store)
    payems(store)                                       # payroll change within noise: not counted
    res = macro.build(FakeCtx(store), series=['UNRATE', 'ICSA', 'PAYEMS'])
    u = find(res, 'UNRATE (')
    assert u['level'] == STRONG and '+0.3 pp' in u['statement']
    i = find(res, 'ICSA (')
    assert i['level'] == STRONG and '+40,000 persons' in i['statement']
    block = find(res, 'Labour block:')
    assert block['kind'] == 'interpretation' and block['level'] == UNCERTAIN and 'INTERPRETIVE' in block['reason_codes']
    assert "'softer'" in block['statement'] and 'PAYEMS' not in block['statement']
    claims = table(res, 'Weekly unemployment claims')
    r = dict(zip(claims['columns'], claims['rows'][0]))
    assert r['4-week average, T_c vintage'] == 210000 and r['weeks (T_c vintage)'] == '2026-09-05..2026-09-26'
    assert r['4-week average, T_p vintage'] == 200000 and r['weeks (T_p vintage)'] == '2026-08-29..2026-09-19'


def test_single_indicator_gives_no_directional_claim():
    store = Store()
    unrate(store)
    res = macro.build(FakeCtx(store), series=['UNRATE'])
    assert not [c for c in res.conclusions if c['kind'] == 'interpretation']


def test_derived_real_earnings_is_an_estimate():
    store = Store()
    level = cpi(store)                                  # CPI known at T_c through Sep 2026
    for k, m in enumerate(months('2026-06', '2026-09')):
        store.add('CES0500000003', m, 37.0 + 0.1 * k, next_month(m, 5) if m != '2026-09-01' else '2026-10-02')
    res = macro.build(FakeCtx(store), series=['CES0500000003', 'CPIAUCSL'])
    c = find(res, 'Derived (not an official print)')
    assert c['level'] == UNCERTAIN and 'ESTIMATE' in c['reason_codes'] and c['kind'] == 'official_fact'
    assert 'for 2026-09' in c['statement'] and 'cannot be derived yet' not in c['statement']
    t = table(res, 'Derived: real average hourly earnings')
    assert t['rows'][0][0] == '2026-09'
    assert t['rows'][0][3] == pytest.approx(round(37.3 / level['2026-09-01'] * 100, 4))
    real_aug = 37.2 / (level['2026-08-01'] + 0.3) * 100          # August CPI as revised in the T_c vintage
    assert t['rows'][0][4] == pytest.approx(round((37.3 / level['2026-09-01'] * 100 / real_aug - 1) * 100, 3))

    # CPI of the latest earnings month not yet known at T_c: derived for the latest month with both
    store = Store()
    for k, m in enumerate(months('2025-01', '2026-08')):
        store.add('CPIAUCSL', m, 320 + k, next_month(m, 12))
    for k, m in enumerate(months('2026-06', '2026-09')):
        store.add('CES0500000003', m, 37.0 + 0.1 * k, next_month(m, 5) if m != '2026-09-01' else '2026-10-02')
    res = macro.build(FakeCtx(store), series=['CES0500000003', 'CPIAUCSL'])
    c = find(res, 'Derived (not an official print)')
    assert 'for 2026-08' in c['statement'] and 'real earnings for 2026-09 cannot be derived yet' in c['statement']


def test_missing_data_is_unavailable_with_reason_never_filled():
    store = Store()
    dgs10(store)
    ctx = FakeCtx(store, status={'DGS2': 'FRED HTTP 500: Internal Server Error'})
    res = macro.build(ctx, series=['DGS10', 'DGS2', 'BAA10Y'])
    items = {u['item']: u['reason'] for u in res.unavailable}
    assert 'FRED HTTP 500' in items['DGS2 (2-year Treasury constant-maturity yield)']
    assert 'does not exist' in [r for i, r in items.items() if i.startswith('BAA10Y')][0]
    assert not [c for c in res.conclusions if c['statement'].startswith(('DGS2', 'BAA10Y'))]
    r = row(table(res, 'Macro indicators'), 'DGS2')
    assert r['level'] == UNAVAILABLE and r['value as known at T_c'] is None and r['delta (T_c - T_p)'] is None
    # series not requested: full table kept, marked NOT EVALUATED, listed as DATA UNAVAILABLE with the reason
    r = row(table(res, 'Macro indicators'), 'VIXCLS')
    assert r['level'] == macro.NOT_EVALUATED
    assert any(u['item'].startswith('VIXCLS') and 'not requested' in u['reason'] for u in res.unavailable)
    assert len(table(res, 'Macro indicators')['rows']) == len([s for s in macro.SERIES.values() if s['q'] == 3])
    assert len(table(res, 'Socio-economic')['rows']) == len([s for s in macro.SERIES.values() if s['q'] == 5])


def test_no_observation_known_at_cutoff_is_unavailable():
    store = Store()
    store.add('HOUST', '2026-09-01', 1300, '2026-10-20')          # first published after the cutoff
    res = macro.build(FakeCtx(store), series=['HOUST'])
    assert [u for u in res.unavailable if u['item'].startswith('HOUST') and 'no observation known at the cutoff'
            in u['reason']]
    assert not [c for c in res.conclusions if c['statement'].startswith('HOUST')]


def test_fetch_before_cutoff_is_partial_coverage():
    store = Store()
    dgs10(store)
    res = macro.build(FakeCtx(store, retrieved='2026-10-06T12:00:00+00:00'), series=['DGS10'])
    c = find(res, 'DGS10 (')
    assert c['level'] == UNCERTAIN and 'PARTIAL_COVERAGE' in c['reason_codes']


def test_accessor_leaking_post_cutoff_data_raises_look_ahead():
    store = Store()
    dgs10(store)
    with pytest.raises(LookAheadError):
        macro.build(FakeCtx(store, buggy=True), series=['DGS10'])


def test_series_override_limits_requests_and_rejects_unknown_ids():
    store = Store()
    dgs10(store)
    ctx = FakeCtx(store)
    macro.build(ctx, series=['DGS10'])
    assert ctx.calls == ['DGS10']
    with pytest.raises(ValueError):
        macro.build(FakeCtx(store), series=['NOT_A_SERIES'])
    full = FakeCtx(store)
    macro.build(full)
    assert full.calls == list(macro.SERIES)


def test_optional_macro_threshold_adds_below_threshold():
    store = Store()
    dgs10(store)
    weekly = {'thresholds_version': 'test-v2', 'thresholds': {'macro_abs_change': {'DGS10': 0.10}}}
    res = macro.build(FakeCtx(store, weekly=weekly), series=['DGS10'])
    c = find(res, 'DGS10 (')
    assert c['level'] == UNCERTAIN and 'BELOW_THRESHOLD' in c['reason_codes']
    assert any('test-v2' in n for n in res.notes)


def test_full_build_contract_kinds_wording_and_thresholds_version():
    store = Store()
    dgs10(store)
    nfci(store)
    cpi(store)
    payems(store)
    unrate(store)
    icsa(store)
    target(store)
    epu(store)
    res = macro.build(FakeCtx(store))
    d = res.as_dict()
    assert d['name'] == 'macro' and d['questions'] == [3, 4, 5]
    assert {c['question'] for c in d['conclusions']} <= {3, 4, 5}
    assert all(c['kind'] in ('official_fact', 'interpretation') for c in d['conclusions'])
    assert all(e['source'] == 'FRED' and e['rank'] == 1 for c in d['conclusions'] for e in c['evidence'])
    assert all(e['published_at'] is None or e['published_at'] <= T_C for c in d['conclusions'] for e in c['evidence'])
    assert all(u['level'] == UNAVAILABLE and u['reason'] for u in d['unavailable'])
    text = ' '.join([c['statement'] for c in d['conclusions']] + d['notes']
                    + [t['note'] or '' for t in d['tables']]).lower()
    for word in CAUSAL:
        assert word not in text, word
    assert any('test-v1' in n for n in d['notes'])
    assert {t['question'] for t in d['tables']} == {3, 4, 5}


def test_versions_fallback_reads_the_database_without_look_ahead():
    db = Database()
    fetch = db.record_fetch('FRED', 'https://api.stlouisfed.org/fred/series/observations',
                            requested_at=RETRIEVED, status='OK')
    fetch = dict(fetch, retrieved_at=RETRIEVED)
    store = Store()
    dgs10(store)
    rows = [{'entity': 'DGS10', 'metric': 'value', 'as_of_date': o, 'value': v, 'published_at': p,
             'published_at_basis': 'test'} for o, v, p in store.rows['DGS10']]
    db.upsert_observations(fetch, rows)

    class DBCtx:
        value_at = Context.value_at
        series_at = Context.series_at
        first_release = Context.first_release
        freshness = Context.freshness

        def __init__(self):
            self.db, self.tm, self.weekly = db, TimeModel(ALL_SESSIONS, CUTOFF, CUTOFF), WEEKLY

        def fred(self, sid):
            return {'status': 'OK', 'fetch': {'fetch_id': fetch['fetch_id'], 'retrieved_at': RETRIEVED}}

    ctx = DBCtx()
    versions = macro._versions(ctx, 'DGS10')
    expected = sorted((o, v, p) for o, v, p in store.rows['DGS10'] if p <= T_C)
    assert versions == expected
    assert max(p for _, _, p in versions) <= T_C and len(versions) < len(store.rows['DGS10'])
    res = macro.build(ctx, series=['DGS10'])
    c = find(res, 'DGS10 (')
    assert c['level'] == STRONG and '5.26% for 2026-10-05' in c['statement']
    assert c['evidence'][-1]['fetch_id'] == fetch['fetch_id']


def test_section_never_reads_the_wall_clock():
    source = Path(macro.__file__).read_text(encoding='utf-8')
    for pattern in (r'datetime\.now', r'date\.today', r'utc_now_iso', r'time\.time'):
        assert not re.search(pattern, source), pattern
