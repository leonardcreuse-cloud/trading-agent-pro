"""
Freshness alerts for the sources the signal, PT1 and the reports depend on (consigne of 2026-10-14, phase 0.3;
rule R8).

For each watched source:
- **fetch age**: hours since its last successful download (source_fetches). The nightly run downloads every one of
  them each day (SEC company facts are cached 12 h and the ticker file 24 h), so more than MAX_FETCH_AGE_H hours
  means at least one night was missed.
- **price lag** (yfinance, Cboe): completed weekdays missing after the last stored close of the reference ticker
  (SPY). A session counts as completed from 21:30 UTC, half an hour after the most conservative close. One missing
  weekday is tolerated (a market holiday).

Statuses: OK, STALE (a limit exceeded), NEVER (no successful download stored).
`python main.py freshness` prints them and exits with 1 when any source is not OK. scripts/daily_run.py runs it
every night, so a stale source turns the run's result to 1 (Task Scheduler "Last Run Result", last_run.json).
Read-only.
"""

from datetime import date, datetime, time, timedelta, timezone

from .common import to_utc_iso, utc_now_iso
from .database import Database

MAX_FETCH_AGE_H = 48
MAX_SESSION_LAG = 1
SESSION_DONE_UTC = time(21, 30)
REFERENCE_TICKER = 'SPY'
WATCHED = (('SEC EDGAR', 'SEC EDGAR', None),
           ('yfinance', 'yfinance', 'close_raw'),
           ('Cboe', 'Cboe delayed quotes', 'close'),
           ('FRED', 'FRED', None))


def _dt(iso):
    return datetime.fromisoformat(iso.replace('Z', '+00:00'))


def last_completed_weekday(now):
    """The last weekday whose session is complete at `now` (from 21:30 UTC on that day)."""
    day = now.date()
    while day.weekday() >= 5 or datetime.combine(day, SESSION_DONE_UTC, tzinfo=timezone.utc) > now:
        day -= timedelta(days=1)
    return day


def weekdays_missing(last_stored, expected):
    """Weekdays after last_stored up to and including expected."""
    n, day = 0, last_stored + timedelta(days=1)
    while day <= expected:
        n += day.weekday() < 5
        day += timedelta(days=1)
    return n


def check(db=None, now=None):
    """
    [{source, status, last_ok, fetch_age_h, failures_since_ok, last_close, sessions_missing, problems}], from the
    downloads and observations stored at or before `now` (default: the current instant), so that a report shows the
    freshness as it was at its cutoff.
    """
    db = db or Database()
    now_iso = to_utc_iso(now) or utc_now_iso()
    now = _dt(now_iso)
    expected = last_completed_weekday(now)
    out = []
    with db.connect() as conn:
        for name, source, metric in WATCHED:
            last_ok = conn.execute("SELECT MAX(completed_at) FROM source_fetches WHERE source=? AND status='OK' "
                                   "AND completed_at <= ?", (source, now_iso)).fetchone()[0]
            row = {'source': name, 'status': 'OK', 'last_ok': last_ok, 'fetch_age_h': None, 'failures_since_ok': 0,
                   'last_close': None, 'sessions_missing': None, 'problems': []}
            if not last_ok:
                row.update(status='NEVER', problems=['no successful download stored'])
                out.append(row)
                continue
            row['fetch_age_h'] = round((now - _dt(last_ok)).total_seconds() / 3600, 1)
            row['failures_since_ok'] = conn.execute(
                "SELECT COUNT(*) FROM source_fetches WHERE source=? AND status!='OK' AND completed_at > ? "
                "AND completed_at <= ?", (source, last_ok, now_iso)).fetchone()[0]
            if row['fetch_age_h'] > MAX_FETCH_AGE_H:
                row['problems'].append(f"last successful download {row['fetch_age_h']} h ago "
                                       f"(limit {MAX_FETCH_AGE_H} h)")
            if metric:
                last = conn.execute("SELECT MAX(as_of_date) FROM observations WHERE source=? AND entity=? AND "
                                    "metric=? AND retrieved_at <= ?", (source, REFERENCE_TICKER, metric,
                                                                      now_iso)).fetchone()[0]
                row['last_close'] = last
                if not last:
                    row['problems'].append(f'no {REFERENCE_TICKER} close stored')
                else:
                    row['sessions_missing'] = weekdays_missing(date.fromisoformat(last[:10]), expected)
                    if row['sessions_missing'] > MAX_SESSION_LAG:
                        row['problems'].append(f"{REFERENCE_TICKER}: last close {last[:10]}, {row['sessions_missing']} "
                                               f"completed weekdays missing up to {expected} (limit {MAX_SESSION_LAG})")
            if row['problems']:
                row['status'] = 'STALE'
            out.append(row)
    return out


def summary(rows):
    bad = [r for r in rows if r['status'] != 'OK']
    return 'all sources fresh' if not bad else '; '.join(f"{r['source']}: {r['status']} ({', '.join(r['problems'])})"
                                                         for r in bad)
