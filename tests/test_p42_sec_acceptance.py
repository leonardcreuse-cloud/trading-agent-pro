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
