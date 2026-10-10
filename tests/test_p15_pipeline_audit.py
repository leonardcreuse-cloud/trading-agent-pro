"""Phase P1.5 - pipeline audit detects broken rules (offline)."""

import json

import pandas as pd
import yfinance

from tests.conftest import make_price_frame


def test_storage_checks_pass_on_clean_database():
    from src.pipeline_audit import PipelineAudit
    db_checks = PipelineAudit().storage_checks()
    assert all(c['status'] == 'PASS' for c in db_checks)


def test_walk_forward_timing_failure_is_detected(tmp_path):
    from src.market_data import session_close_utc
    from src.pipeline_audit import FAIL, PASS, PipelineAudit
    good = {'ticker': 'MP', 'date': '2026-01-05', 'known_at': session_close_utc('2026-01-05'),
            'entry_date': '2026-01-06', 'exit_5d': '2026-01-13', 'exit_20d': None}
    bad = dict(good, date='2026-01-12', known_at=session_close_utc('2026-01-12'), entry_date='2026-01-12')
    from src.common import reports_dir
    path = reports_dir() / 'walk_forward.json'
    path.write_text(json.dumps({'samples': [good]}), encoding='utf-8')
    assert PipelineAudit.walk_forward_checks()[0]['status'] == PASS
    path.write_text(json.dumps({'samples': [good, bad]}), encoding='utf-8')
    result = PipelineAudit.walk_forward_checks()[0]
    assert result['status'] == FAIL and result['evidence'] == ['MP 2026-01-12']


def test_price_checks_flag_non_positive_and_large_moves(monkeypatch):
    from src.pipeline_audit import FAIL, WARN, PipelineAudit
    frame = make_price_frame(300)
    frame.iloc[100, 0] = frame.iloc[99, 0] * 2          # +100 % in one day
    frame.iloc[200, 0] = -1.0
    monkeypatch.setattr(yfinance, 'download', lambda *a, **k: frame)
    by_name = {c['check']: c for c in PipelineAudit().price_checks('MP')}
    assert by_name['non-positive closes']['status'] == FAIL
    assert by_name['|daily return| > 40%']['status'] == WARN


def test_audit_without_sec_reports_warnings_not_crashes(monkeypatch):
    from src.pipeline_audit import PipelineAudit
    monkeypatch.setattr(yfinance, 'download', lambda *a, **k: make_price_frame(300))
    report = PipelineAudit().run(['MP'])
    assert report['summary']['FAIL'] == 0 and report['status'] == 'WARN'
    groups = {c['group'] for c in report['tickers']['MP']}
    assert groups == {'prices', 'sec', 'insider'}


def test_audit_flags_backdated_and_keyless_fred_rows():
    from src.database import Database
    from src.pipeline_audit import PipelineAudit
    db = Database()
    db.record_fetch('FRED', 'https://api.stlouisfed.org/fred/series/observations',
                    requested_at='2026-10-07T10:00:00+00:00', status='OK', params={'api_key': 'k'})
    with db.connect() as conn:          # a synthetic row: backdated, no api_key
        conn.execute("INSERT INTO source_fetches (source, endpoint, request_params, requested_at, completed_at, "
                     "status) VALUES ('FRED', 'https://api.stlouisfed.org/fred/release/dates', '{}', "
                     "'2026-09-01T12:00:00+00:00', '2026-09-01T12:00:00+00:00', 'OK')")
    checks = {c['check']: c for c in PipelineAudit(db=db).storage_checks()}
    assert checks['fetch rows completed earlier than previously logged rows (backdated)']['status'] == 'WARN'
    assert checks['FRED fetch rows without api_key parameter (not a real call)']['status'] == 'WARN'
