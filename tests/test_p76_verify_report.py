"""
Gap round G6: verification of an archived report against its sources (synthetic report and stub sources).
"""

import json


def report(tmp_path):
    payload = {'time_model': {'s0': '2026-10-09', 'cutoff': '2026-10-10T05:00:00+00:00'}, 'code_version': 'x',
               'sections': [
                   {'name': 'macro', 'tables': [{'title': 'Macro indicators as known at T_p and at T_c (FRED vintages)',
                                                 'columns': ['series', 'value as known at T_c', 'obs (T_c)'],
                                                 'rows': [['DGS10', 4.1, '2026-10-08'], ['UNRATE', 4.3, '2026-09'],
                                                          ['CPIAUCSL', 3.0, '2026-09']]}]},
                   {'name': 'sec_events', 'tables': [{'title': 'AAA: every SEC filing available in the window',
                                                      'columns': ['accepted (UTC)', 'form', 'accession'],
                                                      'rows': [['2026-10-06T00:00:11+00:00', '4', '0000000001-26-000001']]}]},
                   {'name': 'market', 'tables': [{'title': 'AAA — session timeline',
                                                  'columns': ['session', 'close_raw (USD)'],
                                                  'rows': [['2026-10-08', 10.0], ['2026-10-09', 11.0]]}]},
                   {'name': 'valuation', 'tables': [{'title': 'AAA: company guidance, quoted from its earnings release',
                                                     'note': 'Source: https://www.sec.gov/Archives/x/ex991.htm. Forward',
                                                     'rows': [['Financial Outlook'], ['Revenue of $10 million']]}]}]}
    path = tmp_path / 'weekly_v3.json'
    path.write_text(json.dumps(payload))
    return path


class Sec:
    last_error = None

    def get_cik(self, t):
        return '0000000001'

    def _get(self, url, as_json=False, max_age=None):
        if url.endswith('-index.htm'):
            return '<div class="infoHead">Accepted</div><div class="info">2026-10-05 20:00:11</div>'
        return '<p>Financial Outlook</p><p>Revenue of $12 million</p>'


def fetch(db, source, url, params=None, raw=None, **kw):
    if 'stlouisfed' in url:
        values = {'DGS10': '4.10', 'UNRATE': '4.4'}
        sid = params['series_id']
        assert params['realtime_start'] == params['realtime_end'] == '2026-10-09'      # last vintage admissible at T_c
        obs = params['observation_start']
        return {'status': 'OK', 'content': json.dumps({'observations': [{'date': obs, 'value': values[sid]}]}),
                'reason': None}
    return {'status': 'OK', 'content': json.dumps({'data': [{'date': '2026-10-08', 'close': 10.0},
                                                            {'date': '2026-10-09', 'close': 11.2}]}), 'reason': None}


def test_matches_and_mismatches_are_reported(tmp_path, monkeypatch):
    from src.database import Database
    from src.verify_report import verify
    monkeypatch.setenv('FRED_API_KEY', 'abcdef0123456789abcdef0123456789')
    out = verify(report(tmp_path), db=Database(), sec=Sec(), http_fetch=fetch)
    by = {(c['kind'], c['claim'][:20]): c['status'] for c in out['checks']}
    assert out['summary']['FRED'] == {'MATCH': 1, 'MISMATCH': 1, 'UNVERIFIABLE': 0}     # CPI YoY is derived: skipped
    assert out['summary']['SEC'] == {'MATCH': 1, 'MISMATCH': 0, 'UNVERIFIABLE': 0}      # 20:00:11 EDT = 00:00:11 UTC
    assert out['summary']['price'] == {'MATCH': 1, 'MISMATCH': 1, 'UNVERIFIABLE': 0}    # 11.0 vs 11.2: 1.8 %
    assert out['summary']['guidance'] == {'MATCH': 1, 'MISMATCH': 1, 'UNVERIFIABLE': 0}
    assert out['mismatches'] == 3 and json.loads(open(out['path']).read())['mismatches'] == 3
    assert by[('FRED', 'UNRATE = 4.3 for 202')] == 'MISMATCH'


def test_unreachable_sources_are_unverifiable_not_matches(tmp_path, monkeypatch):
    from src.database import Database
    from src.verify_report import verify
    monkeypatch.delenv('FRED_API_KEY', raising=False)

    def refused(db, source, url, **kw):
        return {'status': 'DATA UNAVAILABLE', 'content': None, 'reason': 'ProxyError (host refused)'}
    out = verify(report(tmp_path), db=Database(), sec=Sec(), http_fetch=refused)
    assert out['summary']['FRED']['UNVERIFIABLE'] == 2 and out['summary']['price']['UNVERIFIABLE'] == 2
    assert out['mismatches'] == 1                                         # only the guidance quote (stub exhibit)
