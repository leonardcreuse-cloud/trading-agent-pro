"""
Freshness alerts (src/freshness.py). SYNTHETIC fetch log and closes in a temporary database.
"""

from datetime import date, datetime, timezone


def at(iso):
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


def test_last_completed_weekday_and_missing_weekdays():
    from src.freshness import last_completed_weekday, weekdays_missing
    assert last_completed_weekday(at('2026-10-15T21:00:00')) == date(2026, 10, 14)    # Thursday, before 21:30 UTC
    assert last_completed_weekday(at('2026-10-15T22:00:00')) == date(2026, 10, 15)
    assert last_completed_weekday(at('2026-10-18T12:00:00')) == date(2026, 10, 16)    # Sunday -> Friday
    assert weekdays_missing(date(2026, 10, 16), date(2026, 10, 19)) == 1               # weekend not counted
    assert weekdays_missing(date(2026, 10, 15), date(2026, 10, 15)) == 0


def test_statuses(monkeypatch):
    from src.database import Database
    from src.freshness import check, summary
    db = Database()

    def fetch(source, when, status='OK'):
        f = db.record_fetch(source, f'{source}-{when}', status=status,
                            raw='x' if status == 'OK' else None, error=None if status == 'OK' else 'HTTP 500')
        with db.connect() as conn:                    # date the synthetic download (both instants, in order)
            conn.execute('UPDATE source_fetches SET requested_at=?, completed_at=? WHERE fetch_id=?',
                         (when, when, f['fetch_id']))
        return f
    sec = fetch('SEC EDGAR', '2026-10-15T21:10:00+00:00')
    yf = fetch('yfinance', '2026-10-15T21:20:00+00:00')
    db.upsert_observations(yf, [{'entity': 'SPY', 'metric': 'close_raw', 'as_of_date': '2026-10-15', 'value': 1.0,
                                 'published_at': '2026-10-15T21:00:00+00:00'}])
    cb = fetch('Cboe delayed quotes', '2026-10-15T21:15:00+00:00')
    db.upsert_observations(cb, [{'entity': 'SPY', 'metric': 'close', 'as_of_date': '2026-10-09', 'value': 1.0,
                                 'published_at': '2026-10-10T05:00:00+00:00'}])     # 5 weekdays behind
    fetch('FRED', '2026-10-12T21:00:00+00:00')
    fetch('FRED', '2026-10-15T21:05:00+00:00', status='DATA UNAVAILABLE')
    rows = {r['source']: r for r in check(db, now=at('2026-10-15T22:00:00'))}
    assert rows['SEC EDGAR']['status'] == 'OK' and rows['yfinance']['status'] == 'OK'
    assert rows['yfinance']['sessions_missing'] == 0
    assert rows['Cboe']['status'] == 'STALE' and rows['Cboe']['sessions_missing'] == 4
    assert rows['FRED']['status'] == 'STALE' and rows['FRED']['fetch_age_h'] == 73.0
    assert rows['FRED']['failures_since_ok'] == 1
    assert 'Cboe: STALE' in summary(list(rows.values())) and 'SEC' not in summary(list(rows.values()))
