"""
P4.0 external sources: parsing of real payload excerpts (tests/fixtures/external, retrieved 2026-10-11),
publication bounds, provenance and DATA UNAVAILABLE on refused hosts. Offline (conftest blocks HTTP).
The FINRA, CFTC and Federal Register records below are copied from real API responses of 2026-10-11.
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src import external_sources as ex
from src.common import DATA_UNAVAILABLE
from src.database import Database

FIX = Path(__file__).parent / 'fixtures' / 'external'


class Resp:
    def __init__(self, text=None, status=200, content=None, headers=None):
        self.text, self.status_code = text, status
        self.content = content if content is not None else (text or '').encode()
        self.headers = headers or {}


class FakeHTTP:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


# ------------------------------------------------------------------ publication bounds

def test_cot_release_is_friday_1530_new_york_and_moves_after_holidays():
    assert ex.cot_release(date(2026, 10, 6)) == '2026-10-09T19:30:00+00:00'      # EDT
    # Thanksgiving (Thursday 2026-11-26) week: next business day after Friday, 15:30 EST
    assert ex.cot_release(date(2026, 11, 24)) == '2026-11-30T20:30:00+00:00'


def test_finra_dissemination_is_seven_business_days_end_of_day():
    assert ex.finra_dissemination(date(2026, 9, 30)) == '2026-10-10T05:00:00+00:00'
    # Columbus Day 2026-10-12 is skipped: 10-15 + 7 business days = 10-26
    assert ex.finra_dissemination(date(2026, 10, 15)) == '2026-10-27T05:00:00+00:00'


# ------------------------------------------------------------------ parsers on real excerpts

def test_cot_rows_net_positions_from_real_records():
    tff = [{'cftc_contract_market_code': '13874A', 'report_date_as_yyyy_mm_dd': '2026-10-06T00:00:00.000',
            'open_interest_all': '1932227', 'lev_money_positions_long': '113223',
            'lev_money_positions_short': '528310'}]
    rows = {r['metric']: r for r in ex.cot_rows(tff, 'tff')}
    assert rows['open_interest']['value'] == 1932227
    assert rows['leveraged_funds_net']['value'] == 113223 - 528310
    assert 'asset_managers_net' not in rows          # missing fields -> no value, never 0
    assert rows['open_interest']['published_at'] == '2026-10-09T19:30:00+00:00'
    dis = [{'cftc_contract_market_code': '067651', 'report_date_as_yyyy_mm_dd': '2026-10-06T00:00:00.000',
            'open_interest_all': '1889422', 'm_money_positions_long_all': '178353',
            'm_money_positions_short_all': '124755'}]
    assert {r['metric']: r['value'] for r in ex.cot_rows(dis, 'disaggregated')}['managed_money_net'] == 53598
    assert ex.cot_rows([{**tff[0], 'cftc_contract_market_code': '43874Q'}], 'tff') == []


def test_finra_rows_from_real_record():
    rec = {'stockSplitFlag': None, 'previousShortPositionQuantity': 27929552, 'averageDailyVolumeQuantity': 10727968,
           'issueName': 'CrowdStrike Holdings, Inc. Cla', 'currentShortPositionQuantity': 26196357,
           'changePreviousNumber': -1733195, 'accountingYearMonthNumber': 20260930, 'settlementDate': '2026-09-30',
           'marketClassCode': 'NNM', 'symbolCode': 'CRWD', 'daysToCoverQuantity': 2.44,
           'issuerServicesGroupExchangeCode': 'R', 'revisionFlag': None, 'changePercent': -6.21}
    rows = {r['metric']: r for r in ex.finra_rows('CRWD', [rec])}
    assert rows['short_interest_shares']['value'] == 26196357
    assert rows['short_interest_days_to_cover']['value'] == 2.44
    assert rows['short_interest_shares']['published_at'] == '2026-10-10T05:00:00+00:00'
    revised = {r['metric']: r for r in ex.finra_rows('CRWD', [{**rec, 'revisionFlag': 'R'}])}
    assert revised['short_interest_shares']['published_at'] is None
    assert ex.finra_rows('NET', [rec]) == []


def test_cboe_daily_page_excerpt():
    day, ratios = ex.parse_cboe_daily((FIX / 'cboe_daily_2026-10-09_excerpt.html').read_text())
    assert day == '2026-10-09'
    assert ratios['put_call_total'] == 0.82 and ratios['put_call_equity'] == 0.56
    assert ratios['put_call_index'] == 1.13 and ratios['put_call_spx'] == 1.24


def test_fomc_calendar_excerpt():
    last, meetings = ex.parse_fomc((FIX / 'fomc_calendar_excerpt.html').read_text())
    assert last == date(2026, 10, 7)
    by_end = {m['end']: m for m in meetings}
    assert len(meetings) == 8
    assert by_end['2026-01-28']['start'] == '2026-01-27' and not by_end['2026-01-28']['sep']
    assert by_end['2026-03-18']['sep'] and by_end['2026-12-09']['sep']
    assert '2026-10-28' in by_end


def test_bls_schedule_excerpt():
    rows = ex.parse_bls_schedule((FIX / 'bls_empsit_schedule_excerpt.html').read_text())
    assert rows[0] == {'reference': 'October 2026', 'date': '2026-11-06', 'time': '08:30 AM'}
    assert all(r['time'].endswith('AM') for r in rows)


def test_bls_month_calendar_excerpt():
    rows = ex.parse_bls_month((FIX / 'bls_month_2026-10_excerpt.html').read_text(), 2026, 10)
    assert {'release': 'Consumer Price Index', 'reference': 'September 2026', 'date': '2026-10-14',
            'time': '08:30 AM'} in rows                       # missing from the per-release page on 2026-10-11
    assert {'release': 'Producer Price Index', 'reference': 'September 2026', 'date': '2026-10-15',
            'time': '08:30 AM'} in rows
    jolts = [r for r in rows if r['release'] == 'Job Openings and Labor Turnover Survey']
    assert jolts == [{'release': 'Job Openings and Labor Turnover Survey', 'reference': 'August 2026',
                      'date': '2026-09-29', 'time': '10:00 AM'}]     # adjacent-month cell
    assert 'Columbus Day' in {r['release'] for r in rows}             # holiday: not a declared release
    # constructed cell (logic test): December days on a January page belong to the previous year
    cell = ('<td class="other-month" id="d1229"><p class="day">29</p><p><strong>Employment Situation<br>'
            '</strong>November 2026<br>08:30 AM</p></td>')
    assert ex.parse_bls_month(cell, 2027, 1)[0]['date'] == '2026-12-29'


def test_collect_bls_adds_the_current_month_once(monkeypatch):
    pages = {'news_release': (FIX / 'bls_empsit_schedule_excerpt.html').read_text(),
             'sched': (FIX / 'bls_month_2026-10_excerpt.html').read_text()}

    class Router(FakeHTTP):
        def get(self, url, **kw):
            self.calls.append((url, kw))
            return Resp(pages['news_release'] if '/news_release/' in url else pages['sched'])
    fake = Router(None)
    monkeypatch.setattr(ex, 'requests', fake)
    monkeypatch.setattr(ex, '_throttle', lambda url: None)
    db = Database()
    res = ex.collect_bls(db, today=date(2026, 10, 11))
    assert res['status'] == 'OK'
    assert [u for u, _ in fake.calls if '_sched' in u] == ['https://www.bls.gov/schedule/2026/10_sched.htm',
                                                           'https://www.bls.gov/schedule/2026/11_sched.htm']
    cpi = [json.loads(e['value_text']) for e in db.events('BLS:cpi', 'release')]
    assert {'reference': 'September 2026', 'date': '2026-10-14', 'time': '08:30 AM',
            'release': 'Consumer Price Index'} in cpi
    assert len([e for e in cpi if e['date'] == '2026-10-14']) == 1
    assert ex.collect_bls(db, today=date(2026, 10, 11))['stored'] == 0     # same schedule: nothing new


def test_collect_earnings_calendars_snapshot(monkeypatch):
    """Live yfinance answer of 2026-10-11 for NET (values copied); an empty answer is unavailable."""
    import yfinance
    answers = {'NET': {'Earnings Date': [date(2026, 10, 29)], 'Earnings High': 0.37, 'Earnings Low': 0.33541,
                       'Earnings Average': 0.34308}, 'MP': {}}
    monkeypatch.setattr(yfinance, 'Ticker', lambda t: type('T', (), {'calendar': answers[t]})())
    db = Database()
    res = ex.collect_earnings_calendars(db, ['NET', 'MP'])
    assert res['status'] == DATA_UNAVAILABLE and res['stored'] == 1 and 'MP: empty calendar' in res['reason']
    (row,) = db.events('NET', 'earnings_date_reported')
    assert row['as_of_date'] == '2026-10-29'
    fetch = db.latest_fetch('yfinance', 'yfinance.Ticker(NET).calendar')
    assert ex.earnings_dates(json.loads(db.read_raw(fetch['fetch_id']))) == ['2026-10-29']
    assert ex.collect_earnings_calendars(db, ['NET'])['stored'] == 0          # same snapshot: no new row


def test_gdelt_aggregates_on_real_lines():
    agg = ex.gdelt_aggregates((FIX / 'gdelt_20261009_excerpt.tsv').read_text())
    g = agg['GDELT:global']
    assert g['events'] == 8 and g['root_events'] == 3
    assert g['material_conflict_root'] == 1 and g['verbal_conflict_root'] == 1
    assert g['goldstein_mean_root'] == pytest.approx((-2.0 - 5.0 + 4.0) / 3)
    assert agg['GDELT:USA-CHN']['events'] == 3 and agg['GDELT:USA-CHN']['root_events'] == 0
    assert agg['GDELT:USA-CHN']['goldstein_mean_root'] is None


def test_federal_register_rows_use_publication_morning():
    rows = ex.fr_rows('FR:foreign-assets-control-office', [
        {'publication_date': '2026-10-08', 'type': 'Notice', 'document_number': '2026-20683',
         'title': 'Notice of OFAC Sanctions Actions', 'agencies': [{'name': 'Foreign Assets Control Office'}]}])
    assert rows[0]['published_at'] == '2026-10-08T10:00:00+00:00'
    assert json.loads(rows[0]['value_text'])['document_number'] == '2026-20683'


def test_gpr_rows_from_real_values(monkeypatch):
    frame = pd.DataFrame({'date': pd.to_datetime(['2026-10-03', '2026-10-04', '2026-10-05']),
                          'GPRD': [160.736404, 145.607376, 141.491577],
                          'GPRD_ACT': [264.747070, 163.304077, 165.948303],
                          'GPRD_THREAT': [116.223793, 151.346359, 166.100739]})
    monkeypatch.setattr(pd, 'read_excel', lambda *_a, **_k: frame)
    rows = ex.gpr_rows(b'', '2026-10-05T13:42:20+00:00', date(2026, 10, 4))
    assert {r['as_of_date'] for r in rows} == {'2026-10-04', '2026-10-05'}
    assert all(r['published_at'] == '2026-10-05T13:42:20+00:00' for r in rows)


def test_option_snapshot_logic():
    """Logic test on constructed chains (not market data): ATM selection and quality filter."""
    def chain(iv_call, iv_put, bid=1.0):
        calls = pd.DataFrame({'strike': [90, 100, 110], 'bid': [bid] * 3, 'ask': [bid + .2] * 3,
                              'impliedVolatility': [iv_call] * 3, 'openInterest': [10, 20, 30],
                              'volume': [1, 2, 3]})
        puts = calls.assign(impliedVolatility=iv_put, openInterest=[5, 5, 5], volume=[3, 3, 3])
        return calls, puts
    c1, p1 = chain(0.5, 0.6)
    c2, p2 = chain(0.4, 0.5)
    snap = ex.option_snapshot([('e1', c1, p1), ('e2', c2, p2)], 101.0, {'e1': 5, 'e2': 33})
    assert snap['expiry'] == 'e2' and snap['atm_iv'] == pytest.approx(0.45)
    assert snap['put_call_oi'] == pytest.approx(30 / 120)
    no_quotes = ex.option_snapshot([('e2', *chain(0.4, 0.5, bid=0.0))], 101.0, {'e2': 33})
    assert no_quotes['atm_iv'] is None
    calls, puts = chain(0.4, 0.5)
    no_put_oi = ex.option_snapshot([('e2', calls, puts.assign(openInterest=float('nan')))], 101.0, {'e2': 33})
    assert no_put_oi['put_call_oi'] is None                       # missing side: not a ratio of 0
    assert no_put_oi['quotes_missing_open_interest'] == 3 and no_put_oi['put_call_volume'] == pytest.approx(9 / 6)


# ------------------------------------------------------------------ provenance and failures

def test_refused_host_is_logged_unavailable(tmp_path):
    db = Database()

    class Refused:
        def get(self, *a, **k):
            raise ConnectionError('CONNECT tunnel failed, response 403')
    got = ex.http_fetch(db, 'CFTC', 'https://publicreporting.cftc.gov/resource/x.json', session=Refused())
    assert got['status'] == DATA_UNAVAILABLE and 'network policy' in got['reason']
    assert db.get_fetch(got['fetch']['fetch_id'])['status'] == DATA_UNAVAILABLE


def test_dropped_connection_is_retried_once_but_not_a_proxy_refusal(monkeypatch):
    import requests
    monkeypatch.setattr(ex, 'RETRY_PAUSE', 0)
    monkeypatch.setattr(ex, '_throttle', lambda url: None)
    db = Database()

    class Flaky:
        def __init__(self, error):
            self.error, self.calls = error, 0

        def get(self, *a, **k):
            self.calls += 1
            if self.calls == 1 or isinstance(self.error, requests.exceptions.ProxyError):
                raise self.error
            return Resp('{}')
    reset = Flaky(requests.exceptions.ConnectionError("('Connection aborted.', ConnectionResetError(104))"))
    assert ex.http_fetch(db, 'EIA', 'https://api.eia.gov/v2/x', session=reset)['status'] == 'OK'
    assert reset.calls == 2
    proxy = Flaky(requests.exceptions.ProxyError('Tunnel connection failed: 403 Forbidden'))
    got = ex.http_fetch(db, 'EIA', 'https://api.eia.gov/v2/x', session=proxy)
    assert got['status'] == DATA_UNAVAILABLE and proxy.calls == 1 and 'network policy' in got['reason']


def test_rate_limit_is_waited_out_then_reported(monkeypatch):
    """Live 2026-10-13: the Cboe CDN answered HTTP 429 to part of the 40 tickers; a 429 is retried after a pause
    (the server's Retry-After when given), and still reported DATA UNAVAILABLE when it persists."""
    waits = []
    monkeypatch.setattr(ex.time, 'sleep', waits.append)
    monkeypatch.setattr(ex, '_throttle', lambda url: None)
    db = Database()

    class Limited:
        def __init__(self, n_429, headers=None):
            self.n_429, self.headers, self.calls = n_429, headers or {}, 0

        def get(self, *a, **k):
            self.calls += 1
            return Resp('', status=429, headers=self.headers) if self.calls <= self.n_429 else Resp('{}')
    once = Limited(1, {'Retry-After': '7'})
    assert ex.http_fetch(db, 'Cboe', 'https://cdn.cboe.com/x.json', session=once)['status'] == 'OK'
    assert once.calls == 2 and waits == [7.0]
    waits.clear()
    always = Limited(99)
    got = ex.http_fetch(db, 'Cboe', 'https://cdn.cboe.com/x.json', session=always)
    assert got['status'] == DATA_UNAVAILABLE and 'HTTP 429' in got['reason']
    assert always.calls == 1 + len(ex.RATE_LIMIT_PAUSES) and waits == list(ex.RATE_LIMIT_PAUSES)


def test_unchanged_values_keep_their_stored_publication():
    """Live 2026-10-11: the same GPR file came with two Last-Modified values, and Federal Register documents
    dated in the future were clamped to each retrieval; neither may create a new version."""
    db = Database()
    gpr = lambda pub, v: [{'entity': 'GPR', 'metric': 'gpr_daily', 'as_of_date': '2026-10-05', 'value': v,
                           'published_at': pub, 'published_at_basis': 'HTTP Last-Modified'}]
    first = db.record_fetch(ex.GPR_SOURCE, 'gpr', status='OK')
    assert db.upsert_observations(first, gpr('2026-10-05T13:43:09+00:00', 141.491577)) == 1
    again = db.record_fetch(ex.GPR_SOURCE, 'gpr', status='OK')
    rows = ex.keep_stored_publication(db, ex.GPR_SOURCE, gpr('2026-10-05T13:42:20+00:00', 141.491577))
    assert rows[0]['published_at'] == '2026-10-05T13:43:09+00:00'
    assert db.upsert_observations(again, rows) == 0
    revised = ex.keep_stored_publication(db, ex.GPR_SOURCE, gpr('2026-10-06T13:00:00+00:00', 142.0))
    assert revised[0]['published_at'] == '2026-10-06T13:00:00+00:00'      # a new value keeps its own date

    doc = [{'publication_date': '2099-01-02', 'document_number': '2099-00001', 'title': 'Future notice'}]
    f1 = db.record_fetch(ex.FR_SOURCE, 'fr', status='OK')
    assert db.upsert_observations(f1, ex.keep_stored_publication(db, ex.FR_SOURCE, ex.fr_rows('FR:x', doc))) == 1
    f2 = db.record_fetch(ex.FR_SOURCE, 'fr', status='OK')
    assert db.upsert_observations(f2, ex.keep_stored_publication(db, ex.FR_SOURCE, ex.fr_rows('FR:x', doc))) == 0
    other = [{**doc[0], 'document_number': '2099-00002'}]                  # same day, another document: stored
    assert db.upsert_observations(f2, ex.keep_stored_publication(db, ex.FR_SOURCE, ex.fr_rows('FR:x', other))) == 1


def test_collect_cboe_stores_excerpt_and_values(monkeypatch):
    db = Database()
    html = (FIX / 'cboe_daily_2026-10-09_excerpt.html').read_text()
    fake = FakeHTTP(Resp(html))
    monkeypatch.setattr(ex, 'requests', fake)
    monkeypatch.setattr(ex, '_throttle', lambda url: None)
    res = ex.collect_cboe(db, [date(2026, 10, 9), date(2026, 10, 8)])
    assert res['status'] == 'OK'
    rows = dict(db.series('CBOE', 'put_call_total', source='Cboe'))
    assert list(rows) == ['2026-10-09']           # the 10-08 request returned the 10-09 page: not stored as 10-08
    assert rows['2026-10-09']['value'] == 0.82
    assert rows['2026-10-09']['published_at'] == '2026-10-10T05:00:00+00:00'
    raw = json.loads(db.read_raw(rows['2026-10-09']['fetch_id']))
    assert raw['ratios']['put_call_total'] == 0.82


def test_collect_all_reports_every_source_without_raising(monkeypatch):
    db = Database()

    class Refused:
        def get(self, *a, **k):
            raise ConnectionError('CONNECT tunnel failed, response 403')
        post = get
    monkeypatch.setattr(ex, 'requests', Refused())
    monkeypatch.setattr(ex, '_throttle', lambda url: None)
    monkeypatch.setattr(ex, 'collect_options', lambda db, t: ex._result('options_snapshot', DATA_UNAVAILABLE, 0, 'x'))
    monkeypatch.setattr(ex, 'collect_earnings_calendars',
                        lambda db, t: ex._result('earnings_calendar', DATA_UNAVAILABLE, 0, 'x'))
    results = ex.collect_all(db, tickers=['CRWD'], today=date(2026, 10, 11))
    assert [r['collector'] for r in results] == ['cftc_cot', 'finra_short_interest', 'cboe_put_call',
                                                 'fed_fomc_calendar', 'bls_schedules', 'bls_api', 'bea_nipa',
                                                 'eia_energy', 'federal_register', 'gpr_index', 'gdelt_events',
                                                 'fred_release_calendars', 'options_snapshot', 'earnings_calendar',
                                                 'cboe_price_history']
    assert all(r['status'] == DATA_UNAVAILABLE and r['stored'] == 0 for r in results)


def test_daily_fred_calendars_are_read_back_by_the_catalysts_section(monkeypatch):
    from types import SimpleNamespace
    from src.weekly.sections import catalysts
    from tests.conftest import FakeResponse
    monkeypatch.setenv('FRED_API_KEY', 'testkey-abcdef123')
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse({'release_dates': [{'release_id': params['release_id'], 'date': '2026-10-14'}]})
    monkeypatch.setattr('requests.get', get)
    db = Database()
    res = ex.collect_fred_calendars(db, date(2026, 10, 9))
    assert res['status'] == 'OK' and res['stored'] == len(catalysts.RELEASES) == len(calls)
    assert all(c['realtime_start'] == '2026-10-09' and c['api_key'] == 'testkey-abcdef123' for c in calls)
    ctx = SimpleNamespace(db=db)
    found = catalysts.stored_calendar(ctx, 10, '2099-01-01T00:00:00+00:00', '2026-10-10')
    assert found['dates'] == ['2026-10-14'] and found['realtime_start'] == '2026-10-09'
    with db.connect() as conn:
        assert 'testkey' not in json.dumps([dict(r) for r in conn.execute('SELECT * FROM source_fetches')])
