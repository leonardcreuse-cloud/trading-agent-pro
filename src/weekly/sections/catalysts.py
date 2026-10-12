#!/usr/bin/env python3
"""
Weekly report section 'catalysts' - Q9 "What catalysts are approaching?" (phase P3.0)

Horizon
  The 10 sessions after s_0. Future sessions are not observed (the session calendar is the SPY bars
  up to s_0) and no exchange-calendar library is configured, so the horizon is expressed in calendar
  dates: (date(s_0), date(s_0) + HORIZON_CALENDAR_DAYS], 15 days = 10 sessions + weekends + a one-day
  holiday margin (pre-declared). Dates are never mapped to session numbers.

Macro (overall): FRED release calendar, rank 1, dates only (FRED gives no time of day)
  GET https://api.stlouisfed.org/fred/release/dates?release_id=<id>&realtime_start=<date(s_0)>
      &include_release_dates_with_no_data=true&file_type=json   (one request per pre-declared release)
  The key is read like src/macro_fred.py (secret_env('FRED_API_KEY')), sent as a query parameter,
  never stored or printed (record_fetch removes it from the logged parameters; errors carry the
  exception type only). Every call is logged with ctx.db.record_fetch(source='FRED') with its raw
  payload, timestamped by the database (requested_at=None: the section never reads the clock and
  never records G as a request time); an identical request stored less than REUSE_HOURS before G
  is reused (budget). A schedule that lists no date after s_0 is never read as "no release": its
  dates, its status and any change computed from it are DATA UNAVAILABLE.
  Point-in-time: FRED does not timestamp schedule entries and has no vintages for release dates, so
  a schedule is admissible at an instant T only from a calendar fetch RETRIEVED at or before T (a
  stored fetch from an earlier run). The calendar retrieved at G (after the cutoff) is listed in the
  table for information only ("not established as known at T_c") and is stored, so that the next
  weekly report has a pre-cutoff calendar. Conclusions (status SCHEDULED, official_fact) come only
  from the calendar known at T_c; changes against the calendar known at T_p are reported when both
  are stored.
  FOMC: release 326 (Summary of Economic Projections) gives the meetings WITH projections only (4 of
  8 per year); every meeting comes from the Federal Reserve Board calendar below.

Official calendars (overall, phase P4.0, pages stored by `python main.py collect`; never downloaded here)
  FOMC meetings: Federal Reserve Board calendar page (rank 1). The schedule known at T_c is the page version
  in force at T_c: the newest stored page whose "Last Update" date (end of day New York) is <= T_c. When
  that page was retrieved at or after T_c the version was still current at T_c (fresh); otherwise its
  freshness is judged by its retrieval date. Unscheduled meetings and notation votes are not schedule items.
  BLS releases (Employment Situation, CPI, PPI, JOLTS, ECI, Real Earnings), with times: the BLS monthly
  release calendars of the months of the horizon. BLS pages carry no version date relied on, so a month
  counts as known at T_c only from a page RETRIEVED at or before T_c (freshness by retrieval date); a
  page retrieved after the cutoff is listed for information only. A release absent from every horizon
  month known at T_c is "no date in the horizon"; a horizon month without a stored page is DATA UNAVAILABLE.

Company (each ticker of ctx.universe)
  - next earnings date: the newest stored yfinance Ticker(t).calendar snapshot (rank 2, unofficial, possibly
    an estimate) RETRIEVED at or before T_c (`collect` stores one daily; this section stores one per run) is
    reported as known at T_c (kind 'aggregator', ESTIMATE: not an issuer announcement). The calendar is also
    tried once at G (logged): with no publication time it is listed for information only. An empty result
    ({}) is DATA UNAVAILABLE, never "no earnings date". Issuer-announced dates in 8-K exhibits are not parsed
    (NOT IMPLEMENTED).
  - PATTERN row (kind 'interpretation', ESTIMATE): from the SEC submissions feed (ctx.filings), the
    periodic filing (10-Q / 10-K) that followed, one year earlier, the year-earlier counterpart of the
    latest periodic filing known at T_c, with the 8-K item 2.02 (results of operations) filed between
    that period end and that filing. Labelled "pattern, not a forecast": no date, direction or impact
    is forecast. Only the latest periodic filing is judged for freshness at the cutoff; the year-earlier
    filings are historical on purpose (fresh=None, no STALE_AT_CUTOFF from them).
Catalysts are dates only: no expected direction, magnitude or price impact is ever stated.
Sections never call the wall clock and never write files (fetch logging goes through ctx.db).
"""

import json
from datetime import date, datetime, timedelta

import requests

from ...common import DATA_UNAVAILABLE, end_of_us_trading_day_utc, redact, secret_env, to_utc_iso
from ...external_sources import (BLS_MONTH_URL, BLS_RELEASES, EARNINGS_BASIS, FOMC_URL, earnings_dates,
                                 parse_bls_month, parse_fomc)
from ..core import LookAheadError, SectionResult, conclude, evidence, unavailable

NAME = 'catalysts'
QUESTIONS = [9]
Q = 9

HORIZON_SESSIONS = 10
HORIZON_CALENDAR_DAYS = 15          # pre-declared: 10 sessions ~ 14 calendar days + 1 holiday margin
REUSE_HOURS = 12                    # identical FRED calendar request reused when stored < 12 h before G
TIMEOUT = 30

FRED_SOURCE, FRED_RANK = 'FRED', 1
SEC_SOURCE, SEC_RANK = 'SEC EDGAR', 1
YF_SOURCE, YF_RANK = 'yfinance', 2
FED_SOURCE, FED_RANK = 'Federal Reserve Board', 1
BLS_SOURCE, BLS_RANK = 'BLS', 1
RELEASE_DATES_URL = 'https://api.stlouisfed.org/fred/release/dates'
CALENDAR_CADENCE = 'daily'          # a schedule retrieved more than 7 days before the cutoff is stale

# Pre-declared releases (all shown, whether or not they have a date in the horizon).
# (FRED release id, name, catalyst type). Retail sales: release 9 (scouting: RSAFS, 2026-10-15).
RELEASES = [
    (10, 'Consumer Price Index', 'macro release'),
    (50, 'Employment Situation', 'macro release'),
    (54, 'Personal Income and Outlays', 'macro release'),
    (53, 'Gross Domestic Product', 'macro release'),
    (9, 'Advance Monthly Sales for Retail and Food Services', 'macro release'),
    (180, 'Unemployment Insurance Weekly Claims Report', 'macro release'),
    # master mission P1: other official releases the macro section reads
    (46, 'Producer Price Index', 'macro release'),
    (13, 'G.17 Industrial Production and Capacity Utilization', 'macro release'),
    (192, 'Job Openings and Labor Turnover Survey', 'macro release'),
    (27, 'New Residential Construction', 'macro release'),
    (51, 'U.S. International Trade in Goods and Services', 'macro release'),
    (326, 'Summary of Economic Projections (FOMC meetings with projections only)', 'FOMC meeting'),
]
FOMC_RELEASE = 326

PERIODIC_FORMS = ('10-Q', '10-K')
PERIODIC_CADENCE = 'quarterly_filing'
COUNTERPART_TOLERANCE_DAYS = 20     # year-earlier counterpart: report date within +/- 20 days
EARNINGS_CROSS_CHECK_DAYS = 10      # yfinance next date vs anniversary of last year's 8-K 2.02 (descriptive)
EARNINGS_8K_LAG_DAYS = 3            # 8-K 2.02 between period end and periodic filing date + 3 days

NO_SESSION_CALENDAR = ('future sessions are not observed (the session calendar is the SPY daily bars up '
                       'to s_0) and no exchange-calendar library is configured: holidays and early closes '
                       'in the horizon are unknown, so catalysts are given as calendar dates, never as '
                       'session numbers')
COLLECT_HINT = ('`python main.py collect` stores these pages; run it daily so that a report has pages from before '
                'its cutoff')
EARNINGS_SOURCES = ('no official earnings calendar is configured (Nasdaq\'s internal API is deliberately not used); '
                    'issuer-announced dates in 8-K exhibits are not parsed (NOT IMPLEMENTED); `python main.py '
                    'collect` stores a daily yfinance calendar snapshot so that a later report can cite one retrieved '
                    'before its cutoff')
CORPORATE_ACTIONS = ('dates of shareholder votes, merger closings and other pending corporate actions sit in '
                     'the text of S-4 / 425 / DEFM14A / DEF 14A documents, which are not parsed (NOT IMPLEMENTED)')


# ---------------------------------------------------------------- helpers

def _d(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def horizon(tm):
    """(start exclusive, end inclusive) calendar dates of the horizon."""
    s0 = _d(tm.s0)
    return s0, s0 + timedelta(days=HORIZON_CALENDAR_DAYS)


def in_horizon(tm, day):
    lo, hi = horizon(tm)
    return lo < _d(day) <= hi


def _fresh(ctx, as_of, cadence, at=None):
    """Freshness flag at the cutoff, or at another instant `at` (the T_p calendar), via ctx.freshness."""
    if as_of is None:
        return None
    status = (ctx.freshness(str(as_of)[:10], cadence, at=at) or {}).get('status')
    return True if status == 'FRESH' else False if status == 'STALE' else None


def _listed_after(dates, lo):
    """Dates of a schedule strictly after `lo` (an empty result is never read as "no release")."""
    return [d for d in (dates or []) if _d(d) > lo]


def _plus_year(day):
    d = _d(day)
    try:
        return d.replace(year=d.year + 1)
    except ValueError:              # 29 February
        return d.replace(year=d.year + 1, day=28)


def _minus_year(day):
    d = _d(day)
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def _weekday(day):
    return _d(day).strftime('%a')


def calendar_endpoint(release_id, realtime_start):
    """Logged endpoint (no key): one per release and realtime_start."""
    return (f'{RELEASE_DATES_URL}?release_id={release_id}&realtime_start={realtime_start}'
            '&include_release_dates_with_no_data=true')


def _parse_dates(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('release_dates'), list):
        return None
    out = set()
    for row in payload['release_dates']:
        try:
            out.add(_d(row.get('date')).isoformat())
        except (TypeError, ValueError, AttributeError):
            continue
    return sorted(out)


# ---------------------------------------------------------------- FRED calendar access

def fetch_calendar(ctx, release_id, http_get=None):
    """
    The FRED calendar of `release_id` from date(s_0) onward, as retrieved at G (reused when an identical
    request was stored < REUSE_HOURS before G). {'status', 'dates', 'fetch', 'reason', 'reused',
    'requested'}.
    """
    since = to_utc_iso(datetime.fromisoformat(ctx.tm.generated_at) - timedelta(hours=REUSE_HOURS))
    return request_calendar(ctx.db, release_id, ctx.tm.s0, since, http_get)


def request_calendar(db, release_id, start, reuse_since=None, http_get=None):
    """
    The FRED calendar of `release_id` from `start` (ISO date) onward, logged as the catalysts section reads it
    back (stored_calendar); an identical request stored after `reuse_since` is reused. Also used by the daily
    `collect` (external_sources.collect_fred_calendars), so that a report finds calendars retrieved before its
    cutoff.
    """
    endpoint = calendar_endpoint(release_id, start)
    out = {'status': DATA_UNAVAILABLE, 'dates': None, 'fetch': None, 'reason': None, 'reused': False,
           'requested': False}
    if reuse_since and hasattr(db, 'latest_fetch') and hasattr(db, 'read_raw'):
        stored = db.latest_fetch(FRED_SOURCE, endpoint, since=reuse_since)
        if stored:
            try:
                dates = _parse_dates(json.loads(db.read_raw(stored['fetch_id'])))
            except (RuntimeError, ValueError, TypeError, OSError):
                dates = None
            if dates is not None:
                return dict(out, status='OK', dates=dates, fetch=stored, reused=True)
    key, problem = secret_env('FRED_API_KEY')
    if problem:
        return dict(out, reason=f'{problem}: no FRED request made')
    params = {'release_id': release_id, 'realtime_start': start,
              'include_release_dates_with_no_data': 'true', 'file_type': 'json', 'api_key': key}
    get = http_get or requests.get
    response, payload, error = None, None, None
    out['requested'] = True
    try:
        response = get(RELEASE_DATES_URL, params=params, timeout=TIMEOUT)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        status = getattr(response, 'status_code', None)
        if status != 200:
            detail = payload.get('error_message') if isinstance(payload, dict) else None
            error = f'FRED HTTP {status}' + (f': {detail}' if detail else '')
        elif _parse_dates(payload) is None:
            error = 'FRED response without a release_dates list'
    except Exception as e:  # noqa: BLE001 - type only: requests errors embed the URL (with the key)
        error = f'{type(e).__name__} (network error contacting FRED)'
    http_status = getattr(response, 'status_code', None)
    try:
        if error:
            error = redact(error)
            fetch = db.record_fetch(FRED_SOURCE, endpoint, params=params, requested_at=None,
                                    status=DATA_UNAVAILABLE, error=error, http_status=http_status)
            return dict(out, fetch=fetch, reason=error)
        raw = getattr(response, 'content', None)
        dates = _parse_dates(payload)
        fetch = db.record_fetch(FRED_SOURCE, endpoint, params=params, requested_at=None,
                                status='OK', http_status=http_status, n_records=len(dates),
                                raw=raw if isinstance(raw, (bytes, str)) else payload)
    except Exception as e:  # noqa: BLE001 - an unlogged result is never used
        return dict(out, reason=redact(f'the FRED call could not be logged ({type(e).__name__}: {e}); '
                                       'its result is not used'))
    return dict(out, status='OK', dates=dates, fetch=fetch)


def stored_calendar(ctx, release_id, instant, cover_from):
    """
    Calendar of `release_id` as known at `instant`: the most recent successful stored fetch RETRIEVED
    at or before `instant` whose realtime_start <= cover_from (so it lists every date after cover_from).
    {'dates', 'fetch', 'realtime_start'} or None.
    """
    db = ctx.db
    if not hasattr(db, 'connect') or not hasattr(db, 'read_raw'):
        return None
    prefix = f'{RELEASE_DATES_URL}?release_id={release_id}&realtime_start='
    limit = to_utc_iso(instant)
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT fetch_id, completed_at, endpoint, raw_sha256 FROM source_fetches WHERE source=? "
            "AND endpoint LIKE ? AND status='OK' AND raw_path IS NOT NULL AND completed_at <= ? "
            "ORDER BY completed_at DESC, fetch_id DESC", (FRED_SOURCE, prefix + '%', limit))]
    for row in rows:
        if not row['endpoint'].startswith(prefix):
            continue
        start = row['endpoint'][len(prefix):].split('&')[0]
        try:
            if _d(start) > _d(cover_from):
                continue
            dates = _parse_dates(json.loads(db.read_raw(row['fetch_id'])))
        except (RuntimeError, ValueError, TypeError, OSError):
            continue
        if dates is None:
            continue
        return {'dates': dates, 'realtime_start': start,
                'fetch': {'fetch_id': row['fetch_id'], 'source': FRED_SOURCE,
                          'retrieved_at': row['completed_at'], 'raw_sha256': row['raw_sha256']}}
    return None


# ---------------------------------------------------------------- yfinance earnings calendar

def yfinance_calendar(ticker):
    """Ticker(t).calendar (network). Kept separate so tests never call it."""
    import yfinance
    return yfinance.Ticker(ticker).calendar


def _earnings_calendar(ctx, ticker, calendar_fn):
    """{'status', 'value', 'reason', 'fetch'}; an empty result is DATA UNAVAILABLE."""
    endpoint = f'yfinance.Ticker({ticker}).calendar'
    value, error = None, None
    try:
        value = calendar_fn(ticker)
    except Exception as e:  # noqa: BLE001 - surfaced as DATA UNAVAILABLE
        error = redact(f'{type(e).__name__}: {e}')[:300]
    empty = not error and (value is None or (hasattr(value, '__len__') and len(value) == 0))
    if empty:
        error = 'yfinance Ticker.calendar returned an empty result ({}): read as unavailable, not as "none"'
    fetch = None
    db = ctx.db
    if hasattr(db, 'record_fetch'):
        try:
            fetch = db.record_fetch(YF_SOURCE, endpoint, requested_at=None,
                                    status=DATA_UNAVAILABLE if error else 'OK', error=error,
                                    raw=None if error else json.dumps(value, default=str, sort_keys=True))
        except Exception as e:  # noqa: BLE001 - an unlogged result is never used
            return {'status': DATA_UNAVAILABLE, 'value': None, 'fetch': None,
                    'reason': redact(f'the yfinance call could not be logged ({type(e).__name__}: {e})')}
    if error:
        return {'status': DATA_UNAVAILABLE, 'value': None, 'reason': error, 'fetch': fetch}
    return {'status': 'OK', 'value': value, 'reason': None, 'fetch': fetch}


def _calendar_dates(value):
    """Earnings dates listed in a yfinance calendar dict (ISO strings)."""
    raw = value.get('Earnings Date') if isinstance(value, dict) else None
    raw = raw if isinstance(raw, (list, tuple)) else [raw] if raw is not None else []
    out = []
    for x in raw:
        try:
            out.append(_d(x.isoformat() if hasattr(x, 'isoformat') else x).isoformat())
        except (TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------- macro

def _changes(new, old):
    added, removed = sorted(set(new) - set(old)), sorted(set(old) - set(new))
    return ('no change' if not added and not removed
            else '; '.join(x for x in (f'added {", ".join(added)}' if added else '',
                                       f'removed {", ".join(removed)}' if removed else '') if x))


def _macro(ctx, res, http_get):
    tm = ctx.tm
    lo, hi = horizon(tm)
    cover_from = lo + timedelta(days=1)
    rows, n_requests, pit_any, prev_any, no_prev = [], 0, False, False, []
    for rid, name, kind in RELEASES:
        label = f'{name} (FRED release {rid})'
        current = fetch_calendar(ctx, rid, http_get)
        n_requests += int(current['requested'])
        pit = stored_calendar(ctx, rid, tm.cutoff, cover_from)
        prev = stored_calendar(ctx, rid, tm.previous_cutoff, cover_from)
        pit_any, prev_any = pit_any or pit is not None, prev_any or prev is not None
        # A schedule listing no date after s_0 is not read as "no release": it gives no date in the
        # horizon, no "none" and no change against another calendar (DATA UNAVAILABLE instead).
        cur_ok = current['status'] == 'OK' and bool(_listed_after(current['dates'], lo))
        pit_ok = pit is not None and bool(_listed_after(pit['dates'], lo))
        prev_ok = prev is not None and bool(_listed_after(prev['dates'], lo))
        cur_in = [d for d in current['dates'] if in_horizon(tm, d)] if cur_ok else None
        cur_next = next((d for d in current['dates'] if _d(d) > hi), None) if cur_ok else None
        pit_in = [d for d in pit['dates'] if in_horizon(tm, d)] if pit_ok else None
        pit_next = next((d for d in pit['dates'] if _d(d) > hi), None) if pit_ok else None
        prev_in = [d for d in prev['dates'] if in_horizon(tm, d)] if prev_ok else None
        after_cut = _changes(cur_in, pit_in) if pit_in is not None and cur_in is not None else None
        since_tp = _changes(pit_in, prev_in) if pit_in is not None and prev_in is not None else None
        status = ('SCHEDULED' if pit_in else 'no date in the horizon') if pit_ok else DATA_UNAVAILABLE
        cur_fetch = current.get('fetch') or {}
        if current['status'] != 'OK':
            g_dates = None
        elif not cur_ok:
            g_dates = 'empty schedule: no date listed after s_0 (not read as "no release")'
        else:
            g_dates = ((', '.join(f'{d} ({_weekday(d)})' for d in cur_in) or 'none')
                       + (f'; next after the horizon {cur_next}' if cur_next else ''))
        rows.append([
            name, rid, kind,
            None if pit_in is None else (', '.join(f'{d} ({_weekday(d)})' for d in pit_in) or 'none'),
            pit_next,
            (f"fetch {pit['fetch']['fetch_id']} retrieved {pit['fetch']['retrieved_at']}"
             + ('' if pit_ok else ' (lists no date after s_0: not usable)') if pit
             else 'not established: no calendar stored at or before the cutoff'),
            g_dates,
            (f"fetch {cur_fetch.get('fetch_id')} retrieved {cur_fetch.get('retrieved_at')}"
             + (' (reused)' if current['reused'] else '') if current['status'] == 'OK'
             else f"unavailable: {current['reason']}"),
            after_cut, since_tp, status, 'not provided by FRED'])

        if pit is None:
            res.add(unavailable('overall', Q, f'{label}: schedule as known at the cutoff',
                                'no FRED release calendar stored at or before the cutoff '
                                f'{tm.cutoff}; FRED does not timestamp schedule entries (no vintages for '
                                'release dates), so a calendar retrieved after the cutoff cannot establish what '
                                'was known at T_c'
                                + (f" (calendar retrieved at {cur_fetch.get('retrieved_at')}, fetch "
                                   f"{cur_fetch.get('fetch_id')}, listed in the table for information only and "
                                   'stored for the next report)' if current['status'] == 'OK'
                                   else f"; current calendar also unavailable: {current['reason']}")))
            continue
        fetch = pit['fetch']
        item = evidence(tm, FRED_SOURCE, FRED_RANK,
                        f'FRED release calendar, release {rid}: dates from {pit["realtime_start"]}: '
                        f'{", ".join(pit["dates"][:12]) or "none listed"}',
                        as_of=fetch['retrieved_at'][:10], retrieved_at=fetch['retrieved_at'],
                        fetch_id=fetch['fetch_id'], fresh=_fresh(ctx, fetch['retrieved_at'], CALENDAR_CADENCE),
                        basis='schedule as stored (retrieved) before the cutoff; FRED gives no publication '
                              'time per schedule entry')
        what = 'FOMC meeting with a Summary of Economic Projections' if rid == FOMC_RELEASE else name
        if pit_in:
            res.add(conclude('overall', Q, f'{what} (FRED release {rid}): SCHEDULED on '
                                           f'{", ".join(pit_in)} (calendar date{"s" if len(pit_in) > 1 else ""}; '
                                           'time of day not provided by FRED; FRED release calendar as stored '
                                           f'at {fetch["retrieved_at"]}, before the cutoff). A scheduled date is '
                                           'not a forecast of the content or of any market reaction.',
                             [item], 'official_fact'))
        elif pit_next:
            res.add(conclude('overall', Q, f'{what} (FRED release {rid}): no date in the horizon '
                                           f'({lo}, {hi}] on the FRED release calendar as stored at '
                                           f'{fetch["retrieved_at"]}; next scheduled date {pit_next}.',
                             [item], 'official_fact'))
        else:
            res.add(unavailable('overall', Q, f'{label}: next scheduled date',
                                f'the FRED calendar stored at {fetch["retrieved_at"]} lists no date after '
                                f'{lo}: an empty schedule is not read as "no release", so no date in the horizon '
                                'and no change against another calendar is derived from it'))
        if pit_ok and prev is None:
            no_prev.append(label)
        elif pit_ok and not prev_ok:
            res.add(unavailable('overall', Q, f'{label}: change of the schedule since T_p',
                                f'the FRED calendar stored at {prev["fetch"]["retrieved_at"]} (the one known at T_p) '
                                f'lists no date after {lo}: an empty schedule is not compared'))
        if since_tp not in (None, 'no change'):
            item_p = evidence(tm, FRED_SOURCE, FRED_RANK,
                              f'FRED release calendar, release {rid}, as stored at {prev["fetch"]["retrieved_at"]}',
                              as_of=prev['fetch']['retrieved_at'][:10], retrieved_at=prev['fetch']['retrieved_at'],
                              fetch_id=prev['fetch']['fetch_id'],
                              fresh=_fresh(ctx, prev['fetch']['retrieved_at'], CALENDAR_CADENCE, tm.previous_cutoff),
                              basis='schedule as stored before the previous cutoff (freshness evaluated at T_p)')
            res.add(conclude('overall', Q, f'{what} (FRED release {rid}): for the horizon ({lo}, {hi}], the '
                                           f'calendar known at T_c differs from the one known at T_p: {since_tp}.',
                             [item, item_p], 'official_fact'))

    res.table(f'Macro release calendar — pre-declared FRED releases, horizon ({lo}, {hi}]',
              ['release', 'FRED release id', 'type', 'dates in horizon (as known at T_c)',
               'next date after the horizon (as known at T_c)', 'schedule known at T_c from',
               'dates in horizon as retrieved at G (after the cutoff, information only)', 'fetch at G',
               'change T_c -> G', 'change T_p -> T_c', 'status at T_c', 'time of day'],
              rows, question=Q,
              note=(f'FRED (rank 1), fred/release/dates with realtime_start = s_0 ({tm.s0}) and '
                    'include_release_dates_with_no_data=true; dates only. Horizon = the '
                    f'{HORIZON_SESSIONS} sessions after s_0 expressed as calendar dates ({HORIZON_CALENDAR_DAYS} '
                    'days, pre-declared): the session calendar beyond s_0 is not available. A schedule counts as '
                    'known at T_c only from a calendar retrieved at or before the cutoff; dates retrieved at G '
                    f'({tm.generated_at}) are shown for information. FRED requests made by this run: {n_requests}.'))
    if not prev_any:
        res.add(unavailable('overall', Q, 'changes of the macro calendar since T_p (added / moved / removed)',
                            f'no FRED release calendar stored at or before the previous cutoff {tm.previous_cutoff}: '
                            'the calendar as known at T_p cannot be reconstructed'))
    else:
        for label in no_prev:
            res.add(unavailable('overall', Q, f'{label}: change of the schedule since T_p',
                                'no FRED calendar of this release (covering the horizon) stored at or before the '
                                f'previous cutoff {tm.previous_cutoff}: the schedule as known at T_p cannot be '
                                'reconstructed'))
    return pit_any


# ---------------------------------------------------------------- official calendars (FOMC, BLS)

def _page_fetches(db, source, endpoint, until=None):
    """Successful stored fetches of `endpoint` with a raw payload, newest first (retrieved <= until if given)."""
    if not hasattr(db, 'connect') or not hasattr(db, 'read_raw'):
        return []
    sql = ("SELECT fetch_id, completed_at, raw_sha256 FROM source_fetches WHERE source=? AND endpoint=? "
           "AND status='OK' AND raw_path IS NOT NULL")
    args = [source, endpoint]
    if until is not None:
        sql += ' AND completed_at <= ?'
        args.append(to_utc_iso(until))
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql + ' ORDER BY completed_at DESC, fetch_id DESC', args)]


def _fetch_ref(source, f):
    return {'fetch_id': f['fetch_id'], 'source': source, 'retrieved_at': f['completed_at'],
            'raw_sha256': f['raw_sha256']}


def fomc_schedule(db, instant=None):
    """
    FOMC calendar in force at `instant` (None: the newest stored page): the newest stored page whose "Last
    Update" date, end of day New York, is <= instant. {'meetings', 'last_update', 'published_at', 'fetch',
    'confirmed'} or None; confirmed: retrieved at or after `instant` with that version (current at `instant`).
    """
    limit = to_utc_iso(instant) if instant else None
    for f in _page_fetches(db, FED_SOURCE, FOMC_URL):
        try:
            last, meetings = parse_fomc(db.read_raw(f['fetch_id']))
        except (RuntimeError, ValueError, TypeError, OSError):
            continue
        if last is None or not meetings:
            continue
        pub = end_of_us_trading_day_utc(last)
        if limit and pub > limit:
            continue
        return {'meetings': [m for m in meetings if not m.get('unscheduled') and not m.get('notation_vote')],
                'last_update': last.isoformat(), 'published_at': pub, 'fetch': _fetch_ref(FED_SOURCE, f),
                'confirmed': bool(limit) and f['completed_at'] >= limit}
    return None


def bls_month_calendar(db, year, month, until=None):
    """Newest stored BLS monthly calendar of year-month (retrieved <= until if given): {'rows', 'fetch'} or None."""
    for f in _page_fetches(db, BLS_SOURCE, BLS_MONTH_URL.format(year, month), until):
        try:
            rows = parse_bls_month(db.read_raw(f['fetch_id']), year, month)
        except (RuntimeError, ValueError, TypeError, OSError):
            continue
        if rows:
            return {'rows': rows, 'fetch': _fetch_ref(BLS_SOURCE, f)}
    return None


def horizon_months(tm):
    """(year, month) of every calendar month holding a day of the horizon."""
    lo, hi = horizon(tm)
    out, d = [], lo + timedelta(days=1)
    while d <= hi:
        if (d.year, d.month) not in out:
            out.append((d.year, d.month))
        d += timedelta(days=1)
    return out


def _meeting_in_horizon(tm, m):
    return in_horizon(tm, m['start']) or in_horizon(tm, m['end'])


def _meeting_text(m):
    days = m['start'] if m['start'] == m['end'] else f"{m['start']} to {m['end']}"
    return days + (' (with a Summary of Economic Projections)' if m.get('sep') else '')


def _fomc(ctx, res, rows):
    tm = ctx.tm
    lo, hi = horizon(tm)
    pit, latest = fomc_schedule(ctx.db, tm.cutoff), fomc_schedule(ctx.db)
    g_info = None
    if latest:
        g_in = [m for m in latest['meetings'] if _meeting_in_horizon(tm, m)]
        g_info = (f"{', '.join(_meeting_text(m) for m in g_in) or 'none'} (page Last Update {latest['last_update']}, "
                  f"retrieved {latest['fetch']['retrieved_at']})")
    if pit is None:
        rows.append(['FOMC meeting', 'Federal Reserve Board (rank 1)', None, 'not on the calendar page', None,
                     'not established', g_info, DATA_UNAVAILABLE])
        reason = ('no Federal Reserve Board calendar page whose "Last Update" date is at or before the cutoff is '
                  'stored' + (f" (newest stored page: Last Update {latest['last_update']}, after the cutoff)"
                              if latest else '') + f'; {COLLECT_HINT}')
        res.add(unavailable('overall', Q, 'FOMC meetings (Federal Reserve Board calendar) as known at the cutoff',
                            reason))
        return
    fetch = pit['fetch']
    fresh = True if pit['confirmed'] else _fresh(ctx, fetch['retrieved_at'], CALENDAR_CADENCE)
    inside = [m for m in pit['meetings'] if _meeting_in_horizon(tm, m)]
    nxt = next((m for m in sorted(pit['meetings'], key=lambda m: m['start']) if _d(m['start']) > hi), None)
    item = evidence(tm, FED_SOURCE, FED_RANK,
                    f"FOMC calendar, page Last Update {pit['last_update']}: "
                    + ', '.join(_meeting_text(m) for m in pit['meetings'] if _d(m['end']) > lo)[:400],
                    as_of=pit['last_update'], published_at=pit['published_at'], retrieved_at=fetch['retrieved_at'],
                    fetch_id=fetch['fetch_id'], fresh=fresh,
                    basis='page version in force at the cutoff: its "Last Update" date, end of day New York'
                          + ('; retrieved at or after the cutoff with that version, so it was current at the cutoff'
                             if pit['confirmed'] else '; retrieved before the cutoff'))
    known_from = (f"page Last Update {pit['last_update']}, fetch {fetch['fetch_id']} retrieved {fetch['retrieved_at']}")
    rows.append(['FOMC meeting', 'Federal Reserve Board (rank 1)',
                 ', '.join(_meeting_text(m) for m in inside) or 'none', 'not on the calendar page',
                 _meeting_text(nxt) if nxt else None, known_from, g_info,
                 'SCHEDULED' if inside else 'no meeting in the horizon'])
    for m in inside:
        res.add(conclude('overall', Q, f'FOMC meeting SCHEDULED on {_meeting_text(m)} (Federal Reserve Board '
                                       f"calendar, page version of {pit['last_update']}). A scheduled meeting is not a "
                                       'forecast of its decision or of any market reaction.', [item], 'official_fact'))
    if not inside:
        if nxt:
            res.add(conclude('overall', Q, f'No FOMC meeting in the horizon ({lo}, {hi}] on the Federal Reserve Board '
                                           f"calendar (page version of {pit['last_update']}); next scheduled meeting "
                                           f'{_meeting_text(nxt)}.', [item], 'official_fact'))
        else:
            res.add(unavailable('overall', Q, 'next FOMC meeting',
                                f"the Federal Reserve Board calendar (page version of {pit['last_update']}) lists no "
                                f'meeting after {hi}: an empty calendar is not read as "no meeting"'))


def _bls(ctx, res, rows):
    tm = ctx.tm
    lo, hi = horizon(tm)
    months = horizon_months(tm)
    known = {ym: bls_month_calendar(ctx.db, *ym, until=tm.cutoff) for ym in months}
    latest = {ym: bls_month_calendar(ctx.db, *ym) for ym in months}
    missing = [f'{y}-{m:02d}' for (y, m), cal in known.items() if cal is None]
    items = {ym: evidence(tm, BLS_SOURCE, BLS_RANK,
                          f"BLS release calendar {ym[0]}-{ym[1]:02d} retrieved {cal['fetch']['retrieved_at']}",
                          as_of=cal['fetch']['retrieved_at'][:10], retrieved_at=cal['fetch']['retrieved_at'],
                          fetch_id=cal['fetch']['fetch_id'], fresh=_fresh(ctx, cal['fetch']['retrieved_at'],
                                                                          CALENDAR_CADENCE),
                          basis='monthly calendar page as stored (retrieved) at or before the cutoff; no version '
                                'date relied on')
             for ym, cal in known.items() if cal}
    def listed(cals, name):
        """[(row, month of the page it came from)] of `name` in the horizon; a release listed by two pages once."""
        out = {}
        for ym, cal in cals.items():
            for r in (cal or {}).get('rows', []):
                if r['release'] == name and in_horizon(tm, r['date']):
                    out.setdefault((r['date'], r['time'], r['reference']), (r, ym))
        return [out[k] for k in sorted(out)]

    for code, name in BLS_RELEASES.items():
        pit = [r for r, _ in listed(known, name)]
        page_of = {r['date']: ym for r, ym in listed(known, name)}
        g = [r for r, _ in listed(latest, name)]
        g_info = ('; '.join(f"{r['date']} {r['time']} ({r['reference']})" for r in g) or 'none') \
            if any(latest.values()) else None
        status = ('SCHEDULED' if pit else 'no date in the horizon' if not missing else
                  'PARTIAL (horizon month not stored)' if any(known.values()) else DATA_UNAVAILABLE)
        rows.append([name, 'BLS (rank 1)',
                     '; '.join(r['date'] for r in pit) or ('none' if not missing else None),
                     '; '.join(f"{r['time']} ET" for r in pit) or None,
                     '; '.join(r['reference'] for r in pit) or None,
                     ', '.join(f"{y}-{m:02d} calendar fetch {cal['fetch']['fetch_id']} retrieved "
                               f"{cal['fetch']['retrieved_at']}" for (y, m), cal in known.items() if cal)
                     or 'not established: no calendar retrieved at or before the cutoff',
                     g_info, status])
        for r in pit:
            ym = page_of[r['date']]
            res.add(conclude('overall', Q, f"BLS {name} for {r['reference']}: SCHEDULED on {r['date']} at {r['time']} "
                                           f"Eastern Time (BLS monthly release calendar retrieved "
                                           f"{known[ym]['fetch']['retrieved_at']}, before the cutoff). A scheduled "
                                           'release is not a forecast of its content or of any market reaction.',
                             [items[ym]], 'official_fact'))
        if not pit and not missing:
            res.add(conclude('overall', Q, f'BLS {name}: no release in the horizon ({lo}, {hi}] on the BLS monthly '
                                           f"release calendars of {', '.join(f'{y}-{m:02d}' for y, m in months)} "
                                           'retrieved before the cutoff.', list(items.values()), 'official_fact'))
    if missing:
        res.add(unavailable('overall', Q, f"BLS release calendar for {', '.join(missing)} (dates and times) as known "
                                          'at the cutoff',
                            'no BLS monthly calendar page of that month retrieved at or before the cutoff is stored '
                            '(BLS pages carry no version date relied on, so a page retrieved after the cutoff is '
                            f'listed for information only); {COLLECT_HINT}'))


def _official_calendars(ctx, res):
    tm = ctx.tm
    lo, hi = horizon(tm)
    rows = []
    _fomc(ctx, res, rows)
    _bls(ctx, res, rows)
    res.table(f'Official calendars — FOMC meetings and BLS releases, horizon ({lo}, {hi}]',
              ['event', 'source', 'dates in horizon (as known at T_c)', 'time (as known at T_c)',
               'reference period / next meeting', 'known at T_c from', 'as stored most recently (information only)',
               'status at T_c'],
              rows, question=Q,
              note='FOMC: Federal Reserve Board calendar page, version in force at the cutoff ("Last Update" date). '
                   'BLS: monthly release calendars (times are Eastern Time), admissible only when retrieved at or '
                   'before the cutoff. For FOMC rows the fifth column is the next meeting after the horizon. Pages '
                   'come from `python main.py collect` (this section downloads nothing).')


# ---------------------------------------------------------------- company

def _filing_item(ctx, feed, f, assess_fresh=True):
    """
    Evidence for one feed row. assess_fresh=False for the year-earlier reference filings of the pattern:
    they are historical on purpose, so freshness at the cutoff does not apply (fresh=None, no
    STALE_AT_CUTOFF); only the latest periodic filing is judged at the cutoff.
    """
    fetch = feed.get('fetch') or {}
    items = f" items {','.join(f['items'])}" if f.get('items') else ''
    cadence = PERIODIC_CADENCE if f['form'] in PERIODIC_FORMS else 'event'
    basis = f.get('published_at_basis')
    if not assess_fresh:
        basis = (f'{basis}; ' if basis else '') + 'historical reference filing: freshness at the cutoff not applicable'
    return evidence(ctx.tm, SEC_SOURCE, SEC_RANK,
                    f"{f['form']}{items} accession {f['accession_number']}, period {f.get('report_date')}, "
                    f"filed {f.get('filing_date')}",
                    as_of=f.get('report_date') or f.get('filing_date'), published_at=f['published_at'],
                    retrieved_at=fetch.get('retrieved_at'), fetch_id=fetch.get('fetch_id'),
                    fresh=_fresh(ctx, f['published_at'], cadence) if assess_fresh else None, basis=basis)


def filing_pattern(tm, filings, truncated=None):
    """
    {'latest', 'anchor', 'next', 'earnings_8k', 'reason'} from submissions-feed rows known at T_c.
    latest: latest periodic filing known at T_c; anchor: its counterpart one year earlier (report
    date within +/- COUNTERPART_TOLERANCE_DAYS); next: the periodic filing that followed the anchor;
    earnings_8k: the first 8-K with item 2.02 filed between next's period end and its filing date + 3 d.
    truncated: ctx.filings(t)['truncated'] (False: the feed lists the whole filing history).
    """
    known = [f for f in filings if f.get('published_at') and to_utc_iso(f['published_at']) <= tm.cutoff]
    periodic = sorted((f for f in known if f.get('form') in PERIODIC_FORMS and f.get('report_date')
                       and f.get('filing_date')), key=lambda f: (f['report_date'], f['published_at']))
    out = {'latest': None, 'anchor': None, 'next': None, 'earnings_8k': None, 'reason': None}
    if not periodic:
        out['reason'] = 'no 10-Q / 10-K known at the cutoff in the submissions feed'
        return out
    latest = max(periodic, key=lambda f: to_utc_iso(f['published_at']))
    out['latest'] = latest
    target = _minus_year(latest['report_date'])
    cands = [f for f in periodic if abs((_d(f['report_date']) - target).days) <= COUNTERPART_TOLERANCE_DAYS]
    if not cands:
        oldest = min((f['filing_date'] for f in known if f.get('filing_date')), default=None)
        older = ''
        if oldest and _d(oldest) > target:
            older = (f'; the feed lists the whole filing history (not truncated) and its oldest filing is {oldest}: '
                     'no filing of that period exists' if truncated is False
                     else f'; its oldest listed filing is {oldest}, so the recent block may not reach back one year')
        out['reason'] = (f'the feed lists no 10-Q / 10-K for a period ending near {target} (one year before '
                         f"{latest['report_date']})" + older)
        return out
    anchor = min(cands, key=lambda f: (abs((_d(f['report_date']) - target).days), f['published_at']))
    out['anchor'] = anchor
    later = [f for f in periodic if f['report_date'] > anchor['report_date']]
    if not later:
        out['reason'] = f"no periodic filing after the {anchor['form']} for the period ended {anchor['report_date']}"
        return out
    nxt = min(later, key=lambda f: (f['report_date'], f['published_at']))
    out['next'] = nxt
    hi = _d(nxt['filing_date']) + timedelta(days=EARNINGS_8K_LAG_DAYS)
    eightk = sorted((f for f in known if f.get('form') == '8-K' and '2.02' in (f.get('items') or [])
                     and f.get('filing_date') and _d(nxt['report_date']) < _d(f['filing_date']) <= hi),
                    key=lambda f: f['filing_date'])
    out['earnings_8k'] = eightk[0] if eightk else None
    return out


def stored_earnings(ctx, ticker):
    """
    Newest stored yfinance calendar snapshot of `ticker` retrieved at or before the cutoff that lists a date
    after s_0: {'dates', 'fetch'} or None.
    """
    lo = horizon(ctx.tm)[0]
    for f in _page_fetches(ctx.db, YF_SOURCE, f'yfinance.Ticker({ticker}).calendar', until=ctx.tm.cutoff):
        try:
            dates = [d for d in earnings_dates(json.loads(ctx.db.read_raw(f['fetch_id']))) if _d(d) > lo]
        except (RuntimeError, ValueError, TypeError, OSError):
            continue
        if dates:
            return {'dates': dates, 'fetch': _fetch_ref(YF_SOURCE, f)}
    return None


def _company(ctx, res, t, calendar_fn):
    tm = ctx.tm
    lo, hi = horizon(tm)
    rows = []
    # next earnings date: a snapshot stored before the cutoff, then the calendar at G (information only)
    snap = stored_earnings(ctx, t)
    yf_next = snap['dates'][0] if snap else None
    if snap:
        fetch, nxt = snap['fetch'], snap['dates'][0]
        inside = in_horizon(tm, nxt)
        rows.append(['next earnings date (as known at T_c)', 'REPORTED', 'yfinance (rank 2, unofficial)',
                     ', '.join(snap['dates']), f"snapshot fetch {fetch['fetch_id']} retrieved {fetch['retrieved_at']}, "
                                               'before the cutoff; no publication time; may be an estimate'])
        item = evidence(tm, YF_SOURCE, YF_RANK, f"yfinance calendar of {t}: Earnings Date {', '.join(snap['dates'])}",
                        as_of=fetch['retrieved_at'][:10], retrieved_at=fetch['retrieved_at'],
                        fetch_id=fetch['fetch_id'], fresh=_fresh(ctx, fetch['retrieved_at'], CALENDAR_CADENCE),
                        basis=EARNINGS_BASIS)
        res.add(conclude(t, Q, f"{t}: next earnings date reported by Yahoo Finance (yfinance, unofficial): {nxt}, "
                               f"{'inside' if inside else 'outside'} the horizon ({lo}, {hi}] (snapshot retrieved "
                               f"{fetch['retrieved_at']}, before the cutoff). It may be an estimate and is not an "
                               'issuer announcement; no direction or impact is implied.',
                         [item], 'aggregator', reason_codes=['ESTIMATE'],
                         resolve='an issuer announcement of the date (8-K or press release)'))
    cal = _earnings_calendar(ctx, t, calendar_fn) if calendar_fn else {
        'status': DATA_UNAVAILABLE, 'value': None, 'fetch': None, 'reason': 'yfinance calendar not queried'}
    if snap:
        rows.append(['next earnings date (retrieved at G, information only)',
                     'REPORTED' if cal['status'] == 'OK' else DATA_UNAVAILABLE, 'yfinance (rank 2, unofficial)',
                     ', '.join(_calendar_dates(cal['value'])) if cal['status'] == 'OK' else None,
                     f"retrieved at G ({(cal['fetch'] or {}).get('retrieved_at')})" if cal['status'] == 'OK'
                     else cal['reason']])
    elif cal['status'] == 'OK':
        dates = _calendar_dates(cal['value'])
        rows.append(['next earnings date', 'REPORTED (not admissible at T_c)', 'yfinance (rank 2, unofficial)',
                     ', '.join(dates) or json.dumps(cal['value'], default=str)[:200],
                     f"retrieved at G ({(cal['fetch'] or {}).get('retrieved_at')}) after the cutoff, no publication "
                     'time, possibly an estimate'])
        res.add(unavailable(t, Q, 'next earnings date (as known at the cutoff)',
                            'the only source answering (yfinance Ticker.calendar, rank 2) was retrieved after the '
                            'cutoff and gives no publication time, so it cannot establish what was known at T_c '
                            f'(listed in the table for information); {EARNINGS_SOURCES}'))
    else:
        rows.append(['next earnings date', DATA_UNAVAILABLE, 'yfinance Ticker.calendar (rank 2)', None, cal['reason']])
        res.add(unavailable(t, Q, 'next earnings date', f"{cal['reason']}; {EARNINGS_SOURCES}"))

    # pattern from the SEC submissions feed
    try:
        feed = ctx.filings(t)
    except LookAheadError:
        raise
    except Exception as e:  # noqa: BLE001 - one company must not stop the section
        feed = {'status': DATA_UNAVAILABLE, 'filings': [], 'fetch': None, 'reason': f'{type(e).__name__}: {e}'}
    if feed.get('status') != 'OK':
        rows.append(['periodic filing pattern (pattern, not a forecast)', DATA_UNAVAILABLE, 'SEC EDGAR (rank 1)',
                     None, feed.get('reason')])
        res.add(unavailable(t, Q, 'periodic filing pattern', f"SEC submissions feed unavailable: {feed.get('reason')}"))
    else:
        p = filing_pattern(tm, feed.get('filings') or [], feed.get('truncated'))
        latest, anchor, nxt, k8 = p['latest'], p['anchor'], p['next'], p['earnings_8k']
        if latest:
            rows.append(['latest periodic filing known at T_c', 'FILED', 'SEC EDGAR (rank 1)',
                         f"{latest['form']} period {latest['report_date']}, filed {latest['filing_date']}",
                         f"published {latest['published_at']} ({latest.get('published_at_basis')})"])
        if nxt is None:
            rows.append(['periodic filing pattern (pattern, not a forecast)', DATA_UNAVAILABLE, 'SEC EDGAR (rank 1)',
                         None, p['reason']])
            res.add(unavailable(t, Q, 'periodic filing pattern (same filing one year earlier)', p['reason']))
        else:
            anniv = _plus_year(nxt['filing_date'])
            anniv_8k = _plus_year(k8['filing_date']) if k8 else None
            inside = in_horizon(tm, anniv) or (anniv_8k is not None and in_horizon(tm, anniv_8k))
            rows.append(['periodic filing pattern (pattern, not a forecast)', 'PATTERN', 'SEC EDGAR (rank 1)',
                         f"one year earlier: {nxt['form']} for the period ended {nxt['report_date']} filed "
                         f"{nxt['filing_date']}" + (f"; 8-K item 2.02 filed {k8['filing_date']}" if k8 else
                                                    '; no 8-K item 2.02 found for that period'),
                         f"same calendar dates one year later: {anniv}" + (f' / {anniv_8k}' if anniv_8k else '')
                         + f" ({'inside' if inside else 'outside'} the horizon ({lo}, {hi}])"])
            if yf_next and anniv_8k:
                gap = abs((_d(yf_next) - _d(anniv_8k)).days)
                rows.append(['cross-check: yfinance date vs one year after last year\'s 8-K item 2.02',
                             'CONSISTENT' if gap <= EARNINGS_CROSS_CHECK_DAYS else 'DIFFERENT',
                             'yfinance (rank 2) vs SEC EDGAR (rank 1) pattern', f'{yf_next} vs {anniv_8k}: {gap} days apart',
                             f'consistent = within {EARNINGS_CROSS_CHECK_DAYS} days; agreement does not make the date '
                             'official, a difference does not make either wrong'])
            used = {id(f): f for f in (latest, anchor, nxt, k8) if f}     # nxt can be latest (annual filer)
            items = [_filing_item(ctx, feed, f, assess_fresh=f is latest) for f in used.values()]
            if nxt is latest:      # annual filer: the filing after last year's counterpart is the latest one
                pattern_text = (f"{t}: pattern, not a forecast: the latest {latest['form']} (period "
                                f"{latest['report_date']}, filed {latest['filing_date']}) is itself the filing that "
                                f"followed its counterpart one year earlier ({anchor['form']}, period "
                                f"{anchor['report_date']}); one year after it is {anniv}, which falls "
                                f"{'inside' if inside else 'outside'} the horizon ({lo}, {hi}]. Past filing dates "
                                "do not set this year's date; no direction or impact is implied.")
                res.add(conclude(t, Q, pattern_text, items, 'interpretation', reason_codes=['ESTIMATE'],
                                 resolve='an issuer announcement of the date (8-K) or an official earnings calendar; '
                                         'a pattern of past filing dates is never a schedule'))
            else:
              res.add(conclude(
                t, Q, f"{t}: pattern, not a forecast: one year earlier, the periodic filing that followed the "
                      f"{anchor['form']} for the period ended {anchor['report_date']} (counterpart of the latest "
                      f"{latest['form']}, period {latest['report_date']}) was the {nxt['form']} for the period ended "
                      f"{nxt['report_date']}, filed on {nxt['filing_date']}"
                      + (f", with an 8-K item 2.02 (results of operations) filed on {k8['filing_date']}" if k8
                         else ', with no 8-K item 2.02 found between that period end and that filing')
                      + f". The same calendar dates one year later ({anniv}" + (f', {anniv_8k}' if anniv_8k else '')
                      + f") fall {'inside' if inside else 'outside'} the horizon ({lo}, {hi}]. Past filing dates do "
                        "not set this year's date; no direction or impact is implied.",
                items, 'interpretation', reason_codes=['ESTIMATE'],
                resolve='an issuer announcement of the date (8-K) or an official earnings calendar; a pattern of '
                        'past filing dates is never a schedule'))
    res.table(f'{t} — company catalysts, horizon ({lo}, {hi}]', ['item', 'status', 'source', 'value', 'note'],
              rows, scope=t, question=Q,
              note='Status vocabulary: SCHEDULED (official calendar), ANNOUNCED (issuer statement in an SEC filing), '
                   'REPORTED (news / yfinance only), PATTERN (past filing dates only, never converted into a '
                   'forecast date), DATA UNAVAILABLE. Issuer-announced dates in 8-K exhibits are not parsed.')


# ---------------------------------------------------------------- section

def build(ctx, http_get=None, calendar_fn=yfinance_calendar, tickers=None):
    """
    http_get: requests.get-compatible callable for FRED (tests); calendar_fn: ticker -> yfinance-like
    calendar dict (tests inject a fake; None skips the call). At most len(RELEASES) FRED requests.
    """
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    lo, hi = horizon(tm)
    res.add(unavailable('overall', Q, f'exchange session calendar for the {HORIZON_SESSIONS} sessions after s_0',
                        NO_SESSION_CALENDAR))
    _macro(ctx, res, http_get)
    _official_calendars(ctx, res)
    for t in (tickers or ctx.universe):
        _company(ctx, res, t, calendar_fn)
    res.add(unavailable('overall', Q, 'pending corporate actions (shareholder votes, merger closings, offerings)',
                        CORPORATE_ACTIONS))
    res.notes.append(f'Horizon ({lo}, {hi}] = the {HORIZON_SESSIONS} sessions after s_0 ({tm.s0}) as calendar dates; '
                     f'cutoff {tm.cutoff}; thresholds {(getattr(ctx, "weekly", None) or {}).get("thresholds_version")} '
                     '(no threshold is used by this section). Catalysts are dates only: no direction, magnitude or '
                     'price impact is forecast, and a scheduled release is not an expectation of its content. '
                     'Peers\' catalysts are not covered.')
    return res
