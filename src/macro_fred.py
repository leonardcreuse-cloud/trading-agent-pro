#!/usr/bin/env python3
"""
Macro FRED - official Federal Reserve Economic Data via the FRED API

P0.1 changes:
- pandas_datareader removed (unmaintained, imports distutils which no longer exists
  in Python 3.12+, so it failed silently). Uses the official FRED REST API directly;
  requires FRED_API_KEY (free) in .env. Without it, macro data is DATA UNAVAILABLE.
- CPI is reported as year-over-year inflation computed from the index. The previous
  version displayed the raw index level (~310) as "CPI Inflation: 310%".
- Each indicator carries its observation date, unit, series id and retrieval time.

P0.2 changes (provenance):
- All vintages of each observation are requested (realtime_start = window start,
  realtime_end = 9999-12-31) and stored as observations with
  published_at = end of the vintage date (conservative), so a revised value never
  replaces what was known earlier. Displayed values use the current vintage.
- Every call is logged in source_fetches with its raw JSON in data/raw/.
- Error messages no longer contain the request URL (it embedded api_key); FRED's own
  error_message is reported instead. A placeholder key such as "<key>" is rejected
  before any call. The legacy macro_data table is backed up and dropped by the v2 migration.
- Vintage-consistent transformations (YoY as known at a past date) come in phase P0.4.
"""

from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

from .common import (end_of_us_trading_day_utc, redact, secret_env, unavailable, utc_now_iso,
                     DATA_UNAVAILABLE)
from .database import Database

load_dotenv()

FRED_SOURCE = 'FRED (Federal Reserve Bank of St. Louis)'
DB_SOURCE = 'FRED'
CURRENT_VINTAGE_END = '9999-12-31'
VINTAGE_BASIS = 'FRED vintage date (realtime_start), end of day New York (conservative)'


class FredError(Exception):
    pass


class MacroFRED:
    """FRED indicators with explicit provenance."""

    API_URL = "https://api.stlouisfed.org/fred/series/observations"

    # name: (series_id, transform, unit, cadence)
    INDICATORS = {
        'CPI_YOY': ('CPIAUCSL', 'yoy', '% YoY', 'monthly'),
        'CORE_CPI_YOY': ('CPILFESL', 'yoy', '% YoY', 'monthly'),
        'UNEMPLOYMENT': ('UNRATE', 'level', '%', 'monthly'),
        'FED_FUNDS': ('FEDFUNDS', 'level', '%', 'monthly'),
        'T10Y2Y': ('T10Y2Y', 'level', 'percentage points', 'daily'),
        'VIX': ('VIXCLS', 'level', 'index', 'daily'),
    }

    def __init__(self, db=None):
        self.db = db or Database()
        self.api_key, self.key_problem = secret_env('FRED_API_KEY')
        self.last_fetch = None

    def fetch_observations(self, series_id, years=3):
        """
        Current-vintage [(date, float)] sorted by date, plus {date: published_at} of the
        current vintage. All vintages are stored. Raises FredError on HTTP/parsing errors.
        """
        start = (datetime.now() - timedelta(days=365 * years)).strftime('%Y-%m-%d')
        params = {'series_id': series_id, 'api_key': self.api_key, 'file_type': 'json',
                  'observation_start': start, 'realtime_start': start,
                  'realtime_end': CURRENT_VINTAGE_END}
        requested_at = utc_now_iso()
        response = None
        try:
            response = requests.get(self.API_URL, params=params, timeout=30)
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if response.status_code != 200:
                detail = payload.get('error_message') if isinstance(payload, dict) else None
                raise FredError(f"FRED HTTP {response.status_code}"
                                + (f": {detail}" if detail else ''))
        except FredError as e:
            error = redact(str(e))
        except Exception as e:  # noqa: BLE001 - network errors: type only, never the URL
            error = f"{type(e).__name__} (network error contacting FRED)"
        else:
            error = None
        if error:
            self.last_fetch = self.db.record_fetch(
                DB_SOURCE, self.API_URL, params=params, requested_at=requested_at,
                status=DATA_UNAVAILABLE, error=error,
                http_status=getattr(response, 'status_code', None))
            raise FredError(error)

        raw = getattr(response, 'content', None)
        rows = payload.get('observations', [])
        self.last_fetch = fetch = self.db.record_fetch(
            DB_SOURCE, self.API_URL, params=params, requested_at=requested_at, status='OK',
            http_status=response.status_code, n_records=len(rows),
            raw=raw if isinstance(raw, (bytes, str)) else payload)

        stored, current, published = [], {}, {}
        for obs in rows:
            if obs.get('value') in (None, '.', ''):
                continue  # FRED marks missing observations with '.'
            obs_date = date.fromisoformat(obs['date'])
            vintage = obs.get('realtime_start')
            pub = end_of_us_trading_day_utc(vintage) if vintage else None
            stored.append({'entity': series_id, 'metric': 'value', 'as_of_date': obs_date,
                           'value': float(obs['value']), 'published_at': pub,
                           'published_at_basis': VINTAGE_BASIS if vintage else 'unknown'})
            if obs.get('realtime_end', CURRENT_VINTAGE_END) == CURRENT_VINTAGE_END:
                current[obs_date] = float(obs['value'])
                published[obs_date] = min(pub, fetch['retrieved_at']) if pub else None
        self.db.upsert_observations(fetch, stored)
        return sorted(current.items()), published

    @staticmethod
    def year_over_year(observations):
        """YoY % change of the latest observation vs the same month one year earlier."""
        if not observations:
            return None, None
        latest_date, latest_value = observations[-1]
        target = latest_date.replace(year=latest_date.year - 1)
        previous = dict(observations).get(target)
        if previous is None or previous == 0:
            return None, latest_date
        return round((latest_value / previous - 1) * 100, 2), latest_date

    def fetch_indicator(self, name):
        series_id, transform, unit, cadence = self.INDICATORS[name]
        url = f"https://fred.stlouisfed.org/series/{series_id}"
        if self.key_problem:
            return unavailable(FRED_SOURCE, self.key_problem, series_id=series_id, url=url)
        try:
            observations, published = self.fetch_observations(series_id)
        except FredError as e:
            return unavailable(FRED_SOURCE, str(e), series_id=series_id, url=url,
                               fetch_id=self.last_fetch and self.last_fetch['fetch_id'])

        inputs = []
        if transform == 'yoy':
            value, obs_date = self.year_over_year(observations)
            if obs_date is not None:
                inputs = [obs_date, obs_date.replace(year=obs_date.year - 1)]
        elif observations:
            obs_date, value = observations[-1]
            inputs = [obs_date]
        else:
            value, obs_date = None, None

        if value is None:
            return unavailable(FRED_SOURCE, 'insufficient observations', series_id=series_id,
                               url=url, fetch_id=self.last_fetch['fetch_id'])

        input_pubs = [published.get(d) for d in inputs]
        published_at = None if None in input_pubs else max(input_pubs)
        return {
            'status': 'OK',
            'value': value,
            'unit': unit,
            'observation_date': obs_date.isoformat(),
            'series_id': series_id,
            'transform': transform,
            'source': FRED_SOURCE,
            'url': url,
            'vintage': 'current (latest revision)',
            'provenance': self.db.provenance(
                self.last_fetch, cadence=cadence, as_of_date=obs_date, published_at=published_at,
                published_at_basis=VINTAGE_BASIS if published_at else 'unknown'),
            'retrieved_at': self.last_fetch['retrieved_at'],
        }

    @staticmethod
    def interpret_data(indicator, value):
        """Descriptive labels only (no trading signal)."""
        rules = {
            'CPI_YOY': lambda v: "above 2% target" if v > 2.5 else "near/below 2% target",
            'CORE_CPI_YOY': lambda v: "above 2% target" if v > 2.5 else "near/below 2% target",
            'T10Y2Y': lambda v: "inverted" if v < 0 else ("flat" if v < 0.5 else "positive slope"),
            'VIX': lambda v: "low" if v < 15 else ("moderate" if v < 25 else "high"),
        }
        return rules[indicator](value) if indicator in rules else ""

    def run(self):
        print("\n[MACRO - FRED]")
        print("=" * 75)
        indicators = {}
        for name in self.INDICATORS:
            data = self.fetch_indicator(name)
            indicators[name] = data
            if data['status'] == 'OK':
                print(f"  {name:14} {data['value']:8.2f} {data['unit']:18} "
                      f"(obs {data['observation_date']}) {self.interpret_data(name, data['value'])}")
            else:
                print(f"  {name:14} {DATA_UNAVAILABLE} ({data['reason']})")
        print("=" * 75)

        n_ok = sum(1 for d in indicators.values() if d['status'] == 'OK')
        return {
            'indicators': indicators,
            'coverage': f"{n_ok}/{len(indicators)}",
            'status': 'OK' if n_ok else DATA_UNAVAILABLE,
            'source': FRED_SOURCE,
            'retrieved_at': utc_now_iso(),
        }


if __name__ == "__main__":
    MacroFRED().run()
