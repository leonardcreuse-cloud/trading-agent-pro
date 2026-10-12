"""
Master mission, gap round G0: source registry and probe (offline; the HTTP session is a stub).
"""

import json

import requests


class Response:
    def __init__(self, status, body=b'{}'):
        self.status_code, self.content, self.text = status, body, body.decode()


class Session:
    def __init__(self, status=200, fail=False):
        self.status, self.fail, self.calls = status, fail, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        if self.fail:
            raise requests.exceptions.ProxyError('403 CONNECT refused')
        return Response(self.status, b'{"ok": 1}')


def test_registry_entries_are_complete():
    from src.source_registry import REGISTRY
    names = [e['name'] for e in REGISTRY]
    assert len(names) == len(set(names))
    for e in REGISTRY:
        for field in ('name', 'rank', 'integrated', 'probe', 'auth', 'frequency', 'terms', 'rate_limit', 'used_for'):
            assert e.get(field) not in (None, ''), (e['name'], field)
        assert e['rank'] in (1, 2, 3)


def test_probe_reports_status_errors_and_never_a_key(monkeypatch):
    from src import source_registry as sr
    fred = next(e for e in sr.REGISTRY if e['name'].startswith('FRED'))
    monkeypatch.setenv('FRED_API_KEY', 'abcdef0123456789abcdef0123456789')
    ok = sr.probe(fred, Session(200))
    assert ok['http_status'] == 200 and ok['bytes'] == 9 and ok['error'] is None
    bad = sr.probe(fred, Session(404))
    assert bad['http_status'] == 404 and bad['error'].startswith('HTTP 404')
    down = sr.probe(fred, Session(fail=True))
    assert down['http_status'] is None and 'ProxyError' in down['error']
    monkeypatch.delenv('FRED_API_KEY')
    missing = sr.probe(fred, Session(200))
    assert missing['error'] == 'not probed: FRED_API_KEY not set'


def test_probe_mirrors_the_production_user_agent(monkeypatch):
    from src import source_registry as sr
    monkeypatch.setenv('SEC_USER_AGENT', 'Jane Doe jane@example.org')
    sec = next(e for e in sr.REGISTRY if e['name'].startswith('SEC EDGAR'))
    s = Session(200)
    sr.probe(sec, s)
    assert s.calls[0][1] == {'User-Agent': 'Jane Doe jane@example.org'}
    news = next(e for e in sr.REGISTRY if e['name'].startswith('NewsAPI'))
    monkeypatch.setenv('NEWSAPI_KEY', 'k' * 32)
    s = Session(200)
    sr.probe(news, s)
    assert s.calls[0][1] == {}                                   # requests' default, as news_processor


def test_run_writes_a_report_without_keys(monkeypatch):
    from src import source_registry as sr
    from src.common import reports_dir
    for name in ('FRED_API_KEY', 'BEA_API_KEY', 'EIA_API_KEY', 'NEWSAPI_KEY'):
        monkeypatch.setenv(name, 'abcdef0123456789abcdef0123456789')
    monkeypatch.setattr(sr, 'REGISTRY', [e for e in sr.REGISTRY if e.get('client') != 'yfinance'])
    report = sr.run(Session(200))
    text = (reports_dir() / 'source_check.json').read_text()
    assert 'abcdef0123456789' not in text
    saved = json.loads(text)
    assert saved['summary']['integrated_reachable'] == saved['summary']['integrated_total']
    assert report['summary']['alternatives_reachable']                   # the stub answers every host
