"""Weekly report section 'geopolitics' (Q4) - offline tests on an isolated database.

The Federal Register record is copied from a real API response of 2026-10-11 (OFAC notice 2026-20683);
the other documents, GPR and GDELT values are SYNTHETIC (logic tests only, never in a report).
"""

import json
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import pandas as pd

from src import external_sources as ex
from src.database import Database, freshness
from src.weekly.core import STRONG, UNCERTAIN, TimeModel
from src.weekly.sections import geopolitics

ALL_SESSIONS = [d.date().isoformat() for d in pd.bdate_range(end='2026-10-09', periods=400)]
CUTOFF = '2026-10-10T12:00:00+00:00'      # s_0 = 2026-10-09, T_c = 2026-10-10T05:00Z, T_p = 2026-10-03T05:00Z
AFTER = '2026-10-11T21:00:00+00:00'       # collect run after the cutoff
OFAC = {'publication_date': '2026-10-08', 'type': 'Notice', 'document_number': '2026-20683',
        'title': 'Notice of OFAC Sanctions Actions', 'agencies': [{'name': 'Foreign Assets Control Office'}]}


class Ctx:
    def __init__(self, db):
        self.tm = TimeModel(ALL_SESSIONS, CUTOFF, AFTER)
        self.db, self.universe, self.weekly = db, [], {}

    def freshness(self, as_of, cadence, at=None):
        return freshness(as_of, cadence, now=datetime.fromisoformat(at or self.tm.cutoff))


def fr_search(db, slug, since, results, completed=AFTER, pages=1):
    """A stored Federal Register search (endpoint as built by the collector) and its documents."""
    cond = ('conditions[type][]', 'PRESDOCU') if slug == ex.FR_PRESIDENTIAL else ('conditions[agencies][]', slug)
    params = [cond, ('conditions[publication_date][gte]', since), ('per_page', 200), ('order', 'oldest')]
    endpoint = ex.FR_URL + '?' + urlencode(params + [('fields[]', f) for f in ex.FR_FIELDS])
    fetch = db.record_fetch('Federal Register', endpoint, status='OK',
                            raw={'count': len(results), 'total_pages': pages, 'results': results})
    with db.connect() as conn:
        conn.execute('UPDATE source_fetches SET requested_at=?, completed_at=? WHERE fetch_id=?',
                     (completed, completed, fetch['fetch_id']))
    db.upsert_observations(dict(fetch, retrieved_at=completed), ex.fr_rows(f'FR:{slug}', results))


def indices(db):
    rows = []
    for k in range(20):
        d = (date(2026, 10, 9) - timedelta(days=k)).isoformat()
        if d <= '2026-10-05':                  # GPR file known at T_c stops at 10-05 (partial week)
            rows.append({'entity': 'GPR', 'metric': 'gpr_daily', 'as_of_date': d, 'value': 100.0 + k,
                         'published_at': '2026-10-06T13:00:00+00:00', 'published_at_basis': 'HTTP Last-Modified'})
        pub = (datetime.fromisoformat(d) + timedelta(days=1, hours=12)).isoformat() + '+00:00'
        for key, n in (('global', 7000 + 10 * k), ('USA-CHN', 20 + k)):
            rows.append({'entity': f'GDELT:{key}', 'metric': 'material_conflict_root', 'as_of_date': d, 'value': n,
                         'published_at': pub, 'published_at_basis': ex.GDELT_BASIS})
    fetch = dict(db.record_fetch('GDELT', 'test:indices', status='OK'), retrieved_at=AFTER)
    db.upsert_observations(fetch, [r for r in rows if r['entity'] != 'GPR'])
    fetch = dict(db.record_fetch('GPR index (Caldara-Iacoviello)', 'test:gpr', status='OK'), retrieved_at=AFTER)
    db.upsert_observations(fetch, [r for r in rows if r['entity'] == 'GPR'])


def build():
    db = Database()
    fr_search(db, 'foreign-assets-control-office', '2026-08-12',
              [OFAC, {**OFAC, 'document_number': '2026-19000', 'publication_date': '2026-10-01'},    # before T_p
               {**OFAC, 'document_number': '2026-21000', 'publication_date': '2026-10-13'}])        # future issue
    fr_search(db, 'industry-and-security-bureau', '2026-08-12', [])
    fr_search(db, ex.FR_PRESIDENTIAL, '2026-10-06',                                                  # starts too late
              [{'publication_date': '2026-10-07', 'type': 'Presidential Document', 'document_number': '2026-20500',
                'title': 'National Manufacturing Day, 2026'}])
    indices(db)
    return geopolitics.build(Ctx(db)).as_dict()


def find(out, start):
    return next(c for c in out['conclusions'] if c['statement'].startswith(start))


def test_federal_register_documents_in_the_window_and_coverage():
    out = build()
    assert out['name'] == 'geopolitics' and out['questions'] == [4]
    ofac = find(out, 'Federal Register, Office of Foreign Assets Control')
    assert ofac['level'] == STRONG and '1 document published in the window' in ofac['statement']
    assert '2026-10-08 Notice: Notice of OFAC Sanctions Actions' in ofac['statement']
    assert '2026-19000' not in json.dumps(ofac) and '2026-21000' not in json.dumps(ofac)
    assert ofac['evidence'][0]['published_at'] == '2026-10-08T10:00:00+00:00'
    bis = find(out, 'Federal Register, Bureau of Industry and Security')
    assert bis['level'] == STRONG and 'no document published in the window' in bis['statement']
    assert bis['evidence'][0]['published_at'] == '2026-10-10T05:00:00+00:00'      # negative fact dated at T_c
    pres = find(out, 'Federal Register, Presidential documents')
    assert '1 document (at least)' in pres['statement'] and 'PARTIAL_COVERAGE' in pres['reason_codes']
    reasons = {u['item']: u['reason'] for u in out['unavailable']}
    ustr = reasons['Federal Register: Office of the U.S. Trade Representative (trade) documents published in the window']
    assert 'absence is not established' in ustr
    rows = next(t for t in out['tables'] if t['title'].startswith('Federal Register'))['rows']
    assert sorted(r[4] for r in rows) == ['2026-20500', '2026-20683']


def test_truncated_search_does_not_establish_absence():
    db = Database()
    fr_search(db, 'industry-and-security-bureau', '2026-08-12', [], pages=2)
    out = geopolitics.build(Ctx(db)).as_dict()
    assert not [c for c in out['conclusions'] if 'Bureau of Industry' in c['statement']]
    assert any('Bureau of Industry' in u['item'] for u in out['unavailable'])


def test_gpr_and_gdelt_are_aggregators_with_partial_weeks():
    out = build()
    gpr = find(out, 'GPR daily index')
    assert gpr['level'] == UNCERTAIN and {'AGGREGATOR_ONLY', 'PARTIAL_COVERAGE'} <= set(gpr['reason_codes'])
    assert 'over the 3 day(s) dated in (2026-10-02, 2026-10-09]' in gpr['statement']
    assert 'no file version known at T_p is stored' in gpr['statement']           # GPR file published 10-06
    gdelt = find(out, 'GDELT (automated coding')
    assert gdelt['level'] == UNCERTAIN and 'not a record of events' in gdelt['statement']
    # week (10-02, 10-09] known at T_c: 10-03..10-08 (the 10-09 file is published 10-10 12:00 UTC, after T_c)
    t = next(t for t in out['tables'] if t['title'].startswith('Geopolitical indices'))
    row = next(r for r in t['rows'] if r[0].startswith('GDELT USA-CHN'))
    assert row[4] == 6 and row[3] == sum(20 + k for k in range(1, 7)) / 6
    assert row[2] == 6                                        # previous week known at T_p: 09-26..10-01
