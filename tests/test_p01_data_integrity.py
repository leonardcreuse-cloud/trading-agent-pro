"""
Phase P0.1 - no invented data, explicit unavailability, pipeline runs on a fresh clone.
"""

import ast
import json
import re
from datetime import datetime, timedelta

import pytest
import yfinance

from tests.conftest import PROJECT_ROOT, FakeResponse, make_price_frame


# ---------------------------------------------------------------- compilation

def all_python_files():
    return sorted(p for p in PROJECT_ROOT.rglob('*.py')
                  if 'venv' not in p.parts and '.git' not in p.parts)


@pytest.mark.parametrize('path', all_python_files(), ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
def test_every_python_file_compiles(path):
    ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))


# ---------------------------------------------------------------- SEC

def test_sec_has_no_hardcoded_financial_values():
    source = (PROJECT_ROOT / 'src' / 'sec_parser.py').read_text(encoding='utf-8')
    assert 'revenue_data' not in source and 'de_data' not in source
    assert not re.search(r"'(CRWD|NET|RKLB|MP)':\s*[0-9]", source), 'hardcoded per-ticker numbers'


def test_sec_without_user_agent_is_unavailable_not_invented():
    from src.sec_parser import SECParser
    result = SECParser().run('CRWD')
    assert result['revenue'] is None
    assert result['debt_to_equity'] is None
    assert result['form4_filings_90d'] is None          # was 0 before: an invented value
    assert result['source_status'] == 'DATA UNAVAILABLE'
    assert 'SEC_USER_AGENT' in result['error']


def test_sec_purges_previously_cached_invented_values(tmp_path):
    import sqlite3
    from src.common import db_path
    from src.sec_parser import SECParser
    SECParser()  # creates table
    conn = sqlite3.connect(db_path())
    conn.execute("INSERT OR REPLACE INTO sec_data VALUES ('CRWD','revenue','1050000000','SEC EDGAR',95,?)",
                 (datetime.now().isoformat(),))
    conn.commit()
    conn.close()
    SECParser()
    conn = sqlite3.connect(db_path())
    rows = conn.execute("SELECT * FROM sec_data WHERE metric='revenue'").fetchall()
    conn.close()
    assert rows == []


def test_sec_resolves_cik_and_counts_form4_from_api(monkeypatch):
    from src.sec_parser import SECParser
    monkeypatch.setenv('SEC_USER_AGENT', 'TestAgent test@example.com')
    recent_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
    old_date = (datetime.now() - timedelta(days=200)).strftime('%Y-%m-%d')
    payloads = {
        'company_tickers.json': {'0': {'cik_str': 1535527, 'ticker': 'CRWD', 'title': 'CrowdStrike'}},
        'CIK0001535527.json': {'filings': {'recent': {
            'form': ['4', '4', '10-Q', '4'],
            'filingDate': [recent_date, recent_date, recent_date, old_date],
            'reportDate': ['', '', '2026-07-31', ''],
            'accessionNumber': ['a', 'b', 'c', 'd']}}},
    }

    def fake_get(self, url, timeout=None):
        for key, payload in payloads.items():
            if url.endswith(key):
                return FakeResponse(payload)
        return FakeResponse({}, 404)

    monkeypatch.setattr('requests.Session.get', fake_get)
    monkeypatch.setattr('src.sec_parser.time.sleep', lambda s: None)
    result = SECParser().run('CRWD')
    assert result['cik'] == '0001535527'
    assert result['form4_filings_90d'] == 2
    assert result['latest_periodic_filing']['form'] == '10-Q'
    assert result['revenue'] is None   # still unavailable until XBRL (P0.3)


def test_sec_cache_expires():
    import sqlite3
    from src.common import db_path
    from src.sec_parser import SECParser
    parser = SECParser()
    old = (datetime.now() - timedelta(days=3)).isoformat()
    conn = sqlite3.connect(db_path())
    conn.execute("INSERT OR REPLACE INTO sec_data VALUES ('CRWD','form4_count','7','SEC EDGAR',NULL,?)", (old,))
    conn.commit()
    conn.close()
    assert parser.get_cached('CRWD', 'form4_count') is None


# ---------------------------------------------------------------- insider / fundamentals

def test_insider_reports_unavailable_instead_of_neutral():
    from src.insider_tracker import InsiderTracker
    result = InsiderTracker().run('NET')
    assert result['status'] == 'DATA UNAVAILABLE'
    assert result['signal'] is None
    assert result['insider_buys'] is None


def test_fundamentals_missing_inputs_give_none_not_50():
    from src.scoring_fundamentals import ScoringFundamentals
    result = ScoringFundamentals().analyze('RKLB')
    assert result['fundamental_score'] is None
    assert result['signal'] is None
    assert result['status'] == 'DATA UNAVAILABLE'
    assert result['coverage'] == '0/2'


def test_fundamentals_composite_uses_available_components_only():
    from src.scoring_fundamentals import ScoringFundamentals
    f = ScoringFundamentals.__new__(ScoringFundamentals)
    assert f.calculate_composite_score({'revenue_scale': None, 'leverage': 90}) == 90
    assert f.calculate_composite_score({'revenue_scale': None, 'leverage': None}) is None


# ---------------------------------------------------------------- combined signal

def test_signal_requires_two_components():
    from src.scoring_signal_fixed import ScoringSignalFixed, INSUFFICIENT_DATA
    s = ScoringSignalFixed()
    result = s.analyze('MP', {'technical_score': 70, 'signal': 'BUY'}, {'fundamental_score': None},
                       {'news_score': None})
    assert result['combined_score'] is None
    assert result['signal'] == INSUFFICIENT_DATA
    assert result['coverage'] == '1/3'
    assert result['signal_agreement'] is None


def test_signal_renormalizes_weights_over_available_components():
    from src.scoring_signal_fixed import ScoringSignalFixed
    s = ScoringSignalFixed()
    result = s.analyze('MP', {'technical_score': 80}, {'fundamental_score': None}, {'news_score': 40})
    # technical 0.25 and news 0.25 -> equal weights once renormalized
    assert result['combined_score'] == 60.0
    assert result['coverage'] == '2/3'
    assert result['missing_components'] == ['fundamentals']


# ---------------------------------------------------------------- technical

def test_technical_without_prices_is_unavailable():
    from src.price_technical import PriceTechnical
    result = PriceTechnical().analyze('CRWD')
    assert result['technical_score'] is None
    assert result['signal'] is None
    assert result['status'] == 'DATA UNAVAILABLE'


def test_technical_handles_multiindex_yfinance_frames(monkeypatch):
    from src.price_technical import PriceTechnical
    monkeypatch.setattr(yfinance, 'download', lambda *a, **k: make_price_frame(130))
    result = PriceTechnical().analyze('CRWD')
    assert result['status'] == 'OK'
    assert 0 <= result['technical_score'] <= 100
    assert result['last_price_date'] == '2026-09-30'


# ---------------------------------------------------------------- news

def test_news_without_key_is_unavailable_not_50():
    from src.news_processor import NewsProcessor
    result = NewsProcessor().analyze('NET')
    assert result['news_score'] is None
    assert result['status'] == 'DATA UNAVAILABLE'
    assert result['query'] == '"Cloudflare"'   # company name, not the ambiguous ticker


def test_news_with_articles_reports_publication_range(monkeypatch):
    from src.news_processor import NewsProcessor
    monkeypatch.setenv('NEWSAPI_KEY', 'x')
    articles = [{'title': 'Cloudflare shares surge on record growth', 'description': '',
                 'publishedAt': '2026-10-01T10:00:00Z'},
                {'title': 'Cloudflare outage', 'description': 'service decline',
                 'publishedAt': '2026-09-28T08:00:00Z'}]
    monkeypatch.setattr('src.news_processor.requests.get',
                        lambda *a, **k: FakeResponse({'articles': articles}))
    result = NewsProcessor().analyze('NET')
    assert result['status'] == 'OK'
    assert result['articles_count'] == 2
    assert result['oldest_article_published_at'] == '2026-09-28T08:00:00Z'
    assert result['newest_article_published_at'] == '2026-10-01T10:00:00Z'


def test_sentiment_matches_whole_words_only():
    from src.news_sentiment import NewsSentiment
    # 'update', 'supply', 'group', 'executive' used to match 'up' / 'cut' as substrings
    assert NewsSentiment.analyze_sentiment('Company update on supply group executive') == 50
    assert NewsSentiment.analyze_sentiment('Shares surge') > 50
    assert NewsSentiment.analyze_sentiment('Shares plunge') < 50


# ---------------------------------------------------------------- macro

def test_macro_without_key_is_unavailable():
    from src.macro_fred import MacroFRED
    result = MacroFRED().run()
    assert result['status'] == 'DATA UNAVAILABLE'
    assert all(d['status'] == 'DATA UNAVAILABLE' for d in result['indicators'].values())


def test_cpi_is_reported_as_year_over_year_not_index_level(monkeypatch):
    from src.macro_fred import MacroFRED
    monkeypatch.setenv('FRED_API_KEY', 'x')
    observations = [{'date': f'{y}-{m:02d}-01', 'value': str(300 + (y - 2025) * 12 + m)}
                    for y in (2025, 2026) for m in range(1, 9)]
    observations.append({'date': '2026-09-01', 'value': '.'})  # FRED missing marker
    monkeypatch.setattr('src.macro_fred.requests.get',
                        lambda *a, **k: FakeResponse({'observations': observations}))
    data = MacroFRED().fetch_indicator('CPI_YOY')
    assert data['status'] == 'OK'
    assert data['observation_date'] == '2026-08-01'
    assert data['unit'] == '% YoY'
    assert data['value'] == round((320 / 308 - 1) * 100, 2)   # ~3.9%, not ~320


# ---------------------------------------------------------------- base rates

def test_base_rates_are_labelled_and_use_mean_of_all_returns():
    import pandas as pd
    from src.prediction_engine import PredictionEngine
    close = pd.Series([100, 110, 99, 108.9, 98.01, 107.811])  # alternating +10% / -10%
    rates = PredictionEngine(horizons=[1]).calculate_base_rates(close)['1D']
    assert rates['historical_up_frequency_pct'] == 60.0
    assert rates['mean_return_pct'] == 2.0          # old "expected_return" would give +10
    assert rates['n_independent'] == 5
    assert rates['insufficient_sample'] is True


def test_prediction_engine_output_is_not_presented_as_model(monkeypatch):
    from src.prediction_engine import PredictionEngine
    monkeypatch.setattr(yfinance, 'download', lambda *a, **k: make_price_frame(500))
    result = PredictionEngine().analyze('CRWD')
    assert result['is_model_prediction'] is False
    assert result['kind'] == 'historical_base_rate'
    assert 'p_up' not in json.dumps(result)
    assert result['horizons']['60D']['insufficient_sample'] is True


# ---------------------------------------------------------------- backtester

def test_backtester_no_longer_reports_invalid_metrics(monkeypatch):
    from src.backtester import Backtester
    monkeypatch.setattr(yfinance, 'download', lambda *a, **k: make_price_frame(500))
    result = Backtester().run('CRWD')
    metrics = result['backtest_results']
    for invalid in ('sharpe_ratio', 'max_drawdown', 'total_profit', 'win_rate'):
        assert invalid not in metrics
    assert result['status'] == 'PROVISIONAL'
    assert 'baseline_accuracy_pct' in metrics


# ---------------------------------------------------------------- reports / dashboard

FABRICATED_MARKERS = ['STRONG BUY', 'Morgan Stanley', '85/100', '68.5%', 'Sharpe Ratio',
                      'Data leakage: PREVENTED', 'READY_FOR_LIVE', 'no_leakage']


def test_dashboard_contains_no_fabricated_values():
    from src.dashboard import Dashboard
    html = Dashboard().create_live_dashboard_html([{'ticker': 'CRWD', 'modules': {}, 'data_availability': {}}])
    for marker in FABRICATED_MARKERS:
        assert marker not in html
    assert 'N/A — source unavailable' in html


def test_dashboard_source_has_no_hardcoded_scores():
    source = (PROJECT_ROOT / 'src' / 'dashboard.py').read_text(encoding='utf-8')
    for marker in ('Morgan Stanley', '85/100', '68.5%', '1.25', '-12.3%'):
        assert marker not in source


def test_report_renders_missing_values_without_crashing():
    from src.report_generator import ReportGenerator
    html = ReportGenerator().generate_html([{'ticker': 'MP', 'modules': {'sec': {'revenue': None}},
                                             'data_availability': {'sec': 'DATA UNAVAILABLE'}}])
    assert 'N/A — source unavailable' in html


# ---------------------------------------------------------------- end-to-end

def test_full_pipeline_runs_offline_and_reports_unavailability(tmp_path):
    from src.integration import Integration
    results = Integration().run_daily_batch()

    assert [r['ticker'] for r in results] == ['CRWD', 'NET', 'RKLB', 'MP']
    for r in results:
        m = r['modules']
        assert m['signal']['combined_score'] is None
        assert m['signal']['signal'] == 'INSUFFICIENT DATA'
        assert m['walk_forward']['status'] == 'NOT IMPLEMENTED'
        assert r['data_availability']['technical'] == 'DATA UNAVAILABLE'
        assert r['data_availability']['macro'] == 'DATA UNAVAILABLE'

    html = (tmp_path / 'reports' / 'analysis.html').read_text(encoding='utf-8')
    report_json = (tmp_path / 'reports' / 'analysis.json').read_text(encoding='utf-8')
    dashboard = (tmp_path / 'reports' / 'dashboard.html').read_text(encoding='utf-8')
    for text in (html, report_json, dashboard):
        for marker in FABRICATED_MARKERS:
            assert marker not in text
    assert 'N/A — source unavailable' in html
    assert (tmp_path / 'data' / 'trading_pro.db').exists()
