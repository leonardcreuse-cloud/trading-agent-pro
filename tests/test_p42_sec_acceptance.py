"""
P4.2 SEC acceptance label conventions. The EDGAR index page excerpts (tests/fixtures/external) and the feed labels
quoted below are real (retrieved 2026-10-11): MP labels are the true UTC instant, CRWD labels are the true UTC
instant + the New York offset. Network is blocked (conftest): SEC answers are faked from those values.
"""

from pathlib import Path

import pytest
import requests

from src.sec_parser import (SECParser, acceptance_from_label, acceptance_to_utc, index_accepted,
                            label_convention)

FIX = Path(__file__).parent / 'fixtures' / 'external'
MP_INDEX = (FIX / 'edgar_index_mp_0001801368-26-000052.html').read_text()
CRWD_INDEX = (FIX / 'edgar_index_crwd_0001778564-26-000179.html').read_text()


def test_index_page_accepted_time_is_new_york_wall_clock():
    assert index_accepted(MP_INDEX) == '2026-10-01T00:24:39+00:00'        # 2026-09-30 20:24:39 EDT
    assert index_accepted(CRWD_INDEX) == '2026-10-09T00:00:07+00:00'      # 2026-10-08 20:00:07 EDT
    assert index_accepted('<html>no accepted field</html>') is None


def test_label_conventions_from_real_pairs():
    assert label_convention('2026-10-01T00:24:39.000Z', index_accepted(MP_INDEX)) == 'utc'
    assert label_convention('2026-10-09T04:00:07.000Z', index_accepted(CRWD_INDEX)) == 'utc_plus_ny_offset'
    assert label_convention('2026-09-30T20:24:39.000Z', index_accepted(MP_INDEX)) == 'ny_wall'   # constructed
    assert label_convention('2026-10-01T03:24:39.000Z', index_accepted(MP_INDEX)) is None


def test_conversion_summer_and_winter_and_never_after_the_conservative_reading():
    assert acceptance_from_label('2026-10-09T04:00:07.000Z', 'utc_plus_ny_offset') == '2026-10-09T00:00:07+00:00'
    # CRWD Form 4 accepted 2026-02-05 20:00:07 EST, labelled 2026-02-06T06:00:07Z (UTC + 5 h)
    assert acceptance_from_label('2026-02-06T06:00:07.000Z', 'utc_plus_ny_offset') == '2026-02-06T01:00:07+00:00'
    assert acceptance_from_label('2026-10-01T00:24:39.000Z', 'utc') == '2026-10-01T00:24:39+00:00'
    assert acceptance_from_label('2026-09-30T20:24:39.000Z', 'ny_wall') == '2026-10-01T00:24:39+00:00'
    assert acceptance_from_label('2026-10-01T00:24:39.000Z', None) is None
    for label in ('2026-10-09T04:00:07.000Z', '2026-02-06T06:00:07.000Z', '2026-07-01T12:00:00.000Z'):
        for convention in ('utc', 'utc_plus_ny_offset', 'ny_wall'):
            assert acceptance_from_label(label, convention) <= acceptance_to_utc(label)


class Page:
    def __init__(self, text=None, payload=None, status=200):
        self.text, self._payload, self.status_code = text, payload, status
        self.headers, self.content = {}, (text or '').encode()

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f'HTTP {self.status_code}')


def fake_sec(monkeypatch, labels, index_pages):
    """CRWD-like feed of three Form 4 with `labels`; index pages by accession (missing: HTTP 404)."""
    monkeypatch.setenv('SEC_USER_AGENT', 'TestAgent test@example.com')
    accessions = ['0001778564-26-000179', '0001415889-24-017742', '0000950103-20-024040']
    feed = {'filings': {'recent': {'form': ['4', '4', '4'], 'filingDate': ['2026-10-08', '2024-06-03', '2020-06-01'],
                                   'reportDate': ['', '', ''], 'accessionNumber': accessions,
                                   'acceptanceDateTime': labels, 'primaryDocument': ['a.xml'] * 3}}}

    def get(self, url, timeout=None):
        if url.endswith('company_tickers.json'):
            return Page(payload={'0': {'cik_str': 1535527, 'ticker': 'CRWD', 'title': 'CrowdStrike'}})
        if url.endswith('CIK0001535527.json'):
            return Page(payload=feed)
        for acc in accessions:
            if url.endswith(f'{acc}-index.htm') and acc in index_pages:
                return Page(text=index_pages[acc])
        return Page(text='', status=404)
    monkeypatch.setattr('requests.Session.get', get)
    monkeypatch.setattr('src.sec_parser.time.sleep', lambda s: None)
    return accessions


def index_page(accepted_new_york):
    return CRWD_INDEX.replace('2026-10-08 20:00:07', accepted_new_york)


def test_feed_converted_when_three_index_pages_agree(monkeypatch):
    acc = fake_sec(monkeypatch, ['2026-10-09T04:00:07.000Z', '2024-06-04T00:10:00.000Z', '2020-06-02T01:00:00.000Z'],
                   {'0001778564-26-000179': CRWD_INDEX, '0001415889-24-017742': index_page('2024-06-03 16:10:00'),
                    '0000950103-20-024040': index_page('2020-06-01 17:00:00')})
    sec = SECParser()
    feed = sec.get_filings('CRWD')
    assert feed['calibration']['convention'] == 'utc_plus_ny_offset'
    newest = feed['filings'][0]
    assert newest['published_at'] == newest['acceptance_utc'] == '2026-10-09T00:00:07+00:00'
    assert newest['acceptance_label'] == '2026-10-09T04:00:07.000Z'
    assert "convention 'utc_plus_ny_offset' verified" in newest['published_at_basis'] and acc[2] in \
        newest['published_at_basis']
    stored = sec.db.events('CRWD', 'filing:4')
    assert {e['available_at'] for e in stored} >= {'2026-10-09T00:00:07+00:00'}
    # the index pages are immutable: a second parser reuses the stored pages
    sec2 = SECParser(db=sec.db)
    calls = []
    monkeypatch.setattr('requests.Session.get', lambda self, url, timeout=None: calls.append(url) or Page(status=500))
    assert sec2.label_calibration('0001535527', feed['raw'])['convention'] == 'utc_plus_ny_offset'
    assert calls == []


def test_disagreeing_or_missing_index_pages_keep_the_conservative_reading(monkeypatch):
    fake_sec(monkeypatch, ['2026-10-09T04:00:07.000Z', '2024-06-03T20:10:00.000Z', '2020-06-02T01:00:00.000Z'],
             {'0001778564-26-000179': CRWD_INDEX, '0001415889-24-017742': index_page('2024-06-03 16:10:00')})
    feed = SECParser().get_filings('CRWD')
    cal = feed['calibration']
    assert cal['convention'] is None and 'index page not read for 0000950103-20-024040' in cal['reason']
    newest = feed['filings'][0]
    assert newest['acceptance_utc'] is None
    assert newest['published_at'] == acceptance_to_utc('2026-10-09T04:00:07.000Z') == '2026-10-09T08:00:07+00:00'
    assert newest['published_at_basis'].startswith('SEC acceptanceDateTime read as New York time')


@pytest.mark.parametrize('labels', [['2026-10-09T04:00:07.000Z', '2024-06-03T20:10:00.000Z',
                                     '2020-06-02T01:00:00.000Z']])
def test_mixed_conventions_are_not_converted(monkeypatch, labels):
    fake_sec(monkeypatch, labels, {'0001778564-26-000179': CRWD_INDEX,
                                   '0001415889-24-017742': index_page('2024-06-03 16:10:00'),
                                   '0000950103-20-024040': index_page('2020-06-01 21:00:00')})
    cal = SECParser().get_filings('CRWD')['calibration']
    assert cal['convention'] is None and cal['reason'].startswith('conventions differ')


# ---------------------------------------------------------------- redundant versions (dedupe) and the audit

def store(db, rows, retrieved, legacy=False):
    """legacy=True: insert as the code before P0 (2026-10-12) did, without the redundancy check at insertion."""
    fetch = dict(db.record_fetch('SEC EDGAR', f'test:{retrieved}', status='OK'), retrieved_at=retrieved)
    if not legacy:
        return db.upsert_observations(fetch, rows)
    with db.connect() as conn:
        for r in rows:
            conn.execute('INSERT INTO observations (source, source_rank, entity, metric, as_of_date, value, value_text, '
                         'unit, published_at, published_at_basis, value_revisable, retrieved_at, fetch_id) '
                         'VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)',
                         ('SEC EDGAR', r['entity'], r['metric'], r['as_of_date'], r.get('value'), r.get('value_text'),
                          r.get('unit'), r['published_at'], r['published_at_basis'], retrieved, fetch['fetch_id']))
    return len(rows)


def fact(metric, value, published, as_of='2026-06-30', **kw):
    return {'entity': 'AAA', 'metric': metric, 'as_of_date': as_of, 'value': value, 'published_at': published,
            'published_at_basis': 'test', **kw}


def test_redundant_versions_only_when_the_earlier_version_dominates():
    from src.database import Database
    db = Database()
    # re-stored later with a later label (old SEC behaviour): redundant
    store(db, [fact('xbrl:Revenues', 100.0, '2026-08-01T00:00:00+00:00')], '2026-08-02T00:00:00+00:00')
    later = [fact('xbrl:Revenues', 100.0, '2026-08-01T04:00:00+00:00')]
    assert store(db, later, '2026-10-11T00:00:00+00:00') == 0              # P0: no longer stored
    store(db, later, '2026-10-11T00:00:00+00:00', legacy=True)            # as stored by earlier code
    # calibrated (earlier) time retrieved later: neither dominates, both kept
    store(db, [fact('xbrl:Assets', 5.0, '2026-08-01T04:00:00+00:00')], '2026-08-02T00:00:00+00:00')
    store(db, [fact('xbrl:Assets', 5.0, '2026-08-01T00:00:00+00:00')], '2026-10-11T00:00:00+00:00')
    # A, B, A: the last A restores a value, it is not redundant
    for i, v in enumerate((1.0, 2.0, 1.0)):
        store(db, [fact('xbrl:Debt', v, f'2026-08-0{i + 1}T00:00:00+00:00')], f'2026-08-0{i + 1}T01:00:00+00:00')
    # same value, other unit: kept
    store(db, [fact('xbrl:Cash', 7.0, '2026-08-01T00:00:00+00:00', unit='USD')], '2026-08-02T00:00:00+00:00')
    store(db, [fact('xbrl:Cash', 7.0, '2026-08-02T00:00:00+00:00', unit='EUR')], '2026-08-03T00:00:00+00:00')
    # an event seen again later: redundant
    event = {'entity': 'AAA', 'metric': 'filing:4', 'as_of_date': '2026-08-01', 'value_text': '0001-26-000001',
             'published_at_basis': 'test'}
    store(db, [dict(event, published_at='2026-08-01T20:00:00+00:00')], '2026-08-02T00:00:00+00:00')
    assert store(db, [dict(event, published_at='2026-08-02T00:00:00+00:00')], '2026-08-03T00:00:00+00:00') == 0
    store(db, [dict(event, published_at='2026-08-02T00:00:00+00:00')], '2026-08-03T00:00:00+00:00', legacy=True)

    redundant = db.redundant_versions()
    with db.connect() as conn:
        metrics = sorted(r[0] for r in conn.execute(f"SELECT metric FROM observations WHERE obs_id IN "
                                                    f"({','.join(str(i) for i, _ in redundant)})"))
    assert metrics == ['filing:4', 'xbrl:Revenues']

    probes = ['2026-08-01T02:00:00+00:00', '2026-08-02T12:00:00+00:00', '2026-10-12T00:00:00+00:00']
    before = {(m, t, s): [(d, r['value']) for d, r in db.series('AAA', m, known_at=t, strict_vintage=s)]
              for m in ('xbrl:Revenues', 'xbrl:Assets', 'xbrl:Debt') for t in probes for s in (False, True)}
    out = db.remove_redundant_versions()
    assert out['removed'] == 2 and out['by_source'] == {'SEC EDGAR': 2} and Path(out['backup']).exists()
    after = {(m, t, s): [(d, r['value']) for d, r in db.series('AAA', m, known_at=t, strict_vintage=s)]
             for m in ('xbrl:Revenues', 'xbrl:Assets', 'xbrl:Debt') for t in probes for s in (False, True)}
    assert after == before
    assert db.events('AAA', 'filing:4')[0]['available_at'] == '2026-08-01T20:00:00+00:00'
    assert db.redundant_versions() == [] and db.remove_redundant_versions()['removed'] == 0


def five_filing_feed(monkeypatch, sampled_accepted):
    """Five CRWD-like Form 4 labelled UTC + 4 h; calibration reads filings 0, 2, 4, the audit samples 1 and 3."""
    monkeypatch.setenv('SEC_USER_AGENT', 'TestAgent test@example.com')
    accessions = [f'0001778564-26-00010{i}' for i in range(5)]
    accepted = ['2026-10-08 20:00:07', '2026-09-08 16:10:00', '2026-08-03 17:00:00', '2026-07-01 18:00:00',
                '2026-06-01 15:00:00']
    # label = true UTC + 4 h (EDT) = New York wall clock + 8 h
    labels = ['2026-10-09T04:00:07.000Z', '2026-09-09T00:10:00.000Z', '2026-08-04T01:00:00.000Z',
              '2026-07-02T02:00:00.000Z', '2026-06-01T23:00:00.000Z']
    pages = {a: index_page(accepted[i]) for i, a in enumerate(accessions)}
    pages.update({accessions[i]: index_page(v) for i, v in sampled_accepted.items()})
    feed = {'filings': {'recent': {'form': ['4'] * 5, 'filingDate': [x[:10] for x in accepted],
                                   'reportDate': [''] * 5, 'accessionNumber': accessions,
                                   'acceptanceDateTime': labels, 'primaryDocument': ['a.xml'] * 5}}}

    def get(self, url, timeout=None):
        if url.endswith('company_tickers.json'):
            return Page(payload={'0': {'cik_str': 1535527, 'ticker': 'CRWD', 'title': 'CrowdStrike'}})
        if url.endswith('CIK0001535527.json'):
            return Page(payload=feed)
        acc = next((a for a in accessions if url.endswith(f'{a}-index.htm')), None)
        return Page(text=pages[acc]) if acc else Page(text='', status=404)
    monkeypatch.setattr('requests.Session.get', get)
    monkeypatch.setattr('src.sec_parser.time.sleep', lambda s: None)


def audit_labels(monkeypatch, sampled_accepted):
    from src.pipeline_audit import PipelineAudit
    five_filing_feed(monkeypatch, sampled_accepted)
    audit = PipelineAudit()
    feed = audit.sec.get_filings('CRWD')
    assert feed['calibration']['convention'] == 'utc_plus_ny_offset'
    return audit.label_checks('CRWD')[0]


def test_audit_label_check_passes_when_sampled_filings_match(monkeypatch):
    c = audit_labels(monkeypatch, {})
    assert c['status'] == 'PASS' and '2 sampled filing(s) equal to the EDGAR index page' in c['detail']


def test_audit_label_check_fails_when_a_sampled_filing_breaks_the_convention(monkeypatch):
    # filing 3 was really accepted 4 h later than its label implies: the converted time would be early
    c = audit_labels(monkeypatch, {3: '2026-07-01 22:00:00'})
    assert c['status'] == 'FAIL' and '1 filing(s) dated before acceptance' in c['detail']
