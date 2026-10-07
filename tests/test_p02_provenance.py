"""
Phase P0.2 - provenance layer: schema v2, migration with backup, fetch log, raw payloads,
point-in-time access, freshness, source rank, secret redaction.
"""

import gzip
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
import yfinance

from tests.conftest import PROJECT_ROOT, FakeResponse, make_price_frame

SECRET = 'abcdef0123456789secret'


def fetch_for(db, source='FRED', raw=None):
    return db.record_fetch(source, 'https://example.test/endpoint', requested_at=db_now(),
                           status='OK', raw=raw)


def db_now():
    from src.common import utc_now_iso
    return utc_now_iso()


def create_legacy_db(path):
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE sec_data (ticker TEXT, metric TEXT, value TEXT, source TEXT, '
                 'confidence INTEGER, timestamp TEXT)')
    conn.execute("INSERT INTO sec_data VALUES ('CRWD','form4_count','7','SEC EDGAR',NULL,'2026-01-01')")
    conn.execute('CREATE TABLE macro_data (indicator TEXT, value REAL, date TEXT, source TEXT, '
                 'confidence INTEGER, timestamp TEXT)')
    conn.execute('CREATE TABLE backtest_results (ticker TEXT, date TEXT, predicted_signal TEXT, '
                 'actual_direction TEXT, accuracy_5d INTEGER, profit_loss REAL, timestamp TEXT)')
    conn.executemany('INSERT INTO backtest_results VALUES (?,?,?,?,?,?,?)',
                     [('MP', f'2026-01-{d:02d}', 'BUY', 'UP', 1, 1.5, '2026-02-01') for d in range(1, 11)])
    conn.execute('CREATE TABLE user_notes (note TEXT)')   # unknown table: must be kept
    conn.execute("INSERT INTO user_notes VALUES ('keep me')")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- schema / migration

def test_schema_v2_created_and_idempotent():
    from src.database import Database, SCHEMA_VERSION
    db = Database()
    assert db.schema_version() == SCHEMA_VERSION == 2
    assert {'source_fetches', 'observations', 'backtest_results'} <= set(db.tables())
    assert db.last_migration['backup'] is None            # nothing to back up on a fresh db
    again = Database()
    assert again.last_migration is None                   # no second migration


def test_migration_backs_up_then_drops_legacy_tables(tmp_path):
    from src.common import db_path
    from src.database import Database
    create_legacy_db(db_path())
    db = Database()

    info = db.last_migration
    assert sorted(info['dropped_tables']) == ['backtest_results', 'macro_data', 'sec_data']
    tables = set(db.tables())
    assert 'sec_data' not in tables and 'macro_data' not in tables
    assert 'user_notes' in tables                          # unknown tables are left alone
    with db.connect() as conn:                             # new backtest_results has provenance
        cols = {r[1] for r in conn.execute('PRAGMA table_info(backtest_results)')}
    assert {'outcome_date', 'price_fetch_id', 'computed_at'} <= cols
    assert db.count('backtest_results') == 0               # rebuilt by the next run

    backup = sqlite3.connect(info['backup']['db'])
    assert backup.execute('SELECT COUNT(*) FROM backtest_results').fetchone()[0] == 10
    assert backup.execute('SELECT value FROM sec_data').fetchone()[0] == '7'
    backup.close()
    export = json.loads(open(info['backup']['export'], encoding='utf-8').read())
    assert len(export['tables']['backtest_results']['rows']) == 10
    assert info['backup']['row_counts']['sec_data'] == 1


def test_published_after_retrieval_is_rejected_by_schema():
    from src.database import Database
    db = Database()
    fetch = fetch_for(db)
    with db.connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO observations (source, source_rank, entity, metric, as_of_date, value, "
            "published_at, published_at_basis, retrieved_at, fetch_id) VALUES "
            "('FRED', 1, 'X', 'value', '2026-01-01', 1.0, '2026-02-02T00:00:00+00:00', 's', "
            "'2026-02-01T00:00:00+00:00', ?)", (fetch['fetch_id'],))


# ---------------------------------------------------------------- fetch log / raw payloads

def test_record_fetch_stores_verifiable_raw_payload_without_secrets(monkeypatch):
    from src.common import data_dir
    from src.database import Database
    monkeypatch.setenv('FRED_API_KEY', SECRET)
    db = Database()
    payload = {'observations': [], 'echo': f'https://x.test/?api_key={SECRET}&a=1'}
    fetch = db.record_fetch('FRED', f'https://x.test/?api_key={SECRET}', requested_at=db_now(),
                            status='OK', params={'api_key': SECRET, 'series_id': 'UNRATE'},
                            raw=payload)
    row = db.get_fetch(fetch['fetch_id'])
    stored = (data_dir() / row['raw_path']).read_bytes()
    text = gzip.decompress(stored).decode('utf-8')
    assert row['raw_path'].startswith('raw/fred/')
    assert SECRET not in text and SECRET not in row['endpoint'] and SECRET not in row['request_params']
    assert '"series_id": "UNRATE"' in row['request_params']
    assert db.read_raw(fetch['fetch_id']) == text           # SHA-256 verified on read


def test_identical_raw_payloads_are_stored_once():
    from src.database import Database
    db = Database()
    a = fetch_for(db, raw={'x': 1})
    b = fetch_for(db, raw={'x': 1})
    assert a['raw_path'] == b['raw_path'] and a['fetch_id'] != b['fetch_id']


def test_failed_fetch_is_logged_with_redacted_error(monkeypatch):
    from src.database import Database
    monkeypatch.setenv('NEWSAPI_KEY', SECRET)
    db = Database()
    fetch = db.record_fetch('NewsAPI', 'https://newsapi.test', requested_at=db_now(),
                            status='DATA UNAVAILABLE', error=f'boom apiKey={SECRET}', http_status=401)
    row = db.get_fetch(fetch['fetch_id'])
    assert row['status'] == 'DATA UNAVAILABLE' and row['http_status'] == 401
    assert SECRET not in row['error'] and row['raw_path'] is None


def test_gitignore_excludes_data_directory():
    lines = (PROJECT_ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
    assert 'data/' in lines


# ---------------------------------------------------------------- redaction / secrets

def test_redact_masks_env_secrets_and_key_parameters(monkeypatch):
    from src.common import redact
    monkeypatch.setenv('FRED_API_KEY', f'<{SECRET}>')
    text = redact(f'url?series_id=X&api_key=%3C{SECRET}%3E&apiKey=zzz token={SECRET}')
    assert SECRET not in text and 'zzz' not in text and 'series_id=X' in text


@pytest.mark.parametrize('value,problem', [
    ('', 'not set'), ('<abc123>', 'placeholder'), ('ab c', 'whitespace'), ('abc123', None)])
def test_secret_env_rejects_placeholders(monkeypatch, value, problem):
    from src.common import secret_env
    monkeypatch.setenv('NEWSAPI_KEY', value)
    got, reason = secret_env('NEWSAPI_KEY')
    if problem is None:
        assert got == value and reason is None
    else:
        assert got is None and problem in reason and (not value.strip('<> ') or value not in reason)


def test_placeholder_fred_key_is_reported_without_calling_api(monkeypatch):
    from src.macro_fred import MacroFRED
    monkeypatch.setenv('FRED_API_KEY', f'<{SECRET}>')
    called = []
    monkeypatch.setattr('src.macro_fred.requests.get', lambda *a, **k: called.append(1))
    result = MacroFRED().run()
    assert called == []
    assert result['status'] == 'DATA UNAVAILABLE'
    reason = result['indicators']['CPI_YOY']['reason']
    assert 'placeholder' in reason and SECRET not in reason


def test_fred_http_error_never_contains_the_key(monkeypatch):
    from src.macro_fred import MacroFRED
    monkeypatch.setenv('FRED_API_KEY', SECRET)
    monkeypatch.setattr('src.macro_fred.requests.get', lambda *a, **k: FakeResponse(
        {'error_code': 400, 'error_message': 'Bad Request. api_key is not registered.'}, 400))
    data = MacroFRED().fetch_indicator('UNEMPLOYMENT')
    assert data['status'] == 'DATA UNAVAILABLE'
    assert data['reason'].startswith('FRED HTTP 400')
    assert SECRET not in json.dumps(data)


# ---------------------------------------------------------------- point-in-time

def test_point_in_time_never_returns_values_published_later():
    from src.database import Database
    db = Database()
    fetch = fetch_for(db)
    db.upsert_observations(fetch, [
        {'entity': 'CPIAUCSL', 'metric': 'value', 'as_of_date': '2025-06-01', 'value': 321.5,
         'published_at': '2025-07-15T12:30:00Z'},
        {'entity': 'CPIAUCSL', 'metric': 'value', 'as_of_date': '2025-06-01', 'value': 321.435,
         'published_at': '2026-02-13T12:30:00Z'},     # revision
        {'entity': 'CPIAUCSL', 'metric': 'value', 'as_of_date': '2025-07-01', 'value': 322.0,
         'published_at': '2025-08-12T12:30:00Z'},
    ])
    before_release = db.get_point_in_time('CPIAUCSL', 'value', known_at='2025-07-10T00:00:00Z')
    assert before_release is None
    first = db.get_point_in_time('CPIAUCSL', 'value', known_at='2025-08-01T00:00:00Z')
    assert (first['as_of_date'], first['value']) == ('2025-06-01', 321.5)
    pre_revision = db.series('CPIAUCSL', 'value', known_at='2026-01-01T00:00:00Z')
    assert dict((d, r['value']) for d, r in pre_revision) == {'2025-06-01': 321.5, '2025-07-01': 322.0}
    latest = db.series('CPIAUCSL', 'value')
    assert dict(latest)['2025-06-01']['value'] == 321.435
    # strict vintage: the stored version itself was only retrieved today
    assert db.get_point_in_time('CPIAUCSL', 'value', known_at='2025-08-01T00:00:00Z',
                                strict_vintage=True) is None


def test_unknown_publication_time_falls_back_to_retrieval_time():
    from src.database import Database
    db = Database()
    fetch = fetch_for(db)
    db.upsert_observations(fetch, [{'entity': 'X', 'metric': 'm', 'as_of_date': '2020-01-01',
                                    'value': 1.0}])
    assert db.get_point_in_time('X', 'm', known_at='2025-01-01T00:00:00Z') is None
    row = db.get_point_in_time('X', 'm', known_at=fetch['retrieved_at'])
    assert row['published_at'] is None and row['published_at_basis'] == 'unknown'


def test_future_publication_is_clamped_to_retrieval():
    from src.database import Database
    db = Database()
    fetch = fetch_for(db)
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    db.upsert_observations(fetch, [{'entity': 'X', 'metric': 'm', 'as_of_date': '2026-01-01',
                                    'value': 1.0, 'published_at': future}])
    row = db.get_point_in_time('X', 'm')
    assert row['published_at'] == fetch['retrieved_at']
    assert 'clamped' in row['published_at_basis']


def test_reingesting_same_value_adds_nothing_but_revision_adds_version():
    from src.database import Database
    db = Database()
    row = {'entity': 'X', 'metric': 'm', 'as_of_date': '2026-01-01', 'value': 1.0,
           'published_at': '2026-01-02T00:00:00Z'}
    assert db.upsert_observations(fetch_for(db), [row]) == 1
    assert db.upsert_observations(fetch_for(db), [row]) == 0
    assert db.upsert_observations(fetch_for(db), [dict(row, value=2.0)]) == 1
    assert db.count('observations') == 2


def test_events_on_the_same_day_are_distinct():
    from src.database import Database
    db = Database()
    rows = [{'entity': 'MP', 'metric': 'filing:4', 'as_of_date': '2026-09-30', 'value_text': acc,
             'published_at': '2026-10-01T00:24:39Z'} for acc in ('a', 'b')]
    assert db.upsert_observations(fetch_for(db, 'SEC EDGAR'), rows) == 2
    assert len(db.events('MP', 'filing:4')) == 2


def test_better_ranked_source_wins_and_conflict_is_reported():
    from src.database import Database
    db = Database()
    common = {'entity': 'MP', 'metric': 'close', 'as_of_date': '2026-09-30',
              'published_at': '2026-09-30T21:00:00Z'}
    db.upsert_observations(fetch_for(db, 'yfinance'), [dict(common, value=10.0)])
    db.upsert_observations(fetch_for(db, 'SEC EDGAR'), [dict(common, value=10.5)])
    best = db.get_point_in_time('MP', 'close')
    assert best['source'] == 'SEC EDGAR' and best['value'] == 10.5
    assert [c['source'] for c in best['conflicts']] == ['yfinance']


def test_unknown_source_is_rejected():
    from src.database import Database
    with pytest.raises(ValueError):
        fetch_for(Database(), 'SomeBlog')


# ---------------------------------------------------------------- freshness

@pytest.mark.parametrize('cadence,age,status', [
    ('daily_market', 5, 'FRESH'), ('daily_market', 6, 'STALE'),
    ('monthly', 80, 'FRESH'), ('monthly', 81, 'STALE'), ('unknown_cadence', 1, 'UNKNOWN')])
def test_freshness_thresholds(cadence, age, status):
    from src.database import freshness
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    as_of = (now - timedelta(days=age)).date().isoformat()
    assert freshness(as_of, cadence, now=now)['status'] == status


# ---------------------------------------------------------------- sources

def test_sec_filings_stored_with_acceptance_time_and_counted_point_in_time(monkeypatch):
    from src.sec_parser import SECParser
    monkeypatch.setenv('SEC_USER_AGENT', 'TestAgent test@example.com')
    now = datetime.now(timezone.utc)

    def iso(d):
        return d.strftime('%Y-%m-%dT%H:%M:%S.000Z')
    payloads = {
        'company_tickers.json': {'0': {'cik_str': 1801368, 'ticker': 'MP', 'title': 'MP Materials'}},
        'CIK0001801368.json': {'filings': {'recent': {
            'form': ['4', '10-Q', '4'],
            'filingDate': [(now - timedelta(days=d)).strftime('%Y-%m-%d') for d in (5, 60, 150)],
            'reportDate': ['', '2026-06-30', ''],
            'accessionNumber': ['acc-1', 'acc-2', 'acc-3'],
            'acceptanceDateTime': [iso(now - timedelta(days=d)) for d in (5, 60, 150)]}}},
    }
    monkeypatch.setattr('requests.Session.get', lambda self, url, timeout=None: next(
        (FakeResponse(p) for k, p in payloads.items() if url.endswith(k)), FakeResponse({}, 404)))
    monkeypatch.setattr('src.sec_parser.time.sleep', lambda s: None)

    parser = SECParser()
    result = parser.run('MP')
    assert result['form4_filings_90d'] == 1
    assert parser.fetch_form4_count('MP', known_at=now - timedelta(days=30)) == 0
    assert parser.fetch_form4_count('MP', known_at=now - timedelta(days=100)) == 1
    assert parser.fetch_latest_periodic_filing('MP', known_at=now - timedelta(days=90)) is None
    latest = result['latest_periodic_filing']
    assert latest['published_at_basis'].startswith('SEC acceptanceDateTime read as New York time')
    prov = result['provenance']
    assert prov['source'] == 'SEC EDGAR' and prov['source_rank'] == 1
    assert prov['as_of_date'] == '2026-06-30' and prov['raw_sha256']
    assert parser.db.count('source_fetches') == 3   # ticker file, submissions, company facts (P0.3)


def test_fred_vintages_stored_and_current_vintage_displayed(monkeypatch):
    from src.macro_fred import MacroFRED
    monkeypatch.setenv('FRED_API_KEY', 'x' * 32)
    observations = [
        {'realtime_start': '2025-07-15', 'realtime_end': '2026-02-12', 'date': '2025-06-01', 'value': '4.1'},
        {'realtime_start': '2026-02-13', 'realtime_end': '9999-12-31', 'date': '2025-06-01', 'value': '4.2'},
        {'realtime_start': '2025-08-01', 'realtime_end': '9999-12-31', 'date': '2025-07-01', 'value': '4.3'},
    ]
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen.update(params)
        return FakeResponse({'observations': observations})
    monkeypatch.setattr('src.macro_fred.requests.get', fake_get)
    macro = MacroFRED()
    data = macro.fetch_indicator('UNEMPLOYMENT')
    assert seen['realtime_end'] == '9999-12-31' and seen['realtime_start'] == seen['observation_start']
    assert data['value'] == 4.3 and data['observation_date'] == '2025-07-01'
    assert data['provenance']['published_at'] == '2025-08-02T05:00:00+00:00'
    assert macro.db.count('observations') == 3
    known_mid_2025 = macro.db.get_point_in_time('UNRATE', 'value', as_of_date='2025-06-01',
                                                known_at='2025-12-31T00:00:00Z')
    assert known_mid_2025['value'] == 4.1                     # first release, not the revision


def test_news_articles_stored_with_publication_time(monkeypatch):
    from src.news_processor import NewsProcessor
    monkeypatch.setenv('NEWSAPI_KEY', 'k' * 32)
    articles = [{'title': 'Cloudflare shares surge', 'url': 'https://n.test/1',
                 'publishedAt': '2026-10-01T10:00:00Z'}]
    monkeypatch.setattr('src.news_processor.requests.get',
                        lambda *a, **k: FakeResponse({'articles': articles}))
    processor = NewsProcessor()
    result = processor.analyze('NET')
    assert result['provenance']['published_at'] == '2026-10-01T10:00:00+00:00'
    events = processor.db.events('NET', 'news_article')
    assert events[0]['value_text'] == 'https://n.test/1'


def test_price_feed_downloads_once_and_stores_completed_sessions(monkeypatch):
    from src.backtester import Backtester
    from src.market_data import PriceFeed
    from src.prediction_engine import PredictionEngine
    from src.price_technical import PriceTechnical
    calls = []

    def fake_download(*a, **k):
        calls.append(k.get('auto_adjust'))
        return make_price_frame(500)
    monkeypatch.setattr(yfinance, 'download', fake_download)
    feed = PriceFeed()
    tech = PriceTechnical(price_feed=feed).analyze('CRWD')
    bt = Backtester(price_feed=feed).run('CRWD')
    base = PredictionEngine(price_feed=feed).analyze('CRWD')
    assert calls == [True, False]                      # one adjusted + one raw download in total
    assert tech['provenance']['fetch_id'] == bt['provenance']['fetch_id'] == base['provenance']['fetch_id']
    assert tech['provenance']['as_of_date'] == '2026-09-30'
    close = feed.db.get_point_in_time('CRWD', 'close')
    assert close['value_revisable'] == 1 and close['published_at'] == '2026-09-30T21:00:00+00:00'
    with feed.db.connect() as conn:
        rows = conn.execute('SELECT signal_date, outcome_date, price_fetch_id FROM backtest_results').fetchall()
    assert rows and all(r['signal_date'] < r['outcome_date'] for r in rows)


def test_price_feed_drops_session_not_closed_yet(monkeypatch):
    import pandas as pd
    from src.market_data import PriceFeed
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    frame = make_price_frame(100, multiindex=False)
    frame.index = list(pd.bdate_range(end='2026-09-30', periods=99)) + [pd.Timestamp(tomorrow)]
    monkeypatch.setattr(yfinance, 'download', lambda *a, **k: frame)
    feed = PriceFeed()
    result = feed.get('CRWD')
    assert result['dropped_incomplete_sessions'] == 1
    assert str(result['close'].index[-1].date()) == '2026-09-30'
    assert feed.db.get_point_in_time('CRWD', 'close')['as_of_date'] == '2026-09-30'


def test_sec_acceptance_time_is_read_conservatively():
    from src.sec_parser import acceptance_to_utc
    # labelled UTC in the feed; read as New York time -> never earlier than the UTC reading
    assert acceptance_to_utc('2026-08-06T22:15:49.000Z') == '2026-08-07T02:15:49+00:00'   # EDT
    assert acceptance_to_utc('2026-01-15T18:00:00.000Z') == '2026-01-15T23:00:00+00:00'   # EST


# ---------------------------------------------------------------- end-to-end

def test_pipeline_report_has_provenance_and_no_secret(monkeypatch, tmp_path):
    from src.integration import Integration
    monkeypatch.setenv('FRED_API_KEY', SECRET)
    monkeypatch.setattr(yfinance, 'download', lambda *a, **k: make_price_frame(500))
    monkeypatch.setattr('src.macro_fred.requests.get', lambda url, params=None, timeout=None:
                        FakeResponse({'error_message': f'bad key {params["api_key"]}'}, 400))
    results = Integration().run_daily_batch()
    assert results[0]['provenance']['technical']['source'] == 'yfinance'
    html = (tmp_path / 'reports' / 'analysis.html').read_text(encoding='utf-8')
    report_json = (tmp_path / 'reports' / 'analysis.json').read_text(encoding='utf-8')
    assert 'Data provenance' in html
    for text in (html, report_json):
        assert SECRET not in text
