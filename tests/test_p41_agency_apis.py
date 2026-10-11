"""
P4.1 keyed agency APIs (BLS v2, BEA NIPA, EIA v2): parsing of real payload excerpts (tests/fixtures/external,
retrieved 2026-10-11 with the keys removed), publication dates, key redaction and DATA UNAVAILABLE without a
key. Offline (conftest blocks HTTP). The second BEA table version in the "unchanged values" test is constructed
(logic test only).
"""

import json
from datetime import date
from pathlib import Path

import pytest

from src import agency_apis as ag
from src import external_sources as ex
from src.common import DATA_UNAVAILABLE, redact
from src.database import Database

FIX = Path(__file__).parent / 'fixtures' / 'external'
BLS_KEY, BEA_KEY, EIA_KEY = 'blsTESTkey0123456789', 'BEA-TEST-KEY-0000-1111', 'eiaTESTkey9876543210'


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.content, self.headers = text, status, text.encode(), {}


class FakeHTTP:
    def __init__(self, *texts):
        self.texts, self.calls = list(texts), []

    def _next(self, url, kw):
        self.calls.append((url, kw))
        return Resp(self.texts.pop(0) if len(self.texts) > 1 else self.texts[0])

    def get(self, url, **kw):
        return self._next(url, kw)

    def post(self, url, **kw):
        return self._next(url, kw)


@pytest.fixture
def http(monkeypatch):
    def install(*texts):
        fake = FakeHTTP(*texts)
        monkeypatch.setattr(ex, 'requests', fake)
        return fake
    monkeypatch.setattr(ex, '_throttle', lambda url: None)
    return install


def fixture(name):
    return (FIX / name).read_text()


def fetch_rows(db):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM source_fetches')]


# ------------------------------------------------------------------ keys

def test_missing_keys_make_no_call(http):
    fake = http('{}')
    db = Database()
    results = [ag.collect_bls_api(db, 2025, 2026), ag.collect_bea(db, [2026]), ag.collect_eia(db, date(2026, 1, 1))]
    assert [r['status'] for r in results] == [DATA_UNAVAILABLE] * 3
    assert [r['reason'] for r in results] == ['BLS_API_KEY not set', 'BEA_API_KEY not set', 'EIA_API_KEY not set']
    assert fake.calls == [] and fetch_rows(db) == []


def test_key_parameters_are_redacted_without_env_value():
    assert redact('https://apps.bea.gov/api/data?UserID=abc-123-def&method=GetData') == \
        'https://apps.bea.gov/api/data?UserID=***REDACTED***&method=GetData'
    assert 'secret99' not in redact('x?registrationkey=secret99')


# ------------------------------------------------------------------ BLS

def test_bls_rows_from_real_excerpt():
    payload = json.loads(fixture('bls_v2_2026-10-11_excerpt.json'))
    payload['Results']['series'][0]['data'] += [{'year': '2025', 'period': 'M13', 'value': '320.0'},
                                                {'year': '2026', 'period': 'M06', 'value': '-'}]
    payload['Results']['series'].append({'seriesID': 'NOTDECLARED', 'data': [{'year': '2026', 'period': 'M08',
                                                                             'value': '1.0'}]})
    rows, seen = ag.bls_rows(payload)
    by = {(r['entity'], r['as_of_date']): r for r in rows}
    assert seen == {'CUSR0000SA0', 'CES0000000001', 'LNS14000000'}
    assert by[('BLS:CUSR0000SA0', '2026-08-01')]['value'] == 334.131
    assert by[('BLS:CES0000000001', '2026-09-01')]['value'] == 159044
    assert by[('BLS:LNS14000000', '2026-09-01')]['unit'] == '%'
    assert len(rows) == 6                                # M13, '-' and the undeclared series are not stored
    assert all(r['published_at'] is None and 'retrieval time' in r['published_at_basis'] for r in rows)


def test_collect_bls_api_stores_values_and_never_the_key(monkeypatch, http):
    monkeypatch.setenv('BLS_API_KEY', BLS_KEY)
    monkeypatch.setattr(ag, 'BLS_SERIES', {k: ag.BLS_SERIES[k]
                                           for k in ('CUSR0000SA0', 'CES0000000001', 'LNS14000000')})
    fake = http(fixture('bls_v2_2026-10-11_excerpt.json'))
    db = Database()
    res = ag.collect_bls_api(db, 2026, 2026)
    assert res['status'] == 'OK' and res['stored'] == 6
    assert fake.calls[0][1]['json']['registrationkey'] == BLS_KEY
    assert fake.calls[0][1]['json']['seriesid'] == ['CUSR0000SA0', 'CES0000000001', 'LNS14000000']
    (fetch,) = fetch_rows(db)
    assert BLS_KEY not in fetch['endpoint'] and '***REDACTED***' in fetch['endpoint']
    row = dict(db.series('BLS:CUSR0000SA0', 'value', source='BLS'))['2026-08-01']
    assert row['value'] == 334.131 and row['published_at'] is None
    assert ag.collect_bls_api(db, 2026, 2026)['stored'] == 0          # same values: no new version


def test_bls_invalid_key_is_unavailable_and_the_echoed_key_is_redacted(monkeypatch, http):
    monkeypatch.setenv('BLS_API_KEY', 'bad-key-test')
    http(fixture('bls_v2_invalid_key_2026-10-11.json'))
    db = Database()
    res = ag.collect_bls_api(db, 2026, 2026)
    assert res['status'] == DATA_UNAVAILABLE and res['stored'] == 0
    assert 'REQUEST_NOT_PROCESSED' in res['reason'] and 'bad-key-test' not in res['reason']
    (fetch,) = fetch_rows(db)
    assert 'bad-key-test' not in db.read_raw(fetch['fetch_id'])


# ------------------------------------------------------------------ BEA

def test_bea_period():
    assert ag.bea_period('2026Q2') == '2026-04-01' and ag.bea_period('2026Q4') == '2026-10-01'
    assert ag.bea_period('2026M08') == '2026-08-01'
    assert ag.bea_period('2026') is None and ag.bea_period('2026M13') is None and ag.bea_period(None) is None


def test_bea_rows_from_real_excerpts():
    rows, revised, problems = ag.bea_rows('T10101', json.loads(fixture('bea_T10101_2026-10-11_excerpt.json')))
    assert revised == date(2026, 9, 30) and problems == []
    by = {(r['entity'], r['as_of_date']): r for r in rows}
    assert set(by) == {('BEA:A191RL', '2026-01-01'), ('BEA:A191RL', '2026-04-01'),
                       ('BEA:DPCERL', '2026-01-01'), ('BEA:DPCERL', '2026-04-01')}     # A006RL not declared
    assert by[('BEA:A191RL', '2026-04-01')]['value'] == 2.2
    assert by[('BEA:A191RL', '2026-04-01')]['published_at'] == '2026-10-01T05:00:00+00:00'
    assert 'LastRevised: 2026-09-30' in by[('BEA:A191RL', '2026-04-01')]['published_at_basis']

    rows, _, problems = ag.bea_rows('T20600', json.loads(fixture('bea_T20600_2026-10-11_excerpt.json')))
    by = {(r['entity'], r['as_of_date']): r for r in rows}
    assert problems == []
    assert by[('BEA:A065RC', '2026-08-01')]['value'] == 27626933          # "27,626,933"
    assert by[('BEA:A065RC', '2026-08-01')]['unit'] == 'USD millions (SAAR)'
    assert by[('BEA:A072RC', '2026-08-01')]['value'] == 4.1


def test_bea_unit_multiplier_change_is_reported_not_stored():
    payload = json.loads(fixture('bea_T20600_2026-10-11_excerpt.json'))
    for d in payload['BEAAPI']['Results']['Data']:
        if d['SeriesCode'] == 'A065RC':
            d['UNIT_MULT'] = '9'
    rows, _, problems = ag.bea_rows('T20600', payload)
    assert problems == ['A065RC: UNIT_MULT 9 instead of 6 (units changed?)']
    assert not any(r['entity'] == 'BEA:A065RC' for r in rows)


def test_bea_error_payload():
    assert ag.bea_error(json.loads(fixture('bea_error_2026-10-11.json'))) == \
        'BEA error 201: Error retrieving NIPA data. (Invalid TableName was requested.)'
    assert ag.bea_error(json.loads(fixture('bea_T10101_2026-10-11_excerpt.json'))) is None


def test_collect_bea_redacts_echoed_key_and_keeps_publication_of_unchanged_values(monkeypatch, http):
    monkeypatch.setenv('BEA_API_KEY', BEA_KEY)
    monkeypatch.setattr(ag, 'BEA_TABLES', {'T10101': ag.BEA_TABLES['T10101']})
    first = fixture('bea_T10101_2026-10-11_excerpt.json').replace('KEY-REMOVED', BEA_KEY)   # BEA echoes UserID
    db = Database()
    fake = http(first)
    res = ag.collect_bea(db, [2026])
    assert res['status'] == 'OK' and res['stored'] == 4 and res['last_revised'] == {'T10101': '2026-09-30'}
    assert fake.calls[0][1]['params']['UserID'] == BEA_KEY
    (fetch,) = fetch_rows(db)
    assert BEA_KEY not in fetch['endpoint'] and BEA_KEY not in db.read_raw(fetch['fetch_id'])

    # constructed next table version: LastRevised moves, only 2026Q2 GDP changes
    payload = json.loads(first)
    note = payload['BEAAPI']['Results']['Notes'][0]
    note['NoteText'] = note['NoteText'].replace('September 30, 2026', 'October 1, 2026')
    for d in payload['BEAAPI']['Results']['Data']:
        if d['SeriesCode'] == 'A191RL' and d['TimePeriod'] == '2026Q2':
            d['DataValue'] = '2.4'
    http(json.dumps(payload))
    assert ag.collect_bea(db, [2026])['stored'] == 1
    gdp = dict(db.series('BEA:A191RL', 'value', source='BEA'))
    assert gdp['2026-04-01']['value'] == 2.4 and gdp['2026-04-01']['published_at'] == '2026-10-02T05:00:00+00:00'
    assert gdp['2026-01-01']['published_at'] == '2026-10-01T05:00:00+00:00'        # unchanged: first date kept
    before = db.get_point_in_time('BEA:A191RL', 'value', known_at='2026-10-01T12:00:00+00:00')
    assert before['value'] == 2.2                                                   # no look-ahead
    assert db.count('observations') == 5


# ------------------------------------------------------------------ EIA

def test_eia_rows_from_real_excerpt():
    payload = json.loads(fixture('eia_spt_2026-10-11_excerpt.json'))
    payload['response']['data'].append({**payload['response']['data'][0], 'period': '2026-10-02', 'value': None})
    rows, seen = ag.eia_rows(payload, {'RWTC': '', 'RBRTE': ''})
    by = {(r['entity'], r['as_of_date']): r for r in rows}
    assert seen == {'RWTC', 'RBRTE'} and len(rows) == 4                 # the null value is not stored
    assert by[('EIA:RWTC', '2026-10-06')]['value'] == 96.24
    assert by[('EIA:RBRTE', '2026-10-06')]['value'] == 125.44
    assert by[('EIA:RWTC', '2026-10-06')]['unit'] == '$/BBL' and by[('EIA:RWTC', '2026-10-06')]['published_at'] is None


def test_collect_eia_query_redaction_and_truncation(monkeypatch, http):
    monkeypatch.setenv('EIA_API_KEY', EIA_KEY)
    monkeypatch.setattr(ag, 'EIA_ROUTES', {'petroleum/pri/spt': ag.EIA_ROUTES['petroleum/pri/spt']})
    text = fixture('eia_spt_2026-10-11_excerpt.json')
    fake = http(text)
    db = Database()
    res = ag.collect_eia(db, date(2026, 9, 30))
    assert res['status'] == 'OK' and res['stored'] == 4
    url = fake.calls[0][0]
    assert url.startswith('https://api.eia.gov/v2/petroleum/pri/spt/data/?')
    assert 'facets%5Bseries%5D%5B%5D=RWTC' in url and 'facets%5Bseries%5D%5B%5D=RBRTE' in url
    assert 'start=2026-09-30' in url and f'api_key={EIA_KEY}' in url
    (fetch,) = fetch_rows(db)
    assert EIA_KEY not in fetch['endpoint'] and 'api_key=***REDACTED***' in fetch['endpoint']

    payload = json.loads(text)
    payload['response']['total'] = '10'
    http(json.dumps(payload))
    res = ag.collect_eia(db, date(2026, 9, 30))
    assert res['status'] == DATA_UNAVAILABLE and '4 of 10 rows returned' in res['reason']
