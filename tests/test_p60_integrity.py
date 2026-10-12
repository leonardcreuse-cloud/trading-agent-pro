"""
P0 (master mission): preservation of finished experiments and isolation of test data.
"""

import pytest


def test_finished_research_results_are_never_overwritten():
    from src.common import reports_dir
    from src.research.experiment import Study, results_paths
    original = reports_dir() / 'research_stage2.json'
    original.write_text('{"computed_at": "2026-10-11T13:21:34+00:00"}', encoding='utf-8')
    with pytest.raises(FileExistsError, match='never overwritten'):
        Study(stage=2).check_writable()
    recalc = Study(stage=2, recalc='sec-times')
    assert recalc.out.name == 'research_stage2_recalc_sec-times.json'
    recalc.check_writable()                                       # a labelled recalculation has its own file
    assert results_paths(1)[0].name == 'research_stage1.json'
    with pytest.raises(ValueError):
        results_paths(2, '../stage2')


def test_production_folders_are_refused_under_pytest(monkeypatch):
    from src import common
    monkeypatch.delenv('TRADING_AGENT_DATA_DIR')
    with pytest.raises(RuntimeError, match='production folder'):
        common.data_dir()
    monkeypatch.delenv('TRADING_AGENT_REPORTS_DIR')
    with pytest.raises(RuntimeError, match='production folder'):
        common.reports_dir()


def test_parsed_counts_are_recorded_and_drops_detected():
    from src.database import Database
    db = Database()
    for n in (10, 11, 10, 12, 4):                               # last fetch parses far fewer rows
        fetch = db.record_fetch('BLS', f'https://www.bls.gov/schedule/2026_{n:02d}_sched.htm', status='OK',
                                raw='x', raw_ext='html')
        db.upsert_observations(fetch, [{'entity': 'CPI', 'metric': f'release_{i}', 'as_of_date': '2026-10-01',
                                        'value': float(i)} for i in range(n)])
    empty = db.record_fetch('EIA', 'https://api.eia.gov/v2/x', status='OK', raw='{}', raw_ext='json')
    db.upsert_observations(empty, [])
    with db.connect() as conn:
        assert conn.execute('SELECT n_records FROM source_fetches WHERE fetch_id=?',
                            (empty['fetch_id'],)).fetchone()[0] == 0          # an empty parse is recorded
    drops = db.record_count_drops(['BLS', 'EIA'], dated_sources=('BLS',))
    assert db.record_count_drops(['BLS', 'EIA']) == []                  # each monthly page has one fetch only
    assert [(d['source'], d['n_records'], d['median']) for d in drops] == [('BLS', 4, 11)]


def test_ingestion_never_stores_a_redundant_version():
    """A fact repeated by later filings in one download keeps its first publication; re-ingesting the same
    cached download after `dedupe` adds nothing; a changed value is still a new version."""
    from src.database import Database
    db = Database()
    fetch = db.record_fetch('SEC EDGAR', 'companyfacts/CIK1.json', status='OK', raw='{}', raw_ext='json')
    rows = [{'entity': 'ADBE', 'metric': 'xbrl:StockholdersEquity', 'as_of_date': '2008-11-28', 'value': 4410354000.0,
             'unit': 'USD', 'published_at': pub} for pub in ('2011-01-28T05:00:00+00:00', '2009-06-27T05:00:00+00:00',
                                                            '2010-01-23T05:00:00+00:00')]
    assert db.upsert_observations(fetch, rows) == 1
    assert db.upsert_observations(fetch, rows) == 0                       # same cached download again
    assert db.redundant_versions() == []
    with db.connect() as conn:                                            # the first download was a day earlier
        conn.execute("UPDATE observations SET retrieved_at='2026-10-10T21:00:00+00:00' WHERE fetch_id=?",
                     (fetch['fetch_id'],))
    later = db.record_fetch('SEC EDGAR', 'companyfacts/CIK1.json', status='OK', raw='{}', raw_ext='json')
    assert db.upsert_observations(later, rows) == 0                       # new download, same facts
    restated = [dict(rows[0], value=4500000000.0, published_at='2012-01-27T05:00:00+00:00')]
    assert db.upsert_observations(later, restated) == 1                   # a restatement is a new version
    back = [dict(rows[0], published_at='2013-01-25T05:00:00+00:00')]
    assert db.upsert_observations(later, back) == 1                       # back to the old value: not redundant
    assert db.redundant_versions() == []
    earlier = [dict(rows[0], published_at='2009-01-30T05:00:00+00:00')]   # an earlier publication found later
    assert db.upsert_observations(later, earlier) == 1
    assert db.redundant_versions() == []
