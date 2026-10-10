"""Phase P3.1 - integration fixes requested by the weekly section builders (offline)."""

from tests.test_p03_sec_fundamentals_insider import CIK, sec  # noqa: F401 - fixture


def test_fact_ingestion_reuses_stored_submissions(sec):  # noqa: F811
    from src.sec_parser import SECParser
    _, calls = sec
    first = SECParser()
    first.fundamentals('MP')
    second = SECParser(db=first.db)
    second.fundamentals('MP', known_at='2026-08-01T00:00:00+00:00')
    assert sum('submissions' in u for u in calls) == 1     # the second parser reused the stored feed


def test_no_duplicate_facts_when_submissions_unavailable(sec):  # noqa: F811
    from src.sec_parser import SECParser
    payloads, _ = sec
    first = SECParser()
    first.fundamentals('MP')
    n = first.db.count('observations')
    del payloads[f'submissions/CIK{CIK}.json']
    second = SECParser(db=first.db)
    second.db.latest_fetch = lambda *a, **k: None          # force downloads: submissions now fail
    fin = second.fundamentals('MP')
    assert second.db.count('observations') == n            # no later-published duplicates stored
    assert fin['revenue'] == 305_377_000                   # stored, point-in-time versions still used


def test_walk_forward_summary_uses_latest_archived_run_before_cutoff():
    import json
    from src.common import history_dir, stamp
    from src.walk_forward import latest_summary
    for computed in ('2026-09-01T09:00:00+00:00', '2026-10-01T09:00:00+00:00'):
        (history_dir() / f'walk_forward_{stamp(computed)}.json').write_text(
            json.dumps({'status': 'OK', 'computed_at': computed, 'metrics': {}}))
    assert latest_summary(now='2026-09-15T00:00:00+00:00')['computed_at'] == '2026-09-01T09:00:00+00:00'
    assert latest_summary(now='2026-10-05T00:00:00+00:00')['computed_at'] == '2026-10-01T09:00:00+00:00'


def test_research_summary_hides_results_computed_after_cutoff(tmp_path):
    import json
    from src.scoring_signal_fixed import research_summary
    path = tmp_path / 'r.json'
    path.write_text(json.dumps({'computed_at': '2026-10-07T12:00:00+00:00', 'universe': {}, 'feature_tests': []}))
    assert research_summary(1, path, as_of='2026-10-01T00:00:00+00:00') is None
    assert research_summary(1, path, as_of='2026-10-08T00:00:00+00:00')['computed_at'] == '2026-10-07T12:00:00+00:00'


def test_validation_reason_is_a_sentence():
    from src.scoring_signal_fixed import validation_status
    v = validation_status({'status': 'DATA UNAVAILABLE', 'reason': 'the latest run was computed later'})
    assert 'The latest run was computed later.' in v['statement']
