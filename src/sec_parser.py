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
- Cache expiry fixed (timedelta.seconds never exceeded one day, so the cache never expired).
"""

import os
import sqlite3
import time
from datetime import datetime, timedelta

import requests

from .common import db_path, unavailable, utc_now_iso, DATA_UNAVAILABLE

SEC_SOURCE = 'SEC EDGAR'


class SECParser:
    """SEC EDGAR access: CIK resolution, filing list, Form 4 counts."""

    SEC_API = "https://data.sec.gov"
    TICKER_FILE_URL = "https://www.sec.gov/files/company_tickers.json"

    # Values that earlier versions cached although they were invented
    FABRICATED_CACHE_METRICS = ('revenue', 'debt_to_equity')

    def __init__(self):
        self.user_agent = os.getenv('SEC_USER_AGENT', '').strip()
        self.session = requests.Session()
        if self.user_agent:
            self.session.headers.update({'User-Agent': self.user_agent})
        self.cache_ttl = 86400
        self._cik_map = None
        self._filings_cache = {}
        self.last_error = None
        self.init_db()

    def init_db(self):
        """Initialize SQLite cache table and purge previously cached invented values."""
        conn = sqlite3.connect(db_path())
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS sec_data (
            ticker TEXT,
            metric TEXT,
            value TEXT,
            source TEXT,
            confidence INTEGER,
            timestamp TEXT,
            PRIMARY KEY (ticker, metric)
        )''')
        c.execute(
            f"DELETE FROM sec_data WHERE metric IN ({','.join('?' * len(self.FABRICATED_CACHE_METRICS))})",
            self.FABRICATED_CACHE_METRICS)
        conn.commit()
        conn.close()

    def get_cached(self, ticker, metric):
        """Return a cached value younger than cache_ttl, else None."""
        try:
            conn = sqlite3.connect(db_path())
            c = conn.cursor()
            c.execute('SELECT value, timestamp FROM sec_data WHERE ticker=? AND metric=?',
                      (ticker, metric))
            result = c.fetchone()
            conn.close()
            if result:
                value, timestamp = result
                ts = datetime.fromisoformat(timestamp)
                if ts.tzinfo is not None:
                    ts = ts.replace(tzinfo=None)
                if (datetime.now() - ts).total_seconds() < self.cache_ttl:
                    return value
            return None
        except (sqlite3.Error, ValueError):
            return None

    def save_cache(self, ticker, metric, value):
        try:
            conn = sqlite3.connect(db_path())
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO sec_data
                (ticker, metric, value, source, confidence, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)''',
                      (ticker, metric, str(value), SEC_SOURCE, None, datetime.now().isoformat()))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            print(f"  [ERROR] SEC cache: {e}")

    def _get_json(self, url):
        """GET a JSON document from SEC; returns None and records the error on failure."""
        if not self.user_agent:
            self.last_error = 'SEC_USER_AGENT not set (SEC requires a User-Agent with contact info)'
            return None
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            time.sleep(0.11)  # SEC fair-access limit: max 10 requests/second
            return response.json()
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return None

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

    def get_filings(self, ticker):
        """Fetch the filing list (submissions endpoint) for a ticker."""
        if ticker in self._filings_cache:
            return self._filings_cache[ticker]
        cik = self.get_cik(ticker)
        if not cik:
            if not self.last_error:
                self.last_error = f'CIK not found for {ticker} in SEC ticker file'
            return None
        data = self._get_json(f"{self.SEC_API}/submissions/CIK{cik}.json")
        if data:
            self._filings_cache[ticker] = data
        return data

    def fetch_latest_periodic_filing(self, ticker):
        """Latest 10-K or 10-Q in the filing list (form, filing date, report date)."""
        data = self.get_filings(ticker)
        if not data:
            return None
        recent = data.get('filings', {}).get('recent', {})
        forms = recent.get('form', [])
        for i, form in enumerate(forms):
            if form in ('10-K', '10-Q'):
                return {
                    'form': form,
                    'filing_date': recent.get('filingDate', [None] * len(forms))[i],
                    'report_date': recent.get('reportDate', [None] * len(forms))[i],
                    'accession_number': recent.get('accessionNumber', [None] * len(forms))[i],
                }
        return None

    def fetch_revenue(self, ticker):
        """
        Revenue is not available yet: the previous implementation returned invented
        constants. Real values will come from SEC XBRL company facts (phase P0.3).
        """
        return None

    def fetch_debt_equity(self, ticker):
        """Debt-to-equity: DATA UNAVAILABLE until XBRL ingestion (phase P0.3)."""
        return None

    def fetch_form4_count(self, ticker):
        """Number of Form 4 filings in the last 90 days, or None if SEC is unreachable."""
        cached = self.get_cached(ticker, 'form4_count')
        if cached is not None:
            return int(cached)

        data = self.get_filings(ticker)
        if not data:
            return None

        recent = data.get('filings', {}).get('recent', {})
        forms = recent.get('form', [])
        dates = recent.get('filingDate', [])
        cutoff = datetime.now() - timedelta(days=90)
        count = 0
        for form, date_str in zip(forms, dates):
            if form != '4':
                continue
            try:
                if datetime.strptime(date_str, '%Y-%m-%d') > cutoff:
                    count += 1
            except (TypeError, ValueError):
                continue

        self.save_cache(ticker, 'form4_count', count)
        return count

    def run(self, ticker):
        """SEC summary for one ticker; unavailable fields are explicit."""
        print(f"\n[SEC PARSER] {ticker}")
        print("=" * 60)

        self.last_error = None
        latest = self.fetch_latest_periodic_filing(ticker)
        form4s = self.fetch_form4_count(ticker)
        cik = self._cik_map.get(ticker.upper()) if self._cik_map else None

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
            'retrieved_at': utc_now_iso(),
        }

        print(f"   CIK:          {cik or DATA_UNAVAILABLE}")
        print(f"   Latest 10-K/Q: {latest['form'] + ' ' + str(latest['filing_date']) if latest else DATA_UNAVAILABLE}")
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
