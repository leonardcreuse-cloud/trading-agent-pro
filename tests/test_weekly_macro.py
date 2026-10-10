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
from src.common import load_config, to_utc_iso
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

    def __init__(self, store, status=None, retrieved=RETRIEVED, weekly=None, buggy=False, cutoff=CUTOFF):
        self.tm = TimeModel(ALL_SESSIONS, cutoff, cutoff)
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

    def freshness(self, as_of, cadence, at=None):
        return freshness(as_of, cadence, now=datetime.fromisoformat(at or self.tm.cutoff))


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


def target(store, change=True, effective='2026-10-01', end='2026-10-06', lag=0):
    """DFEDTARU / DFEDTARL for every calendar day. FRED dates the range by its EFFECTIVE date (the day after
    the FOMC announcement) and vintages observation d on day d (lag 0), published at end of day d."""
    def up(d):
        return 4.00 if change and d >= date.fromisoformat(effective) else 4.25
    add_daily(store, 'DFEDTARU', '2026-06-01', end, up, lag=lag, weekdays=False)
    add_daily(store, 'DFEDTARL', '2026-06-01', end, lambda d: up(d) - 0.25, lag=lag, weekdays=False)


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
    # the T_p item (2026-09-28) is a historical vintage: fresh at T_p (2 days), its own flag, said in its basis
    item_p = c['evidence'][0]
    assert item_p['as_of'] == '2026-09-28' and 'as known at T_p' in item_p['fact']
    assert item_p['fresh_at_cutoff'] is True and 'freshness evaluated at T_p' in item_p['published_at_basis']
    assert freshness('2026-09-28', 'daily', now=datetime.fromisoformat(T_P))['status'] == 'FRESH'
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
    assert 'not established as the date the University of Michigan first published' in u['statement']
    assert 'is not the current University of Michigan print' not in u['statement']     # not established
    assert u['level'] == UNCERTAIN and u['reason_codes'] == ['TIMESTAMP_AMBIGUOUS']
    assert 'University of Michigan Surveys of Consumers' in u['what_would_resolve_it']
    um = [x for x in res.unavailable if x['item'].startswith('current University of Michigan')]
    assert um and 'preliminary' in um[0]['item'] and 'final' not in um[0]['item']


def test_freshness_of_each_item_is_evaluated_at_its_own_cutoff():
    """PCE-like lag: at T_p the latest month (July) was already 91 days old (> 80), at T_c August is 67 days old.
    The T_c item is FRESH at T_c; the T_p item is evaluated at T_p (its own cutoff, historical vintage) and is
    STALE there, so the comparison is UNCERTAIN (STALE_AT_CUTOFF): a flag is never copied from another item."""
    store = Store()
    for k, m in enumerate(months('2025-01', '2026-08')):
        store.add('PCEPI', m, 125 * 1.002 ** k, '2026-09-30' if m == '2026-08-01' else next_month(m, 28))
    res = macro.build(FakeCtx(store), series=['PCEPI'])
    c = find(res, 'PCEPI (')
    assert len(c['evidence']) == 2
    item_p, item_c = c['evidence']
    assert item_c['as_of'] == '2026-08-01' and item_c['fresh_at_cutoff'] is True
    assert item_p['as_of'] == '2026-07-01' and item_p['fresh_at_cutoff'] is False
    assert freshness('2026-07-01', 'monthly', now=datetime.fromisoformat(T_P))['status'] == 'STALE'
    assert 'freshness evaluated at T_p' in item_p['published_at_basis']
    assert c['level'] == UNCERTAIN and 'STALE_AT_CUTOFF' in c['reason_codes']
    r = row(table(res, 'Macro indicators'), 'PCEPI')
    assert r['obs (T_p)'] == '2026-07' and r['obs (T_c)'] == '2026-08'


def test_target_range_change_and_no_change():
    store = Store()
    target(store, change=True)                     # same-day FRED vintages, as in the stored DFEDTARU data
    res = macro.build(FakeCtx(store), series=list(macro.TARGET))
    c = find(res, 'The federal funds target range changed')
    assert c['level'] == STRONG and c['kind'] == 'official_fact'
    assert '4.00-4.25% for 2026-09-29 as known at T_p' in c['statement'] and '3.75-4.00% for 2026-10-06' in c['statement']
    assert 'DFEDTARU 4.25 -> 4.00 from obs 2026-10-01, first published 2026-10-01 (FRED vintage)' in c['statement']
    assert row(table(res, 'Macro indicators'), 'DFEDTARU')['level'] == STRONG
    assert all(e['fresh_at_cutoff'] is True for e in c['evidence'])

    # no change: the observation for the effective date of a decision announced on s_0 is published after T_c,
    # so the negative fact does not cover the whole window
    store = Store()
    target(store, change=False)
    res = macro.build(FakeCtx(store), series=list(macro.TARGET))
    c = find(res, 'No change of the federal funds target range')
    assert c['level'] == UNCERTAIN and c['reason_codes'] == ['PARTIAL_COVERAGE']
    assert 'no change effective on any date after 2026-09-29 up to 2026-10-06' in c['statement']   # d_p excluded
    assert 'a decision announced on 2026-10-06 (inside the window) would appear only after T_c' in c['statement']
    assert 'effective dates after 2026-10-06' in c['what_would_resolve_it']
    assert not [x for x in res.conclusions if x['statement'].startswith('DFEDTAR')]


def test_target_range_decision_announced_on_s0_is_not_reported_as_no_change():
    """Decision announced on s_0 = 2026-10-06 (inside the window), effective 2026-10-07: FRED's observation
    2026-10-07 is published at end of day 2026-10-07, after T_c. The section must not state a strongly supported
    'no change'; the following week the change is reported."""
    store = Store()
    target(store, change=True, effective='2026-10-07', end='2026-10-12')
    res = macro.build(FakeCtx(store), series=list(macro.TARGET))
    c = find(res, 'No change of the federal funds target range')
    assert c['level'] != STRONG and 'PARTIAL_COVERAGE' in c['reason_codes']
    assert 'decision announced on 2026-10-06' in c['statement']
    later = macro.build(FakeCtx(store, cutoff='2026-10-10T12:00:00+00:00'), series=list(macro.TARGET))
    c = find(later, 'The federal funds target range changed')
    assert 'DFEDTARU 4.25 -> 4.00 from obs 2026-10-07, first published 2026-10-07 (FRED vintage)' in c['statement']


def test_target_range_observation_after_s0_known_at_cutoff_covers_the_window():
    store = Store()
    target(store, change=False)
    store.add('DFEDTARU', '2026-10-07', 4.25, '2026-10-06')          # range for s_0 + 1 published on s_0
    store.add('DFEDTARL', '2026-10-07', 4.00, '2026-10-06')
    res = macro.build(FakeCtx(store), series=list(macro.TARGET))
    c = find(res, 'No change of the federal funds target range')
    assert c['level'] == STRONG and c['reason_codes'] == []
    assert 'Observations up to 2026-10-07 (after s_0 = 2026-10-06) are known at T_c' in c['statement']


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
    payems(store, sep=159300)
    weekly = {'thresholds_version': 'test-v2', 'thresholds': {'macro_abs_change': {'DGS10': 0.10, 'PAYEMS': 50}}}
    res = macro.build(FakeCtx(store, weekly=weekly), series=['DGS10', 'PAYEMS'])
    c = find(res, 'DGS10 (')
    assert c['level'] == UNCERTAIN and 'BELOW_THRESHOLD' in c['reason_codes']
    assert 'HEURISTIC_THRESHOLD' in c['reason_codes'] and '|difference| 0.07 below the pre-declared' in c['statement']
    assert any('test-v2' in n for n in res.notes)
    # the table notes describe the thresholds actually applied (never 'no threshold' when one is configured)
    for title in ('Macro indicators', 'Socio-economic indicators'):
        note = table(res, title)['note']
        assert 'No pre-declared macro materiality threshold' not in note
        assert 'Pre-declared materiality thresholds (thresholds test-v2' in note
    assert 'DGS10 0.1' in table(res, 'Macro indicators')['note']
    assert 'No pre-declared threshold (differences are facts, materiality not assessed): DGS2' in \
        table(res, 'Macro indicators')['note']
    assert row(table(res, 'Macro indicators'), 'DGS10')['materiality threshold (macro_abs_change)'] == 0.1
    assert row(table(res, 'Macro indicators'), 'DGS2')['materiality threshold (macro_abs_change)'].startswith('none')
    assert row(table(res, 'Socio-economic'), 'PAYEMS')['materiality threshold (macro_abs_change)'] == 50
    # a crossing is reported with HEURISTIC_THRESHOLD (thresholds_note): never a strongly supported material change
    p = find(res, 'PAYEMS (')
    assert 'at or above the pre-declared materiality threshold 50' in p['statement']
    assert p['level'] == UNCERTAIN and p['reason_codes'] == ['HEURISTIC_THRESHOLD']
    assert 'heuristic' in p['what_would_resolve_it']


def test_series_without_threshold_is_never_treated_as_threshold_zero():
    store = Store()
    payems(store, sep=159300)
    dgs10(store)
    weekly = {'thresholds_version': 'test-v2', 'thresholds': {'macro_abs_change': {'UNRATE': 0.1}}}
    res = macro.build(FakeCtx(store, weekly=weekly), series=['PAYEMS', 'DGS10'])
    for prefix in ('PAYEMS (', 'DGS10 ('):
        c = find(res, prefix)
        assert 'no pre-declared materiality threshold for this series in thresholds test-v2' in c['statement']
        assert 'materiality not assessed' in c['statement'] and 'at or above' not in c['statement']
        assert c['level'] == STRONG and c['reason_codes'] == []          # a fact, not a material-change claim
    assert any('Series without a threshold' in n and 'PAYEMS' in n for n in res.notes)


def test_threshold_comparison_uses_a_tolerance():
    """4.3 - 4.2 = 0.09999999999999964 in binary floats: a decimal difference equal to the threshold is 'at or
    above' it, whatever the rounding of the two levels."""
    assert macro._below(4.3 - 4.2, 0.1) is False and macro._below(4.4 - 4.3, 0.1) is False
    assert macro._below(4.35 - 4.25, 0.1) is False and macro._below(0.0999, 0.1) is True
    assert macro._below(15000 - 0.01, 15000) is True and macro._below(15000.0, 15000) is False
    store = Store()
    unrate(store, sep=4.3)                                       # 4.2 -> 4.3, threshold 0.1
    add_daily(store, 'DGS10', '2026-06-01', '2026-10-07', lambda d: 4.25 if d <= date(2026, 9, 28) else 4.35)
    weekly = {'thresholds_version': 'test-v2', 'thresholds': {'macro_abs_change': {'UNRATE': 0.1, 'DGS10': 0.1}}}
    res = macro.build(FakeCtx(store, weekly=weekly), series=['UNRATE', 'DGS10'])
    for prefix in ('UNRATE (', 'DGS10 ('):
        c = find(res, prefix)
        assert 'BELOW_THRESHOLD' not in c['reason_codes'] and 'HEURISTIC_THRESHOLD' in c['reason_codes']
        assert '|difference| 0.1 at or above the pre-declared materiality threshold 0.1' in c['statement']
        assert 'tolerance 1e-09 x max(1, threshold)' in c['statement']


def test_build_with_the_shipped_weekly_config():
    """scheduler_config.json weekly (thresholds v2: macro_abs_change pre-declared): notes and tables agree."""
    weekly = load_config()['weekly']
    thr = weekly['thresholds']['macro_abs_change']
    store = Store()
    dgs10(store)
    unrate(store, sep=4.3)
    payems(store, sep=159300)
    icsa(store)
    res = macro.build(FakeCtx(store, weekly=weekly), series=['DGS10', 'UNRATE', 'PAYEMS', 'ICSA'])
    version = weekly['thresholds_version']
    assert any(n.startswith(f'Thresholds {version}: macro materiality thresholds applied') for n in res.notes)
    for t in res.tables:
        assert 'No pre-declared macro materiality threshold in thresholds' not in (t['note'] or '')
    assert f'Pre-declared materiality thresholds (thresholds {version}' in table(res, 'Macro indicators')['note']
    assert f'Pre-declared materiality thresholds (thresholds {version}' in table(res, 'Socio-economic')['note']
    u = find(res, 'UNRATE (')
    assert thr['UNRATE'] == 0.1 and 'at or above the pre-declared materiality threshold 0.1' in u['statement']
    assert 'BELOW_THRESHOLD' not in u['reason_codes'] and 'HEURISTIC_THRESHOLD' in u['reason_codes']
    d = find(res, 'DGS10 (')                         # +0.07 pp < 0.10
    assert 'BELOW_THRESHOLD' in d['reason_codes'] and d['level'] == UNCERTAIN
    assert 'PAYEMS' not in thr and 'materiality not assessed' in find(res, 'PAYEMS (')['statement']
    assert row(table(res, 'Socio-economic'), 'ICSA')['materiality threshold (macro_abs_change)'] == thr['ICSA']


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

    # the production path: Context.vintages (P3.1) returns the same versions as the fallback query
    class VintagesCtx(DBCtx):
        vintages = Context.vintages

    vctx = VintagesCtx()
    assert macro._versions(vctx, 'DGS10') == versions
    assert macro._versions(vctx, 'DGS10') == [(o, v, p) for o, v, p in vctx.vintages('DGS10', T_C)]
    res_v = macro.build(vctx, series=['DGS10'])
    assert find(res_v, 'DGS10 (')['statement'] == c['statement']


def test_end_of_day_values_dated_after_the_session_or_published_before_their_day_are_not_used():
    """Stored VIXCLS holiday rows carry a FRED vintage date BEFORE their own date (e.g. 2026-09-07 published with
    vintage 2026-09-04). A close cannot be public before the end of its day: such versions are not used, and values
    as known at T_c / T_p stop at s_0 / s_-5."""
    store = Store()
    add_daily(store, 'VIXCLS', '2026-06-01', '2026-10-07', lambda d: 15 + 0.1 * (d - date(2026, 6, 1)).days)
    store.add('VIXCLS', '2026-10-08', 99.0, '2026-10-05')     # dated after s_0, "published" before T_c
    store.add('VIXCLS', '2026-10-03', 50.0, '2026-10-02')     # a Saturday inside the week, published the day before
    store.add('VIXCLS', '2026-09-30', 77.0, '2026-09-28')     # after s_-5, "known" at T_p; real print vintage 10-01
    res = macro.build(FakeCtx(store), series=['VIXCLS'])
    r = row(table(res, 'Macro indicators'), 'VIXCLS')
    assert r['obs (T_c)'] == '2026-10-05' and r['obs (T_p)'] == '2026-09-28'
    c = find(res, 'VIXCLS (')
    assert '2026-10-08' not in c['statement'] and '99' not in c['statement']
    assert all(e['as_of'] <= '2026-10-06' for e in c['evidence'])
    def v(day):
        return 15 + 0.1 * (date.fromisoformat(day) - date(2026, 6, 1)).days
    mean = next(x for x in table(res, 'Daily macro series')['rows'] if x[0] == 'VIXCLS')
    week = ['2026-09-30', '2026-10-01', '2026-10-02', '2026-10-05']
    assert mean[2] == 4 and mean[1] == pytest.approx(round(sum(v(x) for x in week) / 4, 4))
    prev = ['2026-09-23', '2026-09-24', '2026-09-25', '2026-09-28']
    assert mean[4] == 4 and mean[3] == pytest.approx(round(sum(v(x) for x in prev) / 4, 4))
    note = [n for n in res.notes if n.startswith('VIXCLS: 3 stored FRED version(s)')]
    assert note and 'not credible' in note[0]


def mortgage(store, replace):
    """MORTGAGE30US: Thursdays (FRED vintage = obs date); `replace` {thursday: wednesday} for holiday weeks."""
    d, k = date(2026, 1, 1), 0
    while d <= date(2026, 10, 1):
        obs = replace.get(d.isoformat(), d.isoformat())
        store.add('MORTGAGE30US', obs, 6.0 + 0.01 * k, obs)
        d, k = d + timedelta(days=7), k + 1
    return k


def test_weekly_prior_period_follows_holiday_shifted_release_dates():
    # holiday week before the release: prior observation dated on a Wednesday, 8 days earlier
    store = Store()
    n = mortgage(store, {'2026-09-24': '2026-09-23'})
    res = macro.build(FakeCtx(store), series=['MORTGAGE30US'])
    c = find(res, 'MORTGAGE30US (')
    assert 'change vs 2026-09-23 (both from the T_c vintage) +0.01 pp' in c['statement']
    assert not [u for u in res.unavailable if u['item'].startswith('MORTGAGE30US: change')]
    r = row(table(res, 'Socio-economic'), 'MORTGAGE30US')
    assert r['prior period'] == '2026-09-23' and r['change vs prior period (T_c vintage)'] == pytest.approx(0.01)
    assert f'over {n - 1} periods' in c['statement']             # every period after the first is in the sample
    # the release itself dated on a Wednesday (6 days after the prior Thursday)
    store = Store()
    mortgage(store, {'2026-10-01': '2026-09-30'})
    res = macro.build(FakeCtx(store), series=['MORTGAGE30US'])
    assert 'first print for 2026-09-30' in find(res, 'MORTGAGE30US (')['statement']
    assert row(table(res, 'Socio-economic'), 'MORTGAGE30US')['prior period'] == '2026-09-24'
    assert not [u for u in res.unavailable if u['item'].startswith('MORTGAGE30US: change')]
    # no observation 4-10 days earlier: not computable, with that reason
    store = Store()
    for obs in ('2026-08-27', '2026-10-01'):
        store.add('MORTGAGE30US', obs, 6.1, obs)
    res = macro.build(FakeCtx(store), series=['MORTGAGE30US'])
    u = [x for x in res.unavailable if x['item'].startswith('MORTGAGE30US: change')]
    assert u and 'no observation for 2026-09-24' in u[0]['reason'] and '4 to 10 days before' in u[0]['reason']


def test_umcsent_revision_record_carries_the_timestamp_caveat():
    store = Store()
    for m in months('2025-06', '2026-08'):
        store.add('UMCSENT', m, 50 + int(m[5:7]) / 10, next_month(m, 25))
    store.add('UMCSENT', '2026-08-01', 51.5, '2026-10-02')       # revision published inside the window
    res = macro.build(FakeCtx(store), series=['UMCSENT'])
    rev = find(res, 'UMCSENT: 1 previously published')
    assert rev['level'] == UNCERTAIN and rev['reason_codes'] == ['TIMESTAMP_AMBIGUOUS']
    assert 'University of Michigan Surveys of Consumers' in rev['what_would_resolve_it']
    item = rev['evidence'][0]
    assert item['as_of'] == '2026-10-02' and item['fresh_at_cutoff'] is True     # the revision event, dated by vintage
    assert "'event' cadence" in item['published_at_basis']


def test_change_must_exceed_the_level_revision_too():
    """A benchmark-like revision shifts every level by +1,000 (the change revisions stay 0): a +250 payroll change
    beyond the change revisions is still not shown to exceed revision noise (the stricter of the two rules)."""
    store = Store()
    for m, v, vint in PAYEMS_FIRST:
        store.add('PAYEMS', m + '-01', v, vint)
        store.add('PAYEMS', m + '-01', v + 1000, '2026-09-10')          # benchmark revision, levels only
    store.add('PAYEMS', '2026-09-01', 159000 + 1000 + 250, '2026-10-02')
    res = macro.build(FakeCtx(store), series=['PAYEMS'])
    r = row(table(res, 'Socio-economic'), 'PAYEMS')
    assert r['change vs prior period (T_c vintage)'] == 250
    assert r['largest revision of the level in stored vintages'] == 1000
    assert r['largest revision of that change in stored vintages'] == 0
    c = find(res, 'PAYEMS (')
    assert r['beyond revision noise'] == 'no' and c['reason_codes'] == ['FIRST_PRINT_WITHIN_REVISION_NOISE']
    assert 'largest revision of the level in stored vintages 1,000' in c['statement']
    assert '"beyond revision noise" requires |change| > the larger of the two' in c['statement']


def test_percent_change_series_and_relative_level_noise():
    store = Store()
    level = {}
    for k, m in enumerate(months('2025-10', '2026-08')):
        level[m] = 700000 * 1.003 ** k
        store.add('RSAFS', m, level[m], next_month(m, 15))
    store.add('RSAFS', '2026-08-01', level['2026-08-01'] + 700, '2026-09-20')    # revision before T_p
    sep = level['2026-08-01'] * 1.006
    store.add('RSAFS', '2026-09-01', sep, '2026-10-02')                          # first print in the window
    res = macro.build(FakeCtx(store), series=['RSAFS'])
    r = row(table(res, 'Socio-economic'), 'RSAFS')
    chg = (sep / (level['2026-08-01'] + 700) - 1) * 100                         # within the T_c vintage
    assert r['change vs prior period (T_c vintage)'] == pytest.approx(round(chg, 4))
    change_noise = 700 / level['2026-07-01'] * 100
    level_noise = 700 / level['2026-08-01'] * 100
    assert r['largest revision of that change in stored vintages'] == pytest.approx(round(change_noise, 4))
    assert r['largest revision of the level in stored vintages'] == pytest.approx(round(level_noise, 4))
    assert r['beyond revision noise'] == ('yes' if chg > max(change_noise, level_noise) else 'no')
    c = find(res, 'RSAFS (')
    assert '% of the first print' in c['statement'] and c['level'] == STRONG


def test_latest_observation_revised_without_new_release():
    store = Store()
    for m in months('2025-06', '2026-08'):
        store.add('GEPUCURRENT', m, 200 + int(m[5:7]), next_month(m, 10))
    store.add('GEPUCURRENT', '2026-08-01', 230, '2026-10-02')
    res = macro.build(FakeCtx(store), series=['GEPUCURRENT'])
    g = find(res, 'GEPUCURRENT (', question=4)
    assert 'the latest observation (2026-08) was revised from 208 (as known at T_p) to 230 (as known at T_c)' \
        in g['statement']
    assert 'difference +22 points' in g['statement'] and 'no new observation first published' in g['statement']
    assert [e['as_of'] for e in g['evidence']] == ['2026-08-01', '2026-08-01'] and g['level'] == STRONG


def test_every_freshness_flag_matches_freshness_of_its_own_as_of():
    """No item says fresh_at_cutoff=True for an as_of that freshness() reports STALE at the instant it states."""
    store = Store()
    dgs10(store)
    nfci(store)
    cpi(store)
    payems(store)
    unrate(store)
    icsa(store)
    target(store)
    epu(store)
    for k, m in enumerate(months('2025-01', '2026-08')):
        store.add('PCEPI', m, 125 * 1.002 ** k, '2026-09-30' if m == '2026-08-01' else next_month(m, 28))
    res = macro.build(FakeCtx(store))
    checked = 0
    for c in res.conclusions:
        for e in c['evidence']:
            sid = e['fact'].split(':')[0]
            basis = e['published_at_basis'] or ''
            cadence = 'event' if "'event' cadence" in basis else macro.SERIES[sid]['cadence']
            at = T_P if 'freshness evaluated at T_p' in basis else T_C
            status = freshness(e['as_of'], cadence, now=datetime.fromisoformat(at))['status']
            assert e['fresh_at_cutoff'] is (status == 'FRESH'), (c['statement'][:60], e['fact'])
            checked += 1
    assert checked > 20


def test_section_never_reads_the_wall_clock():
    source = Path(macro.__file__).read_text(encoding='utf-8')
    pattern = (r'\b(datetime|date|Timestamp)\s*\.\s*(now|utcnow|today)\b|\btime\s*\.\s*(time|monotonic|perf_counter)'
               r'\s*\(|utc_now_iso|\bimport\s+time\b|from\s+time\s+import')
    for probe in ('datetime.utcnow()', 'datetime.today()', 'pd.Timestamp.now()', 'pd.Timestamp.today()',
                  'date.today()', 'datetime.now(timezone.utc)', 'time.time()', 'utc_now_iso()', 'import time'):
        assert re.search(pattern, probe), probe                    # the guard catches every common clock read
    assert not re.search(pattern, source)
    assert not re.search(r'from\s+datetime\s+import[^\n]*\bdatetime\b|^import\s+datetime', source, re.MULTILINE)
