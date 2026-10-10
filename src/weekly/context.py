#!/usr/bin/env python3
"""
Weekly report context (phase P3.0): shared, cached, point-in-time data access for sections.

Every accessor returns data as it can be used at the cutoff:
  prices(t)          yfinance bars truncated to sessions <= s_0 (one fetch per ticker per run;
                     returns are ratios inside that fetch; levels shown from close_raw)
  fred(series)       FRED observations with all vintages stored; value_at(series, T) is the
                     latest observation as known at instant T (vintage published <= T);
                     first_release(series) maps each observation date to its first publication
  sec                SECParser (its fundamentals(known_at=...) replays XBRL by acceptance time)
  filings(t)         submissions feed rows with acceptance time, form, items, accession;
                     the feed is reused from storage when fetched < SUBMISSIONS_MAX_AGE ago
  freshness(as_of, cadence)  evaluated at the cutoff, never with the wall clock
Sections must not call datetime.now(), must not download outside these accessors and must not
write files.
"""

import json
from datetime import datetime, timedelta

from ..common import DATA_UNAVAILABLE, load_config, tickers
from ..database import Database, freshness
from ..macro_fred import FredError, MacroFRED
from ..market_data import PriceFeed
from ..sec_parser import SEC_SOURCE, SECParser
from .core import TimeModel

SUBMISSIONS_MAX_AGE = timedelta(hours=12)
PRICE_HISTORY_DAYS = 1200          # ~3 years: history for z-scores and 252-session windows
FRED_YEARS = 4


class Context:
    def __init__(self, db=None, requested_cutoff=None, generated_at=None, price_feed=None,
                 sec=None, fred=None):
        self.db = db or Database()
        self.config = load_config()
        self.weekly = self.config.get('weekly') or {}
        self.universe = tickers()
        self.prices_feed = price_feed or PriceFeed(db=self.db, lookback_days=PRICE_HISTORY_DAYS)
        self.sec = sec or SECParser(db=self.db)
        self.fred_client = fred or MacroFRED(db=self.db)
        benchmark = self.weekly.get('benchmark', 'SPY')
        spy = self.prices_feed.get(benchmark)
        if spy['status'] != 'OK':
            raise RuntimeError(f'benchmark {benchmark} unavailable: cannot build the session calendar '
                               f'({spy["reason"]})')
        sessions = [d.date().isoformat() for d in spy['close'].index]
        self.tm = TimeModel(sessions, requested_cutoff, generated_at)
        self._prices, self._fred, self._filings = {}, {}, {}

    # ------------------------------------------------------------------ prices

    def prices(self, ticker):
        """{'status', 'frame' (<= s_0), 'fetch', 'reason'}; frame columns close, close_raw, volume."""
        if ticker not in self._prices:
            p = self.prices_feed.get(ticker)
            frame = p.get('frame')
            if p['status'] == 'OK' and frame is not None:
                frame = frame[[d.date().isoformat() <= self.tm.s0 for d in frame.index]]
            self._prices[ticker] = {'status': p['status'] if frame is not None and len(frame) else DATA_UNAVAILABLE,
                                    'frame': frame, 'fetch': p.get('fetch'),
                                    'reason': p.get('reason') or (None if frame is not None and len(frame)
                                                                  else 'no session up to s_0')}
        return self._prices[ticker]

    # ------------------------------------------------------------------ FRED

    def fred(self, series_id):
        """Fetch (once) all vintages of a FRED series; {'status', 'fetch', 'reason'}."""
        if series_id not in self._fred:
            if self.fred_client.key_problem:
                self._fred[series_id] = {'status': DATA_UNAVAILABLE, 'fetch': None,
                                         'reason': self.fred_client.key_problem}
            else:
                try:
                    self.fred_client.fetch_observations(series_id, years=FRED_YEARS)
                    self._fred[series_id] = {'status': 'OK', 'fetch': self.fred_client.last_fetch,
                                             'reason': None}
                except FredError as e:
                    self._fred[series_id] = {'status': DATA_UNAVAILABLE, 'reason': str(e),
                                             'fetch': self.fred_client.last_fetch}
        return self._fred[series_id]

    def value_at(self, series_id, instant):
        """(obs_date, value, published_at) of the latest observation known at `instant`, or None."""
        rows = self.db.series(series_id, 'value', known_at=instant, source='FRED')
        if not rows:
            return None
        obs_date, row = rows[-1]
        return obs_date, row['value'], row['published_at']

    def series_at(self, series_id, instant, start=None):
        """[(obs_date, value)] as known at `instant` (one vintage per observation date)."""
        return [(d, r['value']) for d, r in self.db.series(series_id, 'value', known_at=instant,
                                                          source='FRED', start=start)]

    def vintages(self, series_id, known_at):
        """
        Every stored FRED version known at `known_at`: [(obs_date, value, available_at)] ordered by
        (obs_date, available_at); available_at = COALESCE(published_at, retrieved_at).
        """
        from ..common import to_utc_iso
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT as_of_date, value, COALESCE(published_at, retrieved_at) AS avail, retrieved_at "
                "FROM observations WHERE source='FRED' AND entity=? AND metric='value' "
                "AND COALESCE(published_at, retrieved_at) <= ? ORDER BY as_of_date, avail, retrieved_at",
                (series_id, to_utc_iso(known_at))).fetchall()
        return [(r['as_of_date'], r['value'], r['avail']) for r in rows]

    def first_release(self, series_id):
        """{obs_date: first publication instant} over all stored vintages."""
        return {e['as_of_date']: e['available_at']
                for e in self.db.events(series_id, 'value', source='FRED')}

    # ------------------------------------------------------------------ SEC

    def filings(self, ticker):
        """
        {'status', 'filings': [...], 'fetch', 'reason'}; each filing has form, filing_date,
        report_date, accession_number, published_at (conservative), acceptance_utc (label read
        as UTC, for session mapping only), items (8-K item codes) and primary_document.
        """
        if ticker in self._filings:
            return self._filings[ticker]
        cik = self.sec.get_cik(ticker)
        if not cik:
            out = {'status': DATA_UNAVAILABLE, 'filings': [], 'fetch': None,
                   'reason': self.sec.last_error or f'CIK not found for {ticker}'}
        else:
            url = f"{self.sec.SEC_API}/submissions/CIK{cik}.json"
            data = self.sec._get_json(url, max_age=SUBMISSIONS_MAX_AGE)
            if not data:
                out = {'status': DATA_UNAVAILABLE, 'filings': [], 'fetch': None, 'reason': self.sec.last_error}
            else:
                fetch = self.sec.last_fetch[url]
                rows = self.sec._recent_filings(data)
                recent = (data.get('filings') or {}).get('recent') or {}
                items = list(recent.get('items') or []) + [None] * len(rows)
                labels = list(recent.get('acceptanceDateTime') or []) + [None] * len(rows)
                for row, item, label in zip(rows, items, labels):
                    row['items'] = [x.strip() for x in (item or '').split(',') if x.strip()]
                    row['acceptance_utc'] = (label.replace('.000Z', '+00:00').replace('Z', '+00:00')
                                             if label else None)
                complete = fetch['retrieved_at'] > self.tm.cutoff
                out = {'status': 'OK', 'filings': rows, 'fetch': fetch, 'reason': None,
                       'retrieved_after_cutoff': complete,
                       # the 'recent' block holds ~1000 filings; older ones are in extra files
                       'truncated': bool((data.get('filings') or {}).get('files')),
                       'sic': data.get('sic'), 'sic_description': data.get('sicDescription'),
                       'name': data.get('name')}
        self._filings[ticker] = out
        return out

    # ------------------------------------------------------------------ misc

    def freshness(self, as_of, cadence, at=None):
        """Freshness evaluated at the cutoff (or at `at`, e.g. the previous cutoff)."""
        return freshness(as_of, cadence, now=datetime.fromisoformat(at or self.tm.cutoff))

    def company(self, ticker):
        return (self.config.get('companies') or {}).get(ticker, ticker)
