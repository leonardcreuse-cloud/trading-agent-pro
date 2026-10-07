#!/usr/bin/env python3
"""
SEC EDGAR Parser

P0.1 changes:
- Removed hardcoded revenue / debt-to-equity values (they were invented, not SEC data).
  Financial statement values are DATA UNAVAILABLE until XBRL ingestion (phase P0.3).
- CIKs are resolved from the official SEC ticker file instead of a hardcoded table
  (the previous table pointed to wrong companies).
- SEC requires a User-Agent with contact information: set SEC_USER_AGENT in .env.
  Without it, SEC is reported as unavailable instead of being called non-compliantly.
- Failures return None (never 0 or a placeholder).

P0.2 changes (provenance):
- Every SEC call is logged in source_fetches and its raw JSON kept in data/raw/.
- Each filing of the submissions feed is stored as an observation
  (metric 'filing:<form>', value_text = accession number) with published_at derived
  from acceptanceDateTime, or the end of the filing date when absent.
  acceptanceDateTime is labelled 'Z' (UTC) in the submissions feed, but on real data
  neither UTC nor New York time is consistent with filingDate for every filing. It is
  read as New York wall-clock time, which yields an instant >= the UTC reading: the
  conservative choice (a filing is never considered public too early; at most ~5 h late).
- The 90-day Form 4 count is computed point-in-time from those observations
  (filings available at the evaluation instant only). The legacy sec_data cache, which
  had no publication time, is gone (backed up and dropped by the v2 migration).

P0.3 changes (financial statements, efficiency):
- Revenue (TTM), revenue growth, debt and debt-to-equity come from SEC XBRL company facts
  (see sec_xbrl.py for definitions). Every fact is stored as a point-in-time observation;
  fundamentals(known_at=T) only uses facts whose filing was public at T.
- Documents are reused instead of re-downloaded: the ticker file for 24 h, company facts
  for 12 h, Form 4 XML documents forever (filed documents are immutable). The reused fetch
  keeps its original retrieval time in the provenance.

P1.2b: requests go through one process-wide rate limiter (<= 9 requests/s, under the SEC
fair-access limit of 10/s). prefetch() downloads many documents with a few threads under
that limiter; logging, raw storage and parsing stay in the calling thread.
"""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from .common import (end_of_us_trading_day_utc, redact, to_utc_iso, unavailable, utc_now_iso,
                     DATA_UNAVAILABLE)
from .database import Database
from .sec_xbrl import (DEBT_TAGS, DURATION_MONTHS, EQUITY_TAGS, MAX_BALANCE_AGE_DAYS, REVENUE_TAGS,
                       balance_sheet,
                       facts_to_observations, latest_ttm)

SEC_SOURCE = 'SEC EDGAR'
PERIODIC_FORMS = ('10-K', '10-Q')
NEW_YORK = ZoneInfo('America/New_York')
TICKER_FILE_MAX_AGE = timedelta(hours=24)
COMPANY_FACTS_MAX_AGE = timedelta(hours=12)
IMMUTABLE = 'immutable'
MIN_REQUEST_INTERVAL = 0.11      # seconds between SEC requests, all threads: <= 9 req/s
PREFETCH_WORKERS = 4
_RATE_LOCK = threading.Lock()
_LAST_REQUEST = [0.0]


def _throttle():
    """Block until a request may start without exceeding the SEC rate limit."""
    with _RATE_LOCK:
        wait = _LAST_REQUEST[0] + MIN_REQUEST_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST[0] = time.monotonic()
ACCEPTANCE_BASIS = ('SEC acceptanceDateTime read as New York time '
                    '(conservative: >= the UTC reading of the feed)')


def acceptance_to_utc(value):
    """acceptanceDateTime -> UTC ISO, reading the wall-clock time as America/New_York."""
    wall = datetime.fromisoformat(value.strip().replace('Z', '')[:19])
    return to_utc_iso(wall.replace(tzinfo=NEW_YORK))


class SECParser:
    """SEC EDGAR access: CIK resolution, filing list, Form 4 counts."""

    SEC_API = "https://data.sec.gov"
    TICKER_FILE_URL = "https://www.sec.gov/files/company_tickers.json"

    def __init__(self, db=None):
        self.db = db or Database()
        self.user_agent = os.getenv('SEC_USER_AGENT', '').strip()
        self.session = requests.Session()
        if self.user_agent:
            self.session.headers.update({'User-Agent': self.user_agent})
        self._cik_map = None
        self._filings_cache = {}
        self._facts_fetch = {}
        self._fundamentals_cache = {}
        self.last_error = None
        self.last_fetch = {}

    def _cached(self, url, as_json, max_age):
        """Reusable stored document for url (see _get), or None."""
        if max_age is None:
            return None
        since = None if max_age == IMMUTABLE else datetime.now(timezone.utc) - max_age
        cached = self.db.latest_fetch(SEC_SOURCE, url, since=since)
        if not cached:
            return None
        try:
            text = self.db.read_raw(cached['fetch_id'])
            data = json.loads(text) if as_json else text
        except Exception:  # noqa: BLE001 - corrupted cache: download again
            return None
        self.last_fetch[url] = cached
        return data

    def _download(self, url):
        """(requested_at, response, exception) - thread-safe, rate limited, no DB access."""
        requested_at = utc_now_iso()
        response = None
        try:
            _throttle()
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            return requested_at, response, None
        except Exception as e:  # noqa: BLE001 - recorded by the caller
            return requested_at, response, e

    def prefetch(self, urls, as_json=True, max_age=None, workers=PREFETCH_WORKERS):
        """Download the urls not reusable from storage, in parallel; returns {url: download}."""
        if not self.user_agent:
            return {}
        missing = [u for u in dict.fromkeys(urls)
                   if max_age is None or not self.db.latest_fetch(
                       SEC_SOURCE, u, since=None if max_age == IMMUTABLE
                       else datetime.now(timezone.utc) - max_age)]
        if not missing:
            return {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return dict(zip(missing, pool.map(self._download, missing)))

    def _get(self, url, as_json=True, max_age=None, prefetched=None):
        """
        GET a document from SEC, logged with its raw payload; None on failure.
        max_age: reuse the last successful fetch of this URL if it is more recent than
        this timedelta, or whatever its age when max_age == IMMUTABLE.
        prefetched: result of _download() for this url (from prefetch()).
        """
        if not self.user_agent:
            self.last_error = 'SEC_USER_AGENT not set (SEC requires a User-Agent with contact info)'
            return None
        if prefetched is None:
            data = self._cached(url, as_json, max_age)
            if data is not None:
                return data
        requested_at, response, error = prefetched or self._download(url)
        if error is None:
            try:
                data = response.json() if as_json else response.text
            except Exception as e:  # noqa: BLE001
                error = e
        if error is not None:
            self.last_error = redact(f"{type(error).__name__}: {error}")
            self.db.record_fetch(SEC_SOURCE, url, requested_at=requested_at,
                                 status=DATA_UNAVAILABLE, error=self.last_error,
                                 http_status=getattr(response, 'status_code', None))
            return None
        raw = getattr(response, 'content', None)
        self.last_fetch[url] = self.db.record_fetch(
            SEC_SOURCE, url, requested_at=requested_at, status='OK',
            http_status=getattr(response, 'status_code', None),
            raw=raw if isinstance(raw, (bytes, str)) else data,
            raw_ext='json' if as_json else 'xml')
        return data

    def _get_json(self, url, max_age=None):
        return self._get(url, as_json=True, max_age=max_age)

    def get_cik(self, ticker):
        """Resolve a ticker to its 10-digit CIK using the official SEC ticker file."""
        if self._cik_map is None:
            data = self._get_json(self.TICKER_FILE_URL, max_age=TICKER_FILE_MAX_AGE)
            if not data:
                return None
            self._cik_map = {
                entry['ticker'].upper(): str(entry['cik_str']).zfill(10)
                for entry in data.values()
            }
        return self._cik_map.get(ticker.upper())

    @staticmethod
    def _recent_filings(data):
        """Rows of the 'recent' block: form, dates, accession, primary document, publication."""
        recent = (data or {}).get('filings', {}).get('recent', {})
        forms = recent.get('form', [])

        def col(name):
            values = recent.get(name) or []
            return list(values) + [None] * (len(forms) - len(values))

        filings = []
        for form, filed, report, accession, accepted, document in zip(
                forms, col('filingDate'), col('reportDate'), col('accessionNumber'),
                col('acceptanceDateTime'), col('primaryDocument')):
            if accepted:
                published, basis = acceptance_to_utc(accepted), ACCEPTANCE_BASIS
            elif filed:
                published, basis = end_of_us_trading_day_utc(filed), \
                    'end of SEC filing date (conservative; acceptance time not provided)'
            else:
                published, basis = None, 'unknown'
            filings.append({'form': form, 'filing_date': filed or None,
                            'report_date': report or None, 'accession_number': accession,
                            'primary_document': document or None,
                            'published_at': published, 'published_at_basis': basis})
        return filings

    def get_filings(self, ticker):
        """Fetch the filing list (submissions endpoint) and store each filing as an observation."""
        if ticker in self._filings_cache:
            return self._filings_cache[ticker]
        cik = self.get_cik(ticker)
        if not cik:
            if not self.last_error:
                self.last_error = f'CIK not found for {ticker} in SEC ticker file'
            return None
        url = f"{self.SEC_API}/submissions/CIK{cik}.json"
        data = self._get_json(url)
        if data:
            filings = self._recent_filings(data)
            fetch = self.last_fetch[url]
            self.db.upsert_observations(fetch, [{
                'entity': ticker, 'metric': f"filing:{f['form']}",
                'as_of_date': f['report_date'] or f['filing_date'],
                'value_text': f['accession_number'], 'published_at': f['published_at'],
                'published_at_basis': f['published_at_basis']}
                for f in filings if f['accession_number'] and (f['report_date'] or f['filing_date'])])
            # The 'recent' block holds the last ~1000 filings; older ones are in extra files
            # (not downloaded). History before the oldest listed filing is then unknown.
            truncated = bool((data.get('filings') or {}).get('files'))
            dates = [f['filing_date'] for f in filings if f['filing_date']]
            self._filings_cache[ticker] = {
                'raw': data, 'filings': filings, 'fetch': fetch,
                'coverage_start': min(dates) if truncated and dates else None}
        return self._filings_cache.get(ticker)

    def fetch_latest_periodic_filing(self, ticker, known_at=None):
        """Latest 10-K or 10-Q available at known_at (default: now)."""
        data = self.get_filings(ticker)
        if not data:
            return None
        limit = to_utc_iso(known_at) if known_at else utc_now_iso()
        candidates = [f for f in data['filings'] if f['form'] in PERIODIC_FORMS
                      and f['published_at'] and f['published_at'] <= limit]
        if not candidates:
            return None
        latest = max(candidates, key=lambda f: f['published_at'])
        return {k: latest[k] for k in ('form', 'filing_date', 'report_date', 'accession_number',
                                       'published_at', 'published_at_basis')}

    # ------------------------------------------------------------------ XBRL fundamentals

    def ingest_company_facts(self, ticker):
        """
        Download (or reuse, < 12 h) the XBRL company facts and store the revenue, equity and
        debt facts as observations. Returns the fetch dict, or None if SEC was unreachable.
        """
        if ticker in self._facts_fetch:
            return self._facts_fetch[ticker]
        cik = self.get_cik(ticker)
        if not cik:
            if not self.last_error:
                self.last_error = f'CIK not found for {ticker} in SEC ticker file'
            return None
        url = f"{self.SEC_API}/api/xbrl/companyfacts/CIK{cik}.json"
        data = self._get_json(url, max_age=COMPANY_FACTS_MAX_AGE)
        if not data:
            return None
        filings = self.get_filings(ticker)
        acceptance = {f['accession_number']: (f['published_at'], f['published_at_basis'])
                      for f in (filings or {}).get('filings', [])
                      if f['accession_number'] and f['published_at']}
        fetch = self.last_fetch[url]
        self.db.upsert_observations(fetch, facts_to_observations(ticker, data, acceptance))
        self._facts_fetch[ticker] = fetch
        return fetch

    def _instants(self, ticker, tags, known_at):
        return {tag: dict(self.db.series(ticker, f'xbrl:{tag}', known_at=known_at,
                                         source=SEC_SOURCE)) for tag in tags}

    def fundamentals(self, ticker, known_at=None):
        """
        Revenue TTM, revenue growth, debt and debt-to-equity from facts available at
        known_at (default: now). Missing values are None with a reason, never 0.
        """
        if ticker in self._fundamentals_cache and known_at is None:
            return self._fundamentals_cache[ticker]
        fetch = self.ingest_company_facts(ticker)
        if not fetch:
            return {'status': DATA_UNAVAILABLE, 'revenue': None, 'revenue_growth_pct': None,
                    'debt': None, 'equity': None, 'debt_to_equity': None, 'fetch': None,
                    'reason': f'SEC XBRL company facts unavailable: {self.last_error}'}
        known = to_utc_iso(known_at) if known_at else utc_now_iso()
        reasons = []

        revenue = None
        for tag in REVENUE_TAGS:
            durations = {m: dict(self.db.series(ticker, f'xbrl:{tag}:{m}M', known_at=known,
                                                source=SEC_SOURCE))
                         for m in DURATION_MONTHS}
            current, prior = latest_ttm(durations)
            if current and (revenue is None or current['end'] > revenue['current']['end']):
                revenue = {'tag': tag, 'current': current, 'prior': prior}
        if revenue is None:
            reasons.append('no computable trailing-twelve-month revenue in XBRL facts')

        instants = self._instants(ticker, EQUITY_TAGS + DEBT_TAGS, known)
        sheet = balance_sheet(instants)
        balance_date, equity, debt = sheet['date'], sheet['equity'], sheet['debt']
        if not balance_date:
            reasons.append('stockholders equity not reported')
        elif debt is None:
            reasons.append(f'no recognised debt concept reported between {balance_date} and '
                           f'{MAX_BALANCE_AGE_DAYS} days earlier (leases excluded; company-specific '
                           f'extension tags are not in SEC company facts)')
        de_ratio = None
        if debt and equity:
            if equity['value'] > 0:
                de_ratio = round(debt['value'] / equity['value'], 3)
            else:
                reasons.append('stockholders equity <= 0: debt-to-equity not meaningful')

        growth = None
        if revenue and revenue['prior'] and revenue['prior']['value'] > 0:
            growth = round((revenue['current']['value'] / revenue['prior']['value'] - 1) * 100, 2)
        elif revenue:
            reasons.append('revenue one year earlier not computable: growth unavailable')

        rev_inputs = revenue['current']['inputs'] if revenue else []
        latest_pub = max((r['published_at'] for r in rev_inputs if r.get('published_at')), default=None)
        result = {
            'status': 'OK' if revenue or de_ratio is not None else DATA_UNAVAILABLE,
            'known_at': known,
            'revenue': revenue['current']['value'] if revenue else None,
            'revenue_tag': revenue['tag'] if revenue else None,
            'revenue_period_end': revenue['current']['end'] if revenue else None,
            'revenue_method': revenue['current']['method'] if revenue else None,
            'revenue_prior_year': revenue['prior']['value'] if revenue and revenue['prior'] else None,
            'revenue_growth_pct': growth,
            'balance_sheet_date': balance_date,
            'latest_equity_date': sheet['latest_equity_date'],
            'equity': equity['value'] if equity else None,
            'equity_tag': sheet['equity_tag'],
            'debt': debt['value'] if debt else None,
            'debt_tags': debt['tags'] if debt else None,
            'debt_definition': debt['definition'] if debt else None,
            'debt_includes_finance_leases': debt['includes_finance_leases'] if debt else None,
            'debt_to_equity': de_ratio,
            'revenue_published_at': latest_pub,
            'fetch': fetch,
            'reason': '; '.join(reasons) or None,
        }
        if known_at is None:
            self._fundamentals_cache[ticker] = result
        return result

    def fetch_revenue(self, ticker, known_at=None):
        """Trailing-twelve-month revenue (USD) from SEC XBRL; None if unavailable."""
        return self.fundamentals(ticker, known_at)['revenue']

    def fetch_debt_equity(self, ticker, known_at=None):
        """Debt / stockholders' equity from SEC XBRL; None if unavailable."""
        return self.fundamentals(ticker, known_at)['debt_to_equity']

    def fetch_form4_count(self, ticker, known_at=None, days=90):
        """
        Number of Form 4 filings available in the `days` before known_at (default: now),
        from stored observations; None if SEC could not be reached.
        """
        if not self.get_filings(ticker):
            return None
        end = datetime.fromisoformat(to_utc_iso(known_at)) if known_at else datetime.now(timezone.utc)
        return len(self.db.events(ticker, 'filing:4', published_from=end - timedelta(days=days),
                                  published_to=end, source=SEC_SOURCE))

    def run(self, ticker):
        """SEC summary for one ticker; unavailable fields are explicit."""
        print(f"\n[SEC PARSER] {ticker}")
        print("=" * 60)

        self.last_error = None
        latest = self.fetch_latest_periodic_filing(ticker)
        form4s = self.fetch_form4_count(ticker)
        filings_error = self.last_error
        self.last_error = None
        fin = self.fundamentals(ticker)
        cik = self._cik_map.get(ticker.upper()) if self._cik_map else None
        filings = self._filings_cache.get(ticker)
        fetch = filings['fetch'] if filings else None
        fin_fetch = fin.get('fetch')

        if fin['status'] == 'OK':
            financials_status = {'status': 'OK', 'source': SEC_SOURCE, 'reason': fin['reason'],
                                 'method': 'SEC XBRL company facts (see sec_xbrl.py)'}
        else:
            financials_status = unavailable(SEC_SOURCE, fin['reason'] or 'no usable XBRL facts')

        results = {
            'ticker': ticker,
            'cik': cik,
            'latest_periodic_filing': latest,
            'form4_filings_90d': form4s,
            'revenue': fin['revenue'],
            'revenue_ttm_period_end': fin.get('revenue_period_end'),
            'revenue_tag': fin.get('revenue_tag'),
            'revenue_method': fin.get('revenue_method'),
            'revenue_growth_pct': fin.get('revenue_growth_pct'),
            'balance_sheet_date': fin.get('balance_sheet_date'),
            'debt': fin.get('debt'),
            'debt_tags': fin.get('debt_tags'),
            'equity': fin.get('equity'),
            'debt_to_equity': fin['debt_to_equity'],
            'financials_status': financials_status,
            'source': SEC_SOURCE,
            'source_status': 'OK' if latest or form4s is not None else DATA_UNAVAILABLE,
            'error': filings_error,
            'provenance': self.db.provenance(
                fetch, cadence='quarterly_filing',
                as_of_date=latest and (latest['report_date'] or latest['filing_date']),
                published_at=latest and latest['published_at'],
                published_at_basis=latest and latest['published_at_basis'],
                freshness_date=latest and latest['published_at']) if fetch else None,
            'financials_provenance': self.db.provenance(
                fin_fetch, cadence='quarterly_filing',
                as_of_date=fin.get('revenue_period_end') or fin.get('balance_sheet_date'),
                published_at=fin.get('revenue_published_at'),
                published_at_basis='filing acceptance time of the latest revenue fact',
                freshness_date=fin.get('revenue_published_at')) if fin_fetch else None,
            'retrieved_at': fetch['retrieved_at'] if fetch else utc_now_iso(),
        }

        def money(v):
            return f"{v / 1e6:,.1f} M USD" if v is not None else DATA_UNAVAILABLE
        print(f"   CIK:          {cik or DATA_UNAVAILABLE}")
        print(f"   Latest 10-K/Q: {latest['form'] + ' accepted ' + str(latest['published_at']) if latest else DATA_UNAVAILABLE}")
        print(f"   Form 4 (90d): {form4s if form4s is not None else DATA_UNAVAILABLE}")
        print(f"   Revenue TTM:  {money(fin['revenue'])}"
              + (f" (period end {fin['revenue_period_end']})" if fin['revenue'] is not None else ''))
        growth = fin.get('revenue_growth_pct')
        print(f"   Rev. growth:  {str(growth) + ' % YoY' if growth is not None else DATA_UNAVAILABLE}")
        de = fin['debt_to_equity']
        print(f"   Debt/equity:  {de if de is not None else DATA_UNAVAILABLE}"
              + (f" (debt {money(fin['debt'])}, equity {money(fin['equity'])}, "
                 f"{fin['balance_sheet_date']})" if de is not None else ''))
        if fin['reason']:
            print(f"   Note:         {fin['reason']}")
        if filings_error:
            print(f"   Error:        {filings_error}")
        print("=" * 60)
        return results


if __name__ == "__main__":
    from .common import tickers
    parser = SECParser()
    for t in tickers():
        parser.run(t)
