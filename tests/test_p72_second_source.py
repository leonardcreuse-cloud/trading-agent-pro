"""
Gap round G2: Cboe delayed daily history as a second price source (synthetic payloads, logic only).
"""

import json


def payload(rows):
    return {'symbol': 'AAA', 'timestamp': '2026-10-10 00:00:00',
            'data': [{'date': d, 'open': c, 'high': c, 'low': c, 'close': c, 'volume': v} for d, c, v in rows]}


def test_rows_skip_malformed_values_and_respect_the_start():
    from src.external_sources import CBOE_HISTORY_BASIS, cboe_history_rows
    rows = cboe_history_rows('AAA', payload([('2026-10-07', 10.0, 100), ('2026-10-08', None, 0),
                                             ('2026-10-09', 11.0, 120), ('2026-09-01', 9.0, 90)]), '2026-10-01')
    assert [(r['as_of_date'], r['metric'], r['value']) for r in rows] == [
        ('2026-10-07', 'close', 10.0), ('2026-10-07', 'volume', 100.0), ('2026-10-09', 'close', 11.0),
        ('2026-10-09', 'volume', 120.0)]                                   # missing close and zero volume skipped
    assert rows[0]['published_at'] == '2026-10-08T05:00:00+00:00' and rows[0]['value_revisable'] == 1
    assert rows[0]['published_at_basis'] == CBOE_HISTORY_BASIS


def test_collector_stores_once_and_reports_failures(monkeypatch):
    from datetime import date
    from src import external_sources as ex
    from src.database import Database
    db = Database()
    served = {'AAA': payload([('2026-10-08', 10.0, 100), ('2026-10-09', 11.0, 120)]), 'BBB': None}

    def fake_fetch(db_, source, url, raw=None, **kw):
        t = url.rsplit('/', 1)[-1][:-5]
        if served[t] is None:
            return {'status': 'DATA UNAVAILABLE', 'reason': 'HTTP 404', 'fetch': None}
        stored = raw(json.dumps(served[t]))
        fetch = db_.record_fetch(source, url, status='OK', raw=stored)
        return {'status': 'OK', 'content': json.dumps(served[t]), 'fetch': fetch, 'reason': None}
    monkeypatch.setattr(ex, 'http_fetch', fake_fetch)
    first = ex.collect_cboe_history(db, ['AAA', 'BBB'], date(2026, 1, 1))
    assert first['stored'] == 4 and first['status'] == 'DATA UNAVAILABLE' and 'BBB: HTTP 404' in first['reason']
    again = ex.collect_cboe_history(db, ['AAA'], date(2026, 1, 1))
    assert again == {'collector': 'cboe_price_history', 'status': 'OK', 'stored': 0, 'reason': None}
    assert [d for d, _ in db.series('AAA', 'close', source=ex.CBOE_HISTORY_SOURCE)] == ['2026-10-08', '2026-10-09']


def test_implied_split_from_a_step_of_the_close_ratio():
    from src.valuation import implied_splits, split_explained
    yf = {'2026-06-25': 242.5, '2026-06-26': 243.5, '2026-06-29': 227.8, '2026-06-30': 223.9}
    cb = {'2026-06-25': 462.5, '2026-06-26': 464.4, '2026-06-29': 227.8, '2026-06-30': 223.9}
    implied = implied_splits(yf, cb, {'2026-06-29': 0.9535})
    assert list(implied) == ['2026-06-29'] and abs(implied['2026-06-29'] - 0.5) < 0.001
    assert implied_splits(yf, dict(yf)) == {}                                  # flat ratio: nothing implied
    X = {'shares_outstanding_change_pct': -50.1, 'shares_outstanding_prior_date': '2025-06-30',
         'shares_outstanding_date': '2026-06-30', 'shares_outstanding_published_at': '2026-07-23T13:41:52+00:00'}
    assert split_explained(X, {'2026-06-29': 0.9535}) is False and split_explained(X, implied) is True


def test_second_source_check(monkeypatch):
    from src.database import Database
    from src.external_sources import CBOE_HISTORY_SOURCE
    from src.pipeline_audit import PipelineAudit
    db = Database()
    days = ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09']
    yf = db.record_fetch('yfinance', 'test', status='OK')
    db.upsert_observations(yf, [{'entity': 'AAA', 'metric': 'close_raw', 'as_of_date': d, 'value': 10.0 + i,
                                 'unit': 'USD'} for i, d in enumerate(days)])
    cb = db.record_fetch(CBOE_HISTORY_SOURCE, 'test', status='OK')
    db.upsert_observations(cb, [{'entity': 'AAA', 'metric': 'close', 'as_of_date': d, 'value': 10.0 + i + (0.5 if
                                 d == '2026-10-07' else 0.0), 'unit': 'USD'} for i, d in enumerate(days) if d != '2026-10-08'])
    audit = PipelineAudit(db=db)
    monkeypatch.setattr(audit, '_yf_splits', lambda t: {})
    c = audit.second_source_check('AAA')
    assert c['status'] == 'WARN' and c['detail'].startswith('4 common sessions from 2026-10-05 to 2026-10-09: 1 differ')
    assert '1 yfinance-only, 0 Cboe-only' in c['detail']
    assert any(e.startswith('2026-10-07: yfinance 12 vs Cboe 12.5') for e in c['evidence'])
    assert '2026-10-08: yfinance only' in c['evidence']
    assert audit.second_source_check('ZZZ')['detail'].startswith('no stored yfinance closes')


def test_identifier_check_flags_a_reassigned_ticker():
    from src.database import Database
    from src.pipeline_audit import PipelineAudit
    db = Database()
    for cik in ('0000000001', '0000000002'):
        f = db.record_fetch('SEC EDGAR', f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json', status='OK')
        db.upsert_observations(f, [{'entity': 'AAA', 'metric': f'xbrl:Revenues:12M:{cik}', 'as_of_date': '2025-12-31',
                                    'value': 1.0, 'unit': 'USD'}])

    class Sec:
        SEC_API = 'https://data.sec.gov'

        def __init__(self, cik):
            self.cik = cik

        def get_cik(self, ticker):
            return self.cik

        def _get_json(self, url, max_age=None):
            return {'formerNames': [{'name': 'Old Name', 'from': '2015-01-01', 'to': '2099-01-01'}]}
    audit = PipelineAudit(db=db)
    audit.sec = Sec('0000000002')
    c = audit.identifier_check('AAA')
    assert c['status'] == 'WARN' and c['evidence'] == [
        'stored SEC data from CIK 0000000001, while the ticker now resolves to 0000000002']
    assert "formerly 'Old Name'" in c['detail']
    audit.sec = Sec(None)
    assert audit.identifier_check('AAA')['detail'].startswith('ticker not in the current SEC ticker file')
