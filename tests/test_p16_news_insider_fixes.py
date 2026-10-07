"""Phase P1.6 - critic fixes: no neutral-50 news, fixed window, joint Form 4 filers (offline)."""

from tests.conftest import FakeResponse
from tests.test_p03_sec_fundamentals_insider import sec  # noqa: F401 - fixture


def test_articles_without_lexicon_words_are_ignored_not_50(monkeypatch):
    from src.news_processor import NewsProcessor
    monkeypatch.setenv('NEWSAPI_KEY', 'x')
    articles = [{'title': 'Cloudflare shares surge', 'description': '', 'publishedAt': '2026-10-01T10:00:00Z'},
                {'title': 'Cloudflare to present at conference', 'description': '', 'publishedAt': '2026-10-02T10:00:00Z'},
                {'title': 'Cloudflare quarterly update', 'description': '', 'publishedAt': '2026-10-03T10:00:00Z'}]
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen.update(params)
        return FakeResponse({'articles': articles, 'totalResults': 30})
    monkeypatch.setattr('src.news_processor.requests.get', fake_get)
    r = NewsProcessor().analyze('NET')
    assert r['scored_articles_count'] == 1 and r['avg_sentiment'] == 53      # one 'surge', two unscored
    assert r['partial_coverage'] is True and r['coverage'] == 0.1
    assert 'from' in seen and r['window_days'] == 7


def test_no_scored_article_means_unavailable(monkeypatch):
    from src.news_processor import NewsProcessor
    monkeypatch.setenv('NEWSAPI_KEY', 'x')
    articles = [{'title': 'Cloudflare to present at conference', 'description': '', 'publishedAt': '2026-10-02T10:00:00Z'}]
    monkeypatch.setattr('src.news_processor.requests.get',
                        lambda *a, **k: FakeResponse({'articles': articles, 'totalResults': 1}))
    r = NewsProcessor().analyze('NET')
    assert r['status'] == 'DATA UNAVAILABLE' and r['news_score'] is None and 'lexicon' in r['reason']


def test_live_insider_counts_joint_filers_once(monkeypatch, sec):  # noqa: F811
    from tests.test_p03_sec_fundamentals_insider import add_form4
    from src.insider_tracker import InsiderTracker
    payloads, _ = sec
    xml = """<?xml version="1.0"?><ownershipDocument><documentType>4</documentType>
    <reportingOwner><reportingOwnerId><rptOwnerCik>1</rptOwnerCik><rptOwnerName>Fund GP</rptOwnerName></reportingOwnerId></reportingOwner>
    <reportingOwner><reportingOwnerId><rptOwnerCik>2</rptOwnerCik><rptOwnerName>Fund LP</rptOwnerName></reportingOwnerId></reportingOwner>
    <aff10b5One>0</aff10b5One><nonDerivativeTable><nonDerivativeTransaction>
    <transactionDate><value>2026-09-01</value></transactionDate>
    <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>10</value></transactionShares>
    <transactionPricePerShare><value>20</value></transactionPricePerShare>
    <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""
    add_form4(payloads, [('j-1', 5, xml)])
    result = InsiderTracker().run('MP')
    assert result['insider_buys'] == 1 and result['distinct_buyers'] == 1 and result['insider_score'] == 60


def test_validation_statement_names_news_gap_and_research():
    from src.scoring_signal_fixed import validation_status
    wf = {'status': 'OK', 'computed_at': '2026-10-07T09:00:00+00:00', 'stale': False, 'n_tickers': 40,
          'validated_components': ['technical', 'fundamentals', 'insider'],
          'horizons': {'5d': {'ic_cross_sectional': {'combined': 0.01}, 'ic_cross_sectional_t': {'combined': 0.8}}}}
    research = [{'stage': 1, 'computed_at': '2026-10-07T12:15:45+00:00', 'n_stocks': 148, 'n_tests': 205,
                 'n_significant_bh': 0, 'n_significant_bonferroni': 0, 'confirmatory': []}, None]
    v = validation_status(wf, research)
    assert 'WITHOUT news' in v['statement'] and 'never been validated' in v['statement']
    assert '0 of 205' in v['statement'] and v['live_signal_validated'] is False


def test_walk_forward_summary_respects_cutoff(tmp_path):
    import json
    from src.walk_forward import latest_summary
    path = tmp_path / 'wf.json'
    path.write_text(json.dumps({'status': 'OK', 'computed_at': '2026-10-07T09:00:00+00:00', 'metrics': {}}))
    before = latest_summary(path, now='2026-10-06T00:00:00+00:00')
    assert before['status'] == 'DATA UNAVAILABLE' and 'after' in before['reason']
    later = latest_summary(path, now='2026-10-20T00:00:00+00:00')
    assert later['stale'] is True


def test_sec_429_backs_off_and_retries(monkeypatch):
    from src import sec_parser
    from src.sec_parser import SECParser
    from tests.conftest import FakeResponse
    monkeypatch.setenv('SEC_USER_AGENT', 'TestAgent test@example.com')
    sleeps, calls = [], []
    monkeypatch.setattr('src.sec_parser.time.sleep', lambda s: sleeps.append(s))
    monkeypatch.setattr(sec_parser, '_PAUSE_UNTIL', [0.0])
    responses = [FakeResponse({}, 429), FakeResponse({}, 503), FakeResponse({'ok': 1})]

    def fake_get(self, url, timeout=None):
        calls.append(url)
        return responses.pop(0)
    monkeypatch.setattr('requests.Session.get', fake_get)
    assert SECParser()._get_json('https://data.sec.gov/x.json') == {'ok': 1}
    assert len(calls) == 3 and sleeps                      # paused before retrying


def test_sec_404_is_not_retried(monkeypatch):
    from src.sec_parser import SECParser
    from tests.conftest import FakeResponse
    monkeypatch.setenv('SEC_USER_AGENT', 'TestAgent test@example.com')
    monkeypatch.setattr('src.sec_parser.time.sleep', lambda s: None)
    calls = []
    monkeypatch.setattr('requests.Session.get', lambda self, url, timeout=None: calls.append(url) or FakeResponse({}, 404))
    assert SECParser()._get_json('https://data.sec.gov/missing.json') is None and len(calls) == 1
