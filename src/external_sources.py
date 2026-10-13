#!/usr/bin/env python3
"""
External sources (phase P4.0) - collection layer for the sources opened by the network change of
2026-10-11. `python main.py collect` downloads them; the weekly report reads what was stored, as
known at its cutoff. Nothing here invents a value: a source that cannot be read is logged as a
DATA UNAVAILABLE fetch and its readers report it unavailable.

Every call goes through Database.record_fetch (raw payload kept, SHA-256) and every value through
upsert_observations with an explicit published_at and its basis:

  source (rank)              data                                  published_at (basis)
  CFTC (1)                   Commitments of Traders: TFF futures    release instant: Friday 15:30 New York
                             (E-mini S&P 500 / Nasdaq-100, 10-year  after the Tuesday report date; Monday
                             note, VIX futures, USD index) and      (next business day) when a U.S. federal
                             disaggregated (WTI, gold, copper)      holiday falls Wednesday-Friday
  FINRA (1)                  equity short interest per company      dissemination: 7 business days after the
                                                                    settlement date (federal holidays skipped),
                                                                    end of day New York; a revised row: unknown
                                                                    (retrieval time)
  Cboe (1)                   daily put/call ratios (Cboe-listed     end of day New York of the session
                             volume only, not the whole market)
  Federal Reserve Board (1)  FOMC meeting calendar                  end of the day printed as "Last Update" on
                                                                    the page (version date)
  BLS (1)                    release schedules with times (per-     unknown (retrieval time): no version date
                             release pages + monthly calendars)     relied on
  Federal Register (1)       documents of BIS, OFAC, USTR and       publication date 06:00 New York (documents
                             presidential documents                 on public inspection: retrieval time)
  GPR index (2)              Caldara-Iacoviello daily geopolitical  HTTP Last-Modified of the file version
                             risk index (academic, newspaper-based)
  GDELT (3)                  daily event counts (automated coding   12:00 UTC the day after the file date
                             of news: not a record of events)       (daily file posted early that day)
  yfinance (2)               option chain snapshot per company      unknown (retrieval time); see weekly
                             (unofficial); earnings calendar        positioning / catalysts sections for
                             snapshot (date possibly an estimate)   admissibility

Terms of use: CFTC, FINRA, Federal Reserve, BLS and Federal Register publish public data; Cboe and
Yahoo restrict automated use and redistribution (personal research use only, never redistributed);
GDELT asks for citation; the GPR index asks for citation of Caldara and Iacoviello (2022).
Nasdaq's internal calendar API and OCC (anti-bot protection) are deliberately NOT used.
The keyed BLS, BEA and EIA APIs (phase P4.1) are in agency_apis.py and run from collect_all.
"""

import io
import json
import os
import re
import time
import zipfile
from datetime import date, datetime, time as dtime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError, ProxyError, Timeout

from .common import DATA_UNAVAILABLE, end_of_us_trading_day_utc, redact, to_utc_iso, utc_now_iso
from .database import Database

NEW_YORK = ZoneInfo('America/New_York')
DEFAULT_TIMEOUT = 45
RETRY_PAUSE = 2.0                 # seconds before the single retry of a dropped connection
RATE_LIMIT_PAUSES = (15, 30, 60)  # seconds before each retry of an HTTP 429 (a server Retry-After, capped, wins)
RATE_LIMIT_MAX_WAIT = 120
MIN_INTERVAL = {'publicreporting.cftc.gov': 1.0, 'api.finra.org': 1.0, 'www.cboe.com': 1.0, 'cdn.cboe.com': 1.5,
                'data.gdeltproject.org': 2.0, 'www.bls.gov': 1.0, 'api.bls.gov': 1.0, 'apps.bea.gov': 1.0}
_LAST_CALL = {}

# ---------------------------------------------------------------- calendars of business days

_HOLIDAYS = {}


def federal_holidays(year):
    """U.S. federal holidays observed in `year` (pandas calendar; used for publication bounds only)."""
    if year not in _HOLIDAYS:
        from pandas.tseries.holiday import USFederalHolidayCalendar
        days = USFederalHolidayCalendar().holidays(date(year, 1, 1), date(year, 12, 31))
        _HOLIDAYS[year] = {d.date() for d in days}
    return _HOLIDAYS[year]


def is_business_day(d):
    return d.weekday() < 5 and d not in federal_holidays(d.year)


def add_business_days(d, n):
    while n > 0:
        d += timedelta(days=1)
        if is_business_day(d):
            n -= 1
    return d


def new_york_instant(d, hour, minute=0):
    return to_utc_iso(datetime.combine(d, dtime(hour, minute), tzinfo=NEW_YORK))


def cot_release(report_date):
    """
    Conservative release instant of a COT report dated Tuesday `report_date`: Friday 15:30 New York;
    when a federal holiday falls between Wednesday and Friday, the next business day after Friday.
    """
    friday = report_date + timedelta(days=3)
    day = friday
    if any(report_date < h <= friday for h in federal_holidays(report_date.year)
           | federal_holidays(friday.year)):
        day = add_business_days(friday, 1)
    return new_york_instant(day, 15, 30)


def finra_dissemination(settlement):
    """FINRA short interest publication bound: 7 business days after settlement, end of day New York."""
    return end_of_us_trading_day_utc(add_business_days(settlement, 7))


# ---------------------------------------------------------------- HTTP with provenance

def user_agent():
    contact = os.getenv('SEC_USER_AGENT', '').strip()
    return f'trading-agent-pro research ({contact})' if contact else 'trading-agent-pro research'


def _throttle(url):
    host = url.split('/')[2]
    wait = MIN_INTERVAL.get(host, 0.5) - (time.monotonic() - _LAST_CALL.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL[host] = time.monotonic()


def endpoint_of(url, params=None, body=None):
    out = url + ('?' + urlencode(sorted(params.items())) if params else '')
    return out + ('#' + json.dumps(body, sort_keys=True) if body is not None else '')


def _rate_limit_wait(response, attempt):
    """Seconds to wait after an HTTP 429: the server's Retry-After (seconds, capped) or the next fixed pause."""
    try:
        return min(max(float(response.headers.get('Retry-After')), 1.0), RATE_LIMIT_MAX_WAIT)
    except (TypeError, ValueError):
        return RATE_LIMIT_PAUSES[attempt]


def _send(http, url, params, body, hdrs):
    """One GET / POST, retried once after a dropped connection or a timeout (never after a proxy refusal)."""
    for attempt in range(2):
        _throttle(url)
        try:
            if body is not None:
                return http.post(url, json=body, headers={**hdrs, 'Accept': 'application/json'},
                                 timeout=DEFAULT_TIMEOUT)
            return http.get(url, params=params, headers=hdrs, timeout=DEFAULT_TIMEOUT)
        except (RequestsConnectionError, Timeout) as e:
            if attempt or isinstance(e, ProxyError):
                raise
            time.sleep(RETRY_PAUSE)


def _request(http, url, params, body, hdrs):
    """_send, and after an HTTP 429 (rate limit) wait and send again, at most len(RATE_LIMIT_PAUSES) times; the
    last response is returned whatever its status."""
    for attempt in range(len(RATE_LIMIT_PAUSES) + 1):
        response = _send(http, url, params, body, hdrs)
        if getattr(response, 'status_code', None) != 429 or attempt == len(RATE_LIMIT_PAUSES):
            return response
        time.sleep(_rate_limit_wait(response, attempt))


def http_fetch(db, source, url, *, params=None, body=None, binary=False, raw_ext='json', raw=None,
               session=None, headers=None):
    """
    One HTTP call, logged. Returns {'status', 'content' (bytes or text), 'fetch', 'reason',
    'headers'}. `raw` (callable content -> payload) chooses what is stored as raw payload (default:
    the content itself); the stored payload must be what the values were parsed from.
    """
    endpoint = endpoint_of(url, params, body)
    requested_at = utc_now_iso()
    http = session or requests
    hdrs = {'User-Agent': user_agent(), 'Accept': '*/*', **(headers or {})}
    response = None
    try:
        response = _request(http, url, params, body, hdrs)
        if response.status_code != 200:
            raise RuntimeError(f'HTTP {response.status_code}')
    except Exception as e:  # noqa: BLE001 - recorded, surfaced as DATA UNAVAILABLE
        reason = redact(f'{type(e).__name__}: {e}')
        if 'CONNECT' in reason or 'ProxyError' in reason or 'Tunnel' in reason:
            reason += ' (host refused by the network policy of this environment)'
        fetch = db.record_fetch(source, endpoint, requested_at=requested_at, status=DATA_UNAVAILABLE,
                                http_status=getattr(response, 'status_code', None), error=reason)
        return {'status': DATA_UNAVAILABLE, 'content': None, 'fetch': fetch, 'reason': reason, 'headers': {}}
    content = response.content if binary else response.text
    payload = raw(content) if raw else content
    fetch = db.record_fetch(source, endpoint, requested_at=requested_at, status='OK',
                            http_status=response.status_code, raw=payload, raw_ext=raw_ext)
    return {'status': 'OK', 'content': content, 'fetch': fetch, 'reason': None,
            'headers': dict(response.headers)}


def keep_stored_publication(db, source, rows):
    """
    A row equal to the latest stored version of the same observation (same value; for an event, same text)
    keeps that version's publication time and basis, so it is not stored again when only the publication
    estimate moved: a file served with another Last-Modified, a document dated in the future and clamped to
    each retrieval, a table re-dated by a later release. Rows are updated in place and returned.
    """
    latest = {}
    with db.connect() as conn:
        for key in {(r['entity'], r['metric']) for r in rows}:
            for row in conn.execute('''SELECT as_of_date, value, value_text, published_at, published_at_basis
                                       FROM observations WHERE source=? AND entity=? AND metric=?
                                       ORDER BY retrieved_at, fetch_id''', (source, *key)):
                event = row['value_text'] if row['value'] is None else ''
                latest[(*key, row['as_of_date'], event)] = dict(row)
    for r in rows:
        value = r.get('value')
        event = r.get('value_text') if value is None else ''
        prev = latest.get((r['entity'], r['metric'], str(r['as_of_date'])[:10], event))
        if prev is not None and (value is None or prev['value'] == float(value)):
            r['published_at'], r['published_at_basis'] = prev['published_at'], prev['published_at_basis']
    return rows


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _result(name, status, stored=0, reason=None, **extra):
    return {'collector': name, 'status': status, 'stored': stored, 'reason': reason, **extra}


# ---------------------------------------------------------------- CFTC Commitments of Traders

COT_SOURCE = 'CFTC'
COT_DATASETS = {'tff': 'gpe5-46if', 'disaggregated': '72hh-3qpy'}
COT_URL = 'https://publicreporting.cftc.gov/resource/{}.json'
COT_CONTRACTS = {
    '13874A': ('E-mini S&P 500 (CME)', 'tff'),
    '209742': ('E-mini Nasdaq-100 (CME)', 'tff'),
    '043602': ('10-year Treasury note (CBOT)', 'tff'),
    '1170E1': ('VIX futures (CFE)', 'tff'),
    '098662': ('U.S. dollar index (ICE)', 'tff'),
    '067651': ('WTI crude oil (NYMEX)', 'disaggregated'),
    '088691': ('Gold (COMEX)', 'disaggregated'),
    '085692': ('Copper (COMEX)', 'disaggregated'),
}
# (metric, long field, short field) per dataset; net = long - short, in contracts
COT_GROUPS = {
    'tff': [('leveraged_funds_net', 'lev_money_positions_long', 'lev_money_positions_short'),
            ('asset_managers_net', 'asset_mgr_positions_long', 'asset_mgr_positions_short'),
            ('dealers_net', 'dealer_positions_long_all', 'dealer_positions_short_all')],
    'disaggregated': [('managed_money_net', 'm_money_positions_long_all', 'm_money_positions_short_all'),
                      ('producers_net', 'prod_merc_positions_long', 'prod_merc_positions_short')],
}
COT_BASIS = ('CFTC release schedule: Friday 15:30 New York after the Tuesday report date; next business '
             'day when a federal holiday falls Wednesday-Friday (conservative)')


def cot_rows(records, dataset):
    """Observation rows from CFTC Socrata records (one record = one contract, one report date)."""
    rows = []
    for r in records:
        code = (r.get('cftc_contract_market_code') or '').strip()
        day = (r.get('report_date_as_yyyy_mm_dd') or '')[:10]
        if code not in COT_CONTRACTS or not day:
            continue
        pub = cot_release(date.fromisoformat(day))
        base = {'entity': f'COT:{code}', 'as_of_date': day, 'published_at': pub,
                'published_at_basis': COT_BASIS, 'unit': 'contracts'}
        oi = _num(r.get('open_interest_all'))
        if oi is not None:
            rows.append({**base, 'metric': 'open_interest', 'value': oi})
        for metric, lf, sf in COT_GROUPS[dataset]:
            lo, sh = _num(r.get(lf)), _num(r.get(sf))
            if lo is not None and sh is not None:
                rows.append({**base, 'metric': metric, 'value': lo - sh})
    return rows


def collect_cot(db, since):
    stored, problems = 0, []
    for dataset, ident in COT_DATASETS.items():
        codes = [c for c, (_, ds) in COT_CONTRACTS.items() if ds == dataset]
        where = (f"report_date_as_yyyy_mm_dd >= '{since.isoformat()}T00:00:00.000' AND "
                 f"cftc_contract_market_code in ({', '.join(repr(c) for c in codes)})")
        params = {'$where': where, '$order': 'report_date_as_yyyy_mm_dd', '$limit': 5000}
        got = http_fetch(db, COT_SOURCE, COT_URL.format(ident), params=params)
        if got['status'] != 'OK':
            problems.append(f'{dataset}: {got["reason"]}')
            continue
        try:
            records = json.loads(got['content'])
        except ValueError:
            problems.append(f'{dataset}: response is not JSON')
            continue
        stored += db.upsert_observations(got['fetch'], cot_rows(records, dataset))
    return _result('cftc_cot', 'OK' if not problems else DATA_UNAVAILABLE, stored, '; '.join(problems) or None)


# ---------------------------------------------------------------- FINRA short interest

FINRA_SOURCE = 'FINRA'
FINRA_URL = 'https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest'
FINRA_BASIS = ('FINRA dissemination schedule: 7 business days after the settlement date (federal holidays '
               'skipped), end of day New York (conservative)')


def finra_rows(ticker, records):
    rows = []
    for r in records:
        if (r.get('symbolCode') or '').upper() != ticker.upper() or not r.get('settlementDate'):
            continue
        settle = date.fromisoformat(r['settlementDate'][:10])
        revised = bool(r.get('revisionFlag'))
        base = {'entity': ticker, 'as_of_date': settle.isoformat(),
                'published_at': None if revised else finra_dissemination(settle),
                'published_at_basis': ('revised row: revision time unknown (retrieval time)' if revised
                                       else FINRA_BASIS)}
        for metric, field, unit in (('short_interest_shares', 'currentShortPositionQuantity', 'shares'),
                                    ('short_interest_days_to_cover', 'daysToCoverQuantity', 'days'),
                                    ('short_interest_avg_daily_volume', 'averageDailyVolumeQuantity', 'shares')):
            v = _num(r.get(field))
            if v is not None:
                rows.append({**base, 'metric': metric, 'value': v, 'unit': unit})
    return rows


def collect_finra(db, tickers):
    stored, problems = 0, []
    for t in tickers:
        body = {'limit': 5000, 'compareFilters': [{'compareType': 'EQUAL', 'fieldName': 'symbolCode',
                                                    'fieldValue': t.upper()}]}
        got = http_fetch(db, FINRA_SOURCE, FINRA_URL, body=body)
        if got['status'] != 'OK':
            problems.append(f'{t}: {got["reason"]}')
            continue
        try:
            records = json.loads(got['content'])
        except ValueError:
            problems.append(f'{t}: response is not JSON')
            continue
        stored += db.upsert_observations(got['fetch'], finra_rows(t, records))
    return _result('finra_short_interest', 'OK' if not problems else DATA_UNAVAILABLE, stored,
                   '; '.join(problems) or None)


# ---------------------------------------------------------------- Cboe daily put/call ratios

CBOE_SOURCE = 'Cboe'
CBOE_URL = 'https://www.cboe.com/markets/us/options/market-statistics/daily'
CBOE_RATIOS = {
    'TOTAL PUT/CALL RATIO': 'put_call_total',
    'INDEX PUT/CALL RATIO': 'put_call_index',
    'EQUITY PUT/CALL RATIO': 'put_call_equity',
    'EXCHANGE TRADED PRODUCTS PUT/CALL RATIO': 'put_call_etp',
    'SPX + SPXW PUT/CALL RATIO': 'put_call_spx',
    'CBOE VOLATILITY INDEX (VIX) PUT/CALL RATIO': 'put_call_vix',
}
CBOE_BASIS = 'Cboe end-of-day market statistics: midnight New York after the session (conservative)'


def parse_cboe_daily(html):
    """(session date, {metric: value}) from the Cboe daily statistics page, or (None, {})."""
    text = html.replace('\\"', '"')
    m = re.search(r'"selectedDate"\s*:\s*"(\d{4}-\d{2}-\d{2})"', text)
    ratios = {}
    for name, value in re.findall(r'\{"name":"([^"]+PUT/CALL RATIO)","value":"([0-9.]+)"\}', text):
        if name in CBOE_RATIOS and CBOE_RATIOS[name] not in ratios:
            ratios[CBOE_RATIOS[name]] = float(value)
    return (m.group(1) if m else None), ratios


def _cboe_excerpt(html):
    day, ratios = parse_cboe_daily(html)
    return json.dumps({'selectedDate': day, 'ratios': ratios,
                       'note': 'excerpt of the Cboe daily statistics page (selectedDate and put/call ratios)'})


def collect_cboe(db, days):
    """days: session dates to request (?dt=YYYY-MM-DD). Already stored sessions are skipped."""
    stored, problems, seen = 0, [], set()
    have = {d for d, _ in db.series('CBOE', 'put_call_total', source=CBOE_SOURCE)}
    for d in days:
        if d.isoformat() in have:
            continue
        got = http_fetch(db, CBOE_SOURCE, CBOE_URL, params={'dt': d.isoformat()}, raw=_cboe_excerpt)
        if got['status'] != 'OK':
            problems.append(f'{d}: {got["reason"]}')
            break                     # a refused host refuses every date
        day, ratios = parse_cboe_daily(got['content'])
        if day != d.isoformat() or not ratios:
            continue                  # holiday or page without statistics for that date: nothing stored
        if day in seen:
            continue
        seen.add(day)
        stored += db.upsert_observations(got['fetch'], [
            {'entity': 'CBOE', 'metric': k, 'as_of_date': day, 'value': v, 'unit': 'ratio',
             'published_at': end_of_us_trading_day_utc(day), 'published_at_basis': CBOE_BASIS}
            for k, v in ratios.items()])
    return _result('cboe_put_call', 'OK' if not problems else DATA_UNAVAILABLE, stored,
                   '; '.join(problems) or None)


# ---------------------------------------------------------------- Cboe delayed daily history (second price source)

CBOE_HISTORY_SOURCE = 'Cboe delayed quotes'
CBOE_HISTORY_URL = 'https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/{}.json'
CBOE_HISTORY_BASIS = ('Cboe delayed daily bar (split-adjusted as served): public after the session; conservative '
                      'end of the US trading day (05:00 UTC the next day)')
CBOE_HISTORY_OVERLAP_DAYS = 45      # routine runs re-read this many days before the last stored bar (late fixes)


def cboe_history_rows(ticker, payload, start):
    """close / volume rows dated >= start (ISO) from a Cboe historical payload; malformed or non-positive values
    are skipped, never filled. Values are revisable: Cboe re-adjusts its history after a split."""
    rows = []
    for r in (payload or {}).get('data') or []:
        day = str(r.get('date') or '')[:10]
        if len(day) != 10 or day < start:
            continue
        for metric, unit in (('close', 'USD'), ('volume', 'shares')):
            v = _num(r.get(metric))
            if v is not None and v > 0:
                rows.append({'entity': ticker, 'metric': metric, 'as_of_date': day, 'value': v, 'unit': unit,
                             'value_revisable': 1, 'published_at': end_of_us_trading_day_utc(day),
                             'published_at_basis': CBOE_HISTORY_BASIS})
    return rows


def collect_cboe_history(db, tickers, since):
    """Daily close / volume of each ticker since `since` (first run) or since the last stored bar minus
    CBOE_HISTORY_OVERLAP_DAYS; the stored raw payload is the excerpt the rows were parsed from."""
    stored, problems = 0, []
    for t in tickers:
        have = db.series(t, 'close', source=CBOE_HISTORY_SOURCE)
        start = since if not have else max(since, date.fromisoformat(have[-1][0]) - timedelta(days=CBOE_HISTORY_OVERLAP_DAYS))
        start_iso = start.isoformat()
        parsed = {}

        def excerpt(content, start_iso=start_iso, parsed=parsed):
            try:
                data = json.loads(content)
            except ValueError:
                parsed['error'] = 'payload is not JSON'
                return content[:2000]
            parsed['payload'] = {'symbol': data.get('symbol'), 'timestamp': data.get('timestamp'),
                                 'data': [r for r in data.get('data') or [] if str(r.get('date') or '')[:10] >= start_iso]}
            return json.dumps(parsed['payload'])
        got = http_fetch(db, CBOE_HISTORY_SOURCE, CBOE_HISTORY_URL.format(t), raw=excerpt)
        if got['status'] != 'OK':
            problems.append(f"{t}: {got['reason']}")
            if 'network policy' in (got['reason'] or ''):
                break                     # a refused host refuses every ticker
            continue
        if 'payload' not in parsed:
            problems.append(f"{t}: {parsed.get('error', 'unreadable payload')}")
            continue
        rows = cboe_history_rows(t, parsed['payload'], start_iso)
        if not rows:
            problems.append(f'{t}: no bar since {start_iso}')
            continue
        stored += db.upsert_observations(got['fetch'], rows)
    return _result('cboe_price_history', 'OK' if not problems else DATA_UNAVAILABLE, stored,
                   '; '.join(problems[:5]) or None)


# ---------------------------------------------------------------- Federal Reserve FOMC calendar

FED_SOURCE = 'Federal Reserve Board'
FOMC_URL = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'
MONTHS = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july',
                                      'august', 'september', 'october', 'november', 'december'], 1)}


def _month(name):
    name = name.strip().lower().rstrip('.')
    for full, i in MONTHS.items():
        if full.startswith(name[:3]):
            return i
    raise ValueError(f'unknown month {name!r}')


def parse_fomc(html):
    """
    (last_update date or None, [meeting]) where meeting = {'start', 'end', 'sep', 'label'}; one per
    row of each '<year> FOMC Meetings' panel. 'sep': marked with * (Summary of Economic Projections).
    """
    m = re.search(r'Last Update:\s*(?:<[^>]+>\s*)*([A-Z][a-z]+ \d{1,2}, \d{4})', html)
    last = datetime.strptime(m.group(1), '%B %d, %Y').date() if m else None
    heads = list(re.finditer(r'<h4><a id="\d+">(\d{4}) FOMC Meetings</a></h4>', html))
    meetings = []
    for i, h in enumerate(heads):
        year = int(h.group(1))
        block = html[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(html)]
        for month, days in re.findall(r'fomc-meeting__month[^>]*><strong>([^<]+)</strong></div>\s*'
                                      r'<div class="fomc-meeting__date[^>]*>([^<]+)</div>', block):
            label = f'{month.strip()} {days.strip()}'
            sep = '*' in days
            nums = re.findall(r'\d+', days)
            if not nums:
                continue
            months = [x for x in re.split(r'[/-]', month) if x.strip()]
            m1 = _month(months[0])
            m2 = _month(months[-1]) if len(months) > 1 else m1
            d1, d2 = int(nums[0]), int(nums[-1])
            start = date(year, m1, d1)
            end = date(year + (1 if m2 < m1 else 0), m2, d2)
            meetings.append({'start': start.isoformat(), 'end': end.isoformat(), 'sep': sep, 'label': label,
                             'unscheduled': 'unscheduled' in days.lower(),
                             'notation_vote': 'notation' in days.lower()})
    return last, meetings


def collect_fomc(db):
    got = http_fetch(db, FED_SOURCE, FOMC_URL, raw_ext='html')
    if got['status'] != 'OK':
        return _result('fed_fomc_calendar', DATA_UNAVAILABLE, 0, got['reason'])
    last, meetings = parse_fomc(got['content'])
    if not meetings:
        return _result('fed_fomc_calendar', DATA_UNAVAILABLE, 0, 'no meeting found on the page (layout changed?)')
    pub = end_of_us_trading_day_utc(last) if last else None
    basis = (f'page "Last Update: {last.isoformat()}", end of that day New York' if last
             else 'page without a version date: retrieval time')
    rows = [{'entity': 'FOMC', 'metric': 'meeting', 'as_of_date': m['end'], 'value_text': json.dumps(m),
             'published_at': pub, 'published_at_basis': basis} for m in meetings]
    stored = db.upsert_observations(got['fetch'], keep_stored_publication(db, FED_SOURCE, rows))
    return _result('fed_fomc_calendar', 'OK', stored,
                   meetings=len(meetings), last_update=last and last.isoformat())


# ---------------------------------------------------------------- BLS release schedules

BLS_SOURCE = 'BLS'
BLS_SCHEDULE_URL = 'https://www.bls.gov/schedule/news_release/{}.htm'
BLS_MONTH_URL = 'https://www.bls.gov/schedule/{}/{:02d}_sched.htm'
BLS_RELEASES = {'empsit': 'Employment Situation', 'cpi': 'Consumer Price Index',
                'ppi': 'Producer Price Index', 'jolts': 'Job Openings and Labor Turnover Survey',
                'eci': 'Employment Cost Index', 'realer': 'Real Earnings'}
BLS_CODES = {name: code for code, name in BLS_RELEASES.items()}
BLS_SCHEDULE_BASIS = 'BLS schedule page has no version date: retrieval time'
BLS_MONTH_BASIS = 'BLS monthly release calendar, as retrieved (its Last Modified date is not relied on): retrieval time'


def parse_bls_schedule(html):
    """[{'reference', 'date', 'time'}] from a BLS 'Schedule of Releases' page."""
    out = []
    for ref, day, tm in re.findall(r'<tr[^>]*>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*</tr>',
                                   html):
        txt = re.sub(r'\s+', ' ', day.strip()).replace('.', '')
        try:
            when = datetime.strptime(txt, '%b %d, %Y').date()
        except ValueError:
            try:
                when = datetime.strptime(txt, '%B %d, %Y').date()
            except ValueError:
                continue
        out.append({'reference': ref.strip(), 'date': when.isoformat(), 'time': tm.strip()})
    return out


def parse_bls_month(html, year, month):
    """
    [{'release', 'reference', 'date', 'time'}] from a BLS monthly release calendar (month view) of year-month.
    Cells of the adjacent months (December before a January page, January after a December page) are dated
    in their own year.
    """
    out = []
    for mmdd, cell in re.findall(r'<td[^>]*\bid="d(\d{4})"[^>]*>(.*?)</td>', html, re.S):
        m, d = int(mmdd[:2]), int(mmdd[2:])
        y = year - 1 if (month == 1 and m == 12) else year + 1 if (month == 12 and m == 1) else year
        for name, ref, tm in re.findall(r'<strong>([^<]+)<br\s*/?>\s*</strong>([^<]*)<br\s*/?>([^<]*)</p>', cell):
            out.append({'release': name.strip(), 'reference': ref.strip(), 'date': date(y, m, d).isoformat(),
                        'time': tm.strip()})
    return out


def _bls_release_row(code, r, basis):
    """One schedule row; the same release from either page gives the same value_text (stored once)."""
    return {'entity': f'BLS:{code}', 'metric': 'release', 'as_of_date': r['date'],
            'value_text': json.dumps({'reference': r['reference'], 'date': r['date'], 'time': r['time'],
                                      'release': BLS_RELEASES[code]}),
            'published_at': None, 'published_at_basis': basis}


def collect_bls(db, today=None):
    """
    Per-release schedule pages, plus the monthly calendars of this month and the next: on 2026-10-11 the
    per-release pages omitted the releases of the current month (CPI and Real Earnings on 10-14, PPI on 10-15).
    """
    today = today or datetime.now(NEW_YORK).date()
    stored, problems = 0, []
    for code in BLS_RELEASES:
        got = http_fetch(db, BLS_SOURCE, BLS_SCHEDULE_URL.format(code), raw_ext='html')
        if got['status'] != 'OK':
            problems.append(f'{code}: {got["reason"]}')
            continue
        rows = [_bls_release_row(code, r, BLS_SCHEDULE_BASIS) for r in parse_bls_schedule(got['content'])]
        if not rows:
            problems.append(f'{code}: no schedule row parsed (layout changed?)')
        stored += db.upsert_observations(got['fetch'], rows)
    first = today.replace(day=1)
    for month in (first, (first + timedelta(days=32)).replace(day=1)):
        got = http_fetch(db, BLS_SOURCE, BLS_MONTH_URL.format(month.year, month.month), raw_ext='html')
        if got['status'] != 'OK':
            problems.append(f'{month:%Y-%m} calendar: {got["reason"]}')
            continue
        found = parse_bls_month(got['content'], month.year, month.month)
        if not found:
            problems.append(f'{month:%Y-%m} calendar: no release parsed (layout changed?)')
        rows = [_bls_release_row(BLS_CODES[r['release']], r, BLS_MONTH_BASIS)
                for r in found if r['release'] in BLS_CODES]
        stored += db.upsert_observations(got['fetch'], rows)
    return _result('bls_schedules', 'OK' if not problems else DATA_UNAVAILABLE, stored, '; '.join(problems) or None)


# ---------------------------------------------------------------- Federal Register

FR_SOURCE = 'Federal Register'
FR_URL = 'https://www.federalregister.gov/api/v1/documents.json'
FR_AGENCIES = {'industry-and-security-bureau': 'Bureau of Industry and Security (export controls)',
               'foreign-assets-control-office': 'Office of Foreign Assets Control (sanctions)',
               'trade-representative-office-of-united-states': 'Office of the U.S. Trade Representative'}
FR_PRESIDENTIAL = 'presidential-documents'
FR_FIELDS = ('document_number', 'title', 'type', 'subtype', 'publication_date', 'html_url', 'action', 'agencies')
FR_BASIS = 'Federal Register publication date, 06:00 New York (issue online; documents on public inspection earlier)'


def fr_rows(entity, results):
    rows = []
    for d in results:
        if not d.get('publication_date') or not d.get('document_number'):
            continue
        pub_day = date.fromisoformat(d['publication_date'])
        rec = {k: d.get(k) for k in ('document_number', 'title', 'type', 'subtype', 'action', 'html_url')}
        rec['agencies'] = [a.get('name') for a in d.get('agencies') or [] if a.get('name')]
        rows.append({'entity': entity, 'metric': 'document', 'as_of_date': pub_day.isoformat(),
                     'value_text': json.dumps(rec, sort_keys=True), 'published_at': new_york_instant(pub_day, 6),
                     'published_at_basis': FR_BASIS})
    return rows


def collect_federal_register(db, since):
    stored, problems = 0, []
    queries = [(f'FR:{slug}', {'conditions[agencies][]': slug}) for slug in FR_AGENCIES]
    queries.append((f'FR:{FR_PRESIDENTIAL}', {'conditions[type][]': 'PRESDOCU'}))
    for entity, cond in queries:
        params = {**cond, 'conditions[publication_date][gte]': since.isoformat(), 'per_page': 200,
                  'order': 'oldest'}
        url_params = list(params.items()) + [('fields[]', f) for f in FR_FIELDS]
        got = http_fetch(db, FR_SOURCE, FR_URL + '?' + urlencode(url_params))
        if got['status'] != 'OK':
            problems.append(f'{entity}: {got["reason"]}')
            continue
        try:
            payload = json.loads(got['content'])
        except ValueError:
            problems.append(f'{entity}: response is not JSON')
            continue
        if payload.get('total_pages', 1) > 1:
            problems.append(f'{entity}: more than 200 documents since {since}; only the first page stored')
        rows = keep_stored_publication(db, FR_SOURCE, fr_rows(entity, payload.get('results') or []))
        stored += db.upsert_observations(got['fetch'], rows)
    return _result('federal_register', 'OK' if not problems else DATA_UNAVAILABLE, stored,
                   '; '.join(problems) or None)


# ---------------------------------------------------------------- Geopolitical Risk index

GPR_SOURCE = 'GPR index (Caldara-Iacoviello)'
GPR_URL = 'https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls'
GPR_COLUMNS = {'GPRD': 'gpr_daily', 'GPRD_ACT': 'gpr_daily_acts', 'GPRD_THREAT': 'gpr_daily_threats'}


def gpr_rows(content, published_at, since):
    import pandas as pd
    frame = pd.read_excel(io.BytesIO(content))
    rows = []
    for _, r in frame.iterrows():
        day = r.get('date')
        if day is None or pd.isna(day):
            continue
        day = pd.Timestamp(day).date()
        if day < since:
            continue
        for col, metric in GPR_COLUMNS.items():
            v = r.get(col)
            if v is not None and not pd.isna(v):
                rows.append({'entity': 'GPR', 'metric': metric, 'as_of_date': day.isoformat(), 'value': float(v),
                             'unit': 'index (1985-2019 = 100)', 'value_revisable': True,
                             'published_at': published_at,
                             'published_at_basis': 'HTTP Last-Modified of the downloaded file version'
                                                   if published_at else 'unknown (retrieval time)'})
    return rows


def collect_gpr(db, since):
    got = http_fetch(db, GPR_SOURCE, GPR_URL, binary=True, raw_ext='xls')
    if got['status'] != 'OK':
        return _result('gpr_index', DATA_UNAVAILABLE, 0, got['reason'])
    modified = got['headers'].get('Last-Modified') or got['headers'].get('last-modified')
    pub = None
    if modified:
        try:
            pub = to_utc_iso(datetime.strptime(modified, '%a, %d %b %Y %H:%M:%S GMT').replace(tzinfo=timezone.utc))
        except ValueError:
            pub = None
    try:
        rows = gpr_rows(got['content'], pub, since)
    except Exception as e:  # noqa: BLE001 - unreadable file
        return _result('gpr_index', DATA_UNAVAILABLE, 0, f'file not readable: {type(e).__name__}: {e}')
    stored = db.upsert_observations(got['fetch'], keep_stored_publication(db, GPR_SOURCE, rows))
    return _result('gpr_index', 'OK', stored, file_version=pub)


# ---------------------------------------------------------------- GDELT daily events

GDELT_SOURCE = 'GDELT'
GDELT_URL = 'https://data.gdeltproject.org/events/{}.export.CSV.zip'
GDELT_DYADS = {'USA-CHN': ('USA', 'CHN'), 'USA-RUS': ('USA', 'RUS'), 'RUS-UKR': ('RUS', 'UKR'),
               'CHN-TWN': ('CHN', 'TWN'), 'ISR-IRN': ('ISR', 'IRN'), 'USA-IRN': ('USA', 'IRN')}
# GDELT 1.0 event export columns (0-based)
G_A1_COUNTRY, G_A2_COUNTRY, G_ROOT, G_QUAD, G_GOLDSTEIN = 7, 17, 25, 29, 30
GDELT_BASIS = 'GDELT 1.0 daily export posted early the next day UTC: 12:00 UTC the day after (conservative)'


def gdelt_aggregates(text):
    """{entity: {metric: value}} from one daily export (root events only for conflict counts)."""
    agg = {'GDELT:global': {'events': 0, 'material_conflict': 0, 'verbal_conflict': 0, 'goldstein_sum': 0.0,
                            'root_events': 0}}
    for k in GDELT_DYADS:
        agg[f'GDELT:{k}'] = {'events': 0, 'material_conflict': 0, 'verbal_conflict': 0, 'goldstein_sum': 0.0,
                             'root_events': 0}
    pairs = {frozenset(v): f'GDELT:{k}' for k, v in GDELT_DYADS.items()}
    for line in text.splitlines():
        f = line.split('\t')
        if len(f) < 57:
            continue
        targets = ['GDELT:global']
        dyad = pairs.get(frozenset((f[G_A1_COUNTRY], f[G_A2_COUNTRY])))
        if dyad and f[G_A1_COUNTRY] != f[G_A2_COUNTRY]:
            targets.append(dyad)
        root = f[G_ROOT] == '1'
        quad = f[G_QUAD]
        g = _num(f[G_GOLDSTEIN])
        for t in targets:
            a = agg[t]
            a['events'] += 1
            if root:
                a['root_events'] += 1
                a['material_conflict'] += quad == '4'
                a['verbal_conflict'] += quad == '3'
                if g is not None:
                    a['goldstein_sum'] += g
    out = {}
    for ent, a in agg.items():
        out[ent] = {'events': a['events'], 'root_events': a['root_events'],
                    'material_conflict_root': a['material_conflict'],
                    'verbal_conflict_root': a['verbal_conflict'],
                    'goldstein_mean_root': a['goldstein_sum'] / a['root_events'] if a['root_events'] else None}
    return out


def collect_gdelt(db, days):
    stored, problems = 0, []
    have = {d for d, _ in db.series('GDELT:global', 'events', source=GDELT_SOURCE)}
    for d in days:
        if d.isoformat() in have:
            continue
        got = http_fetch(db, GDELT_SOURCE, GDELT_URL.format(d.strftime('%Y%m%d')), binary=True, raw_ext='zip')
        if got['status'] != 'OK':
            problems.append(f'{d}: {got["reason"]}')
            if 'network policy' in (got['reason'] or ''):
                break
            continue
        try:
            z = zipfile.ZipFile(io.BytesIO(got['content']))
            text = z.read(z.namelist()[0]).decode('utf-8', 'replace')
        except Exception as e:  # noqa: BLE001
            problems.append(f'{d}: unreadable archive ({type(e).__name__})')
            continue
        pub = to_utc_iso(datetime.combine(d + timedelta(days=1), dtime(12, 0), tzinfo=timezone.utc))
        rows = []
        for ent, metrics in gdelt_aggregates(text).items():
            for metric, v in metrics.items():
                if v is not None:
                    rows.append({'entity': ent, 'metric': metric, 'as_of_date': d.isoformat(), 'value': float(v),
                                 'unit': 'events' if metric != 'goldstein_mean_root' else 'Goldstein scale',
                                 'published_at': pub, 'published_at_basis': GDELT_BASIS})
        stored += db.upsert_observations(got['fetch'], rows)
    return _result('gdelt_events', 'OK' if not problems else DATA_UNAVAILABLE, stored, '; '.join(problems) or None)


# ---------------------------------------------------------------- options snapshot (yfinance)

def option_snapshot(chain_frames, spot, expiry_days):
    """
    Summary of an option chain: {'atm_iv', 'expiry', 'put_call_oi', 'put_call_volume', 'n_quotes'}.
    chain_frames: [(expiry date, calls DataFrame, puts DataFrame)]. ATM IV: mean implied volatility of
    the call and put nearest to spot at the expiry closest to 30 days (>= 7 days), quotes with
    bid > 0 and ask > 0 only. None values when the quality conditions are not met.
    Open interest / volume: sums over the quotes that report a value; a ratio is None when either side has no
    reported value at all (a missing side is never read as zero); missing quotes are counted.
    """
    tot = {k: 0.0 for k in ('oi_c', 'oi_p', 'vol_c', 'vol_p')}
    seen = dict.fromkeys(tot, 0)
    missing = {'openInterest': 0, 'volume': 0}
    best = None
    for exp, calls, puts in chain_frames:
        for key, frame, col in (('oi_c', calls, 'openInterest'), ('oi_p', puts, 'openInterest'),
                                ('vol_c', calls, 'volume'), ('vol_p', puts, 'volume')):
            values = frame[col]
            tot[key] += float(values.sum(skipna=True))
            seen[key] += int(values.notna().sum())
            missing[col] += int(values.isna().sum())
        d = expiry_days[exp]
        if d >= 7 and (best is None or abs(d - 30) < abs(expiry_days[best[0]] - 30)):
            best = (exp, calls, puts)
    def quoted(frame):
        return frame[(frame['bid'] > 0) & (frame['ask'] > 0) & (frame['impliedVolatility'] > 0.01)]

    def iv_near(frame, strike):
        q = quoted(frame)
        if not len(q):
            return None
        row = q.iloc[(q['strike'] - strike).abs().argsort().iloc[0]]
        # the nearest quoted strike must be within 5% of the target, else the point is not measured
        return float(row['impliedVolatility']) if abs(row['strike'] / strike - 1) <= 0.05 else None

    def atm(calls, puts):
        ivs = [iv_near(f, spot) for f in (calls, puts)]
        return sum(ivs) / 2 if None not in ivs else None
    atm_iv = atm(best[1], best[2]) if best is not None and spot else None
    # master mission P2: skew at the ~30-day expiry (put 90% strike minus call 110% strike, volatility points) and
    # the term structure (ATM IV by expiry, >= 7 days)
    skew = None
    if best is not None and spot:
        put90, call110 = iv_near(best[2], 0.9 * spot), iv_near(best[1], 1.1 * spot)
        skew = put90 - call110 if put90 is not None and call110 is not None else None
    term = []
    if spot:
        for exp, calls, puts in chain_frames:
            if expiry_days[exp] >= 7:
                v = atm(calls, puts)
                if v is not None:
                    term.append((expiry_days[exp], exp, v))
    term.sort()
    slope = term[-1][2] - term[0][2] if len(term) >= 2 else None
    def ratio(num, den):
        return tot[num] / tot[den] if seen[num] and seen[den] and tot[den] else None
    return {'atm_iv': atm_iv, 'expiry': best[0] if best else None,
            'put_call_oi': ratio('oi_p', 'oi_c'), 'put_call_volume': ratio('vol_p', 'vol_c'),
            'quotes_missing_open_interest': missing['openInterest'], 'quotes_missing_volume': missing['volume'],
            'skew_90_110': skew, 'term_structure': [[d, e, round(v, 4)] for d, e, v in term], 'term_slope': slope}


def collect_options(db, tickers, today=None, max_days=60):
    """Option chain snapshots (yfinance, unofficial); stored with published_at unknown (retrieval time)."""
    import yfinance as yf
    today = today or datetime.now(NEW_YORK).date()
    stored, problems = 0, []
    for t in tickers:
        requested_at = utc_now_iso()
        try:
            tk = yf.Ticker(t)
            exps = [e for e in tk.options if 0 <= (date.fromisoformat(e) - today).days <= max_days]
            frames, raw = [], {}
            for e in exps:
                oc = tk.option_chain(e)
                cols = ['strike', 'bid', 'ask', 'impliedVolatility', 'openInterest', 'volume', 'lastTradeDate']
                frames.append((e, oc.calls, oc.puts))
                raw[e] = {'calls': oc.calls[cols].to_dict('list'), 'puts': oc.puts[cols].to_dict('list')}
            spot = (getattr(oc, 'underlying', None) or {}).get('regularMarketPrice') if exps else None
            market_time = (getattr(oc, 'underlying', None) or {}).get('regularMarketTime') if exps else None
        except Exception as e:  # noqa: BLE001
            reason = redact(f'{type(e).__name__}: {e}')
            db.record_fetch('yfinance', f'yfinance.Ticker({t}).option_chain', requested_at=requested_at,
                            status=DATA_UNAVAILABLE, error=reason)
            problems.append(f'{t}: {reason}')
            continue
        if not frames:
            db.record_fetch('yfinance', f'yfinance.Ticker({t}).option_chain', requested_at=requested_at,
                            status=DATA_UNAVAILABLE, error='no expiration within 60 days')
            problems.append(f'{t}: no option expiration returned')
            continue
        snap = option_snapshot(frames, spot, {e: (date.fromisoformat(e) - today).days for e, _, _ in frames})
        as_of = (datetime.fromtimestamp(market_time, NEW_YORK).date().isoformat() if market_time
                 else today.isoformat())
        fetch = db.record_fetch('yfinance', f'yfinance.Ticker({t}).option_chain', requested_at=requested_at,
                                status='OK', raw=json.dumps({'spot': spot, 'regularMarketTime': market_time,
                                                             'chains': raw}, default=str),
                                n_records=sum(len(c) + len(p) for _, c, p in frames))
        basis = 'snapshot: publication time unknown (retrieval time); as_of = regularMarketTime session'
        rows = [{'entity': t, 'metric': m, 'as_of_date': as_of, 'value': v, 'unit': u, 'published_at': None,
                 'published_at_basis': basis}
                for m, v, u in (('opt_atm_iv_30d', snap['atm_iv'], 'annualised implied volatility'),
                                ('opt_put_call_oi_60d', snap['put_call_oi'], 'ratio'),
                                ('opt_put_call_volume_60d', snap['put_call_volume'], 'ratio'),
                                ('opt_skew_90_110_30d', snap['skew_90_110'], 'implied volatility difference'),
                                ('opt_term_slope_60d', snap['term_slope'], 'implied volatility difference'))
                if v is not None]
        rows.append({'entity': t, 'metric': 'opt_snapshot', 'as_of_date': as_of, 'published_at': None,
                     'published_at_basis': basis,
                     'value_text': json.dumps({**snap, 'spot': spot, 'expirations': [e for e, _, _ in frames]})})
        stored += db.upsert_observations(fetch, rows)
    return _result('options_snapshot', 'OK' if not problems else DATA_UNAVAILABLE, stored,
                   '; '.join(problems) or None)


# ---------------------------------------------------------------- FRED release calendars

def collect_fred_calendars(db, today):
    """
    The FRED release calendars of the weekly catalysts section (weekly.sections.catalysts.RELEASES) from
    `today` onward, stored as that section reads them: a weekly report admits a calendar only when it was
    retrieved before its cutoff, so they are refreshed daily here.
    """
    from .weekly.sections.catalysts import RELEASES, request_calendar
    stored, problems = 0, []
    for rid, name, _ in RELEASES:
        got = request_calendar(db, rid, today.isoformat())
        if got['status'] != 'OK':
            problems.append(f'release {rid}: {got["reason"]}')
        else:
            stored += 1
    return _result('fred_release_calendars', 'OK' if not problems else DATA_UNAVAILABLE, stored,
                   '; '.join(problems) or None)


# ---------------------------------------------------------------- earnings calendar snapshot (yfinance)

EARNINGS_BASIS = 'yfinance calendar snapshot: no publication time (retrieval time); the date may be an estimate'


def earnings_dates(value):
    """ISO dates listed under 'Earnings Date' in a yfinance calendar dict (or its JSON copy)."""
    raw = value.get('Earnings Date') if isinstance(value, dict) else None
    out = []
    for x in raw if isinstance(raw, (list, tuple)) else [raw] if raw is not None else []:
        try:
            out.append(date.fromisoformat(str(x.isoformat() if hasattr(x, 'isoformat') else x)[:10]).isoformat())
        except ValueError:
            continue
    return out


def collect_earnings_calendars(db, tickers):
    """
    Daily snapshot of yfinance Ticker(t).calendar (rank 2, unofficial), logged with the endpoint and raw format
    of the weekly catalysts section, so a later report can cite a snapshot retrieved before its cutoff. An
    empty result is DATA UNAVAILABLE, never "no earnings date".
    """
    import yfinance as yf
    stored, problems = 0, []
    for t in tickers:
        endpoint, requested_at = f'yfinance.Ticker({t}).calendar', utc_now_iso()
        try:
            value = yf.Ticker(t).calendar
            error = None if value else 'empty calendar ({}): read as unavailable, not as "no earnings date"'
        except Exception as e:  # noqa: BLE001 - recorded, surfaced as DATA UNAVAILABLE
            value, error = None, redact(f'{type(e).__name__}: {e}')[:300]
        if error:
            db.record_fetch('yfinance', endpoint, requested_at=requested_at, status=DATA_UNAVAILABLE, error=error)
            problems.append(f'{t}: {error}')
            continue
        fetch = db.record_fetch('yfinance', endpoint, requested_at=requested_at, status='OK',
                                raw=json.dumps(value, default=str, sort_keys=True))
        stored += db.upsert_observations(fetch, [
            {'entity': t, 'metric': 'earnings_date_reported', 'as_of_date': d,
             'value_text': json.dumps({'earnings_date': d, 'source': 'Yahoo Finance via yfinance'}),
             'published_at': None, 'published_at_basis': EARNINGS_BASIS} for d in earnings_dates(value)])
    return _result('earnings_calendar', 'OK' if not problems else DATA_UNAVAILABLE, stored,
                   '; '.join(problems) or None)


# ---------------------------------------------------------------- orchestration

def collect_all(db=None, tickers=None, today=None, history_days=400):
    """Run every collector; one failing source never stops the others. Returns the per-collector results."""
    from .agency_apis import collect_bea, collect_bls_api, collect_eia
    from .common import tickers as configured
    db = db or Database()
    tickers = tickers or configured()
    today = today or datetime.now(timezone.utc).date()
    since = today - timedelta(days=history_days)
    recent = [today - timedelta(days=k) for k in range(15, 0, -1)]
    cboe_days = [d for d in (today - timedelta(days=k) for k in range(90, -1, -1)) if d.weekday() < 5]
    from .common import validation_universe
    price_tickers = sorted(set(tickers) | set(validation_universe()) | {'SPY'})
    jobs = [('cftc_cot', lambda: collect_cot(db, since)),
            ('finra_short_interest', lambda: collect_finra(db, tickers)),
            ('cboe_put_call', lambda: collect_cboe(db, cboe_days)),
            ('fed_fomc_calendar', lambda: collect_fomc(db)),
            ('bls_schedules', lambda: collect_bls(db, today)),
            ('bls_api', lambda: collect_bls_api(db, since.year, today.year)),
            ('bea_nipa', lambda: collect_bea(db, range(since.year, today.year + 1))),
            ('eia_energy', lambda: collect_eia(db, since)),
            ('federal_register', lambda: collect_federal_register(db, today - timedelta(days=60))),
            ('gpr_index', lambda: collect_gpr(db, since)),
            ('gdelt_events', lambda: collect_gdelt(db, recent)),
            ('fred_release_calendars', lambda: collect_fred_calendars(db, today)),
            ('options_snapshot', lambda: collect_options(db, tickers)),
            ('earnings_calendar', lambda: collect_earnings_calendars(db, tickers)),
            ('cboe_price_history', lambda: collect_cboe_history(db, price_tickers, since))]
    results = []
    for name, job in jobs:
        try:
            results.append(job())
        except Exception as e:  # noqa: BLE001 - one source must not stop the others
            results.append(_result(name, DATA_UNAVAILABLE, 0, redact(f'{type(e).__name__}: {e}')))
    return results


def print_results(results):
    print('\n[COLLECT] external sources')
    for r in results:
        line = f"  {r['collector']:22} {r['status']:17} {r['stored']:6} new rows"
        if r.get('reason'):
            line += f"  - {r['reason'][:300]}"
        print(line)
