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
- Vintages / publication dates (ALFRED) come in phase P0.4.
"""

import os
import sqlite3
from datetime import date, datetime, timedelta

import requests
from dotenv import load_dotenv

from .common import db_path, unavailable, utc_now_iso, DATA_UNAVAILABLE

load_dotenv()

FRED_SOURCE = 'FRED (Federal Reserve Bank of St. Louis)'


class MacroFRED:
    """FRED indicators with explicit provenance."""

    API_URL = "https://api.stlouisfed.org/fred/series/observations"

    # name: (series_id, transform, unit)
    INDICATORS = {
        'CPI_YOY': ('CPIAUCSL', 'yoy', '% YoY'),
        'CORE_CPI_YOY': ('CPILFESL', 'yoy', '% YoY'),
        'UNEMPLOYMENT': ('UNRATE', 'level', '%'),
        'FED_FUNDS': ('FEDFUNDS', 'level', '%'),
        'T10Y2Y': ('T10Y2Y', 'level', 'percentage points'),
        'VIX': ('VIXCLS', 'level', 'index'),
    }

    def __init__(self):
        self.api_key = os.getenv('FRED_API_KEY', '').strip()
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(db_path())
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS macro_data (
            indicator TEXT,
            value REAL,
            date TEXT,
            source TEXT,
            confidence INTEGER,
            timestamp TEXT,
            PRIMARY KEY (indicator, date)
        )''')
        conn.commit()
        conn.close()

    def fetch_observations(self, series_id, years=3):
        """Return [(date, float)] sorted by date; raises on HTTP/parsing errors."""
        start = (datetime.now() - timedelta(days=365 * years)).strftime('%Y-%m-%d')
        response = requests.get(self.API_URL, params={
            'series_id': series_id, 'api_key': self.api_key, 'file_type': 'json',
            'observation_start': start}, timeout=15)
        response.raise_for_status()
        observations = []
        for obs in response.json().get('observations', []):
            if obs.get('value') in (None, '.', ''):
                continue  # FRED marks missing observations with '.'
            observations.append((date.fromisoformat(obs['date']), float(obs['value'])))
        observations.sort()
        return observations

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
        series_id, transform, unit = self.INDICATORS[name]
        url = f"https://fred.stlouisfed.org/series/{series_id}"
        if not self.api_key:
            return unavailable(FRED_SOURCE, 'FRED_API_KEY not set', series_id=series_id, url=url)
        try:
            observations = self.fetch_observations(series_id)
        except Exception as e:
            return unavailable(FRED_SOURCE, f"{type(e).__name__}: {e}", series_id=series_id, url=url)

        if transform == 'yoy':
            value, obs_date = self.year_over_year(observations)
        elif observations:
            obs_date, value = observations[-1]
        else:
            value, obs_date = None, None

        if value is None:
            return unavailable(FRED_SOURCE, 'insufficient observations', series_id=series_id, url=url)

        return {
            'status': 'OK',
            'value': value,
            'unit': unit,
            'observation_date': obs_date.isoformat(),
            'series_id': series_id,
            'transform': transform,
            'source': FRED_SOURCE,
            'url': url,
            'retrieved_at': utc_now_iso(),
        }

    def save_to_db(self, indicator, value, obs_date):
        try:
            conn = sqlite3.connect(db_path())
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO macro_data
                (indicator, value, date, source, confidence, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)''',
                      (indicator, value, obs_date, FRED_SOURCE, None, utc_now_iso()))
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            print(f"  [DB Error] {e}")

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
                self.save_to_db(name, data['value'], data['observation_date'])
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
