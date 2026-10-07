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
"""

import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from .common import (end_of_us_trading_day_utc, redact, to_utc_iso, unavailable, utc_now_iso,
                     DATA_UNAVAILABLE)
from .database import Database

SEC_SOURCE = 'SEC EDGAR'
PERIODIC_FORMS = ('10-K', '10-Q')
NEW_YORK = ZoneInfo('America/New_York')
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
        self.last_error = None
        self.last_fetch = {}

    def _get_json(self, url):
        """GET a JSON document from SEC, logged with its raw payload; None on failure."""
        if not self.user_agent:
            self.last_error = 'SEC_USER_AGENT not set (SEC requires a User-Agent with contact info)'
            return None
        requested_at = utc_now_iso()
        response = None
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            time.sleep(0.11)  # SEC fair-access limit: max 10 requests/second
            data = response.json()
        except Exception as e:  # noqa: BLE001 - recorded and surfaced
            self.last_error = redact(f"{type(e).__name__}: {e}")
            self.db.record_fetch(SEC_SOURCE, url, requested_at=requested_at,
                                 status=DATA_UNAVAILABLE, error=self.last_error,
                                 http_status=getattr(response, 'status_code', None))
            return None
        raw = getattr(response, 'content', None)
        self.last_fetch[url] = self.db.record_fetch(
            SEC_SOURCE, url, requested_at=requested_at, status='OK',
            http_status=getattr(response, 'status_code', None),
            raw=raw if isinstance(raw, (bytes, str)) else data)
        return data

    def get_cik(self, ticker):
        """Resolve a ticker to its 10-digit CIK using the official SEC ticker file."""
        if self._cik_map is None:
            data = self._get_json(self.TICKER_FILE_URL)
            if not data:
                return None
            self._cik_map = {
                entry['ticker'].upper(): str(entry['cik_str']).zfill(10)
                for entry in data.values()
            }
        return self._cik_map.get(ticker.upper())

    @staticmethod
    def _recent_filings(data):
        """Rows of the 'recent' block: form, filing_date, report_date, accession, accepted_at."""
        recent = (data or {}).get('filings', {}).get('recent', {})
        forms = recent.get('form', [])

        def col(name):
            values = recent.get(name) or []
            return list(values) + [None] * (len(forms) - len(values))

        filings = []
        for form, filed, report, accession, accepted in zip(
                forms, col('filingDate'), col('reportDate'), col('accessionNumber'),
                col('acceptanceDateTime')):
            if accepted:
                published, basis = acceptance_to_utc(accepted), ACCEPTANCE_BASIS
            elif filed:
                published, basis = end_of_us_trading_day_utc(filed), \
                    'end of SEC filing date (conservative; acceptance time not provided)'
            else:
                published, basis = None, 'unknown'
            filings.append({'form': form, 'filing_date': filed or None,
                            'report_date': report or None, 'accession_number': accession,
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
            self._filings_cache[ticker] = {'raw': data, 'filings': filings, 'fetch': fetch}
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

    def fetch_revenue(self, ticker):
        """
        Revenue is not available yet: the previous implementation returned invented
        constants. Real values will come from SEC XBRL company facts (phase P0.3).
        """
        return None

    def fetch_debt_equity(self, ticker):
        """Debt-to-equity: DATA UNAVAILABLE until XBRL ingestion (phase P0.3)."""
        return None

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
        cik = self._cik_map.get(ticker.upper()) if self._cik_map else None
        filings = self._filings_cache.get(ticker)
        fetch = filings['fetch'] if filings else None

        results = {
            'ticker': ticker,
            'cik': cik,
            'latest_periodic_filing': latest,
            'form4_filings_90d': form4s,
            'revenue': None,
            'debt_to_equity': None,
            'financials_status': unavailable(
                SEC_SOURCE, 'XBRL financial statement ingestion not implemented yet (phase P0.3)'),
            'source': SEC_SOURCE,
            'source_status': 'OK' if latest or form4s is not None else DATA_UNAVAILABLE,
            'error': self.last_error,
            'provenance': self.db.provenance(
                fetch, cadence='quarterly_filing',
                as_of_date=latest and (latest['report_date'] or latest['filing_date']),
                published_at=latest and latest['published_at'],
                published_at_basis=latest and latest['published_at_basis'],
                freshness_date=latest and latest['published_at']) if fetch else None,
            'retrieved_at': fetch['retrieved_at'] if fetch else utc_now_iso(),
        }

        print(f"   CIK:          {cik or DATA_UNAVAILABLE}")
        print(f"   Latest 10-K/Q: {latest['form'] + ' accepted ' + str(latest['published_at']) if latest else DATA_UNAVAILABLE}")
        print(f"   Form 4 (90d): {form4s if form4s is not None else DATA_UNAVAILABLE}")
        print(f"   Revenue/D-E:  {DATA_UNAVAILABLE} (XBRL ingestion planned P0.3)")
        if self.last_error:
            print(f"   Error:        {self.last_error}")
        print("=" * 60)
        return results


if __name__ == "__main__":
    from .common import tickers
    parser = SECParser()
    for t in tickers():
        parser.run(t)
