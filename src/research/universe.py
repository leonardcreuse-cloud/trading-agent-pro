#!/usr/bin/env python3
"""
Research universe (phase P2.1)

Source: current S&P 500 members from github.com/datasets/s-and-p-500-companies (third-party,
source rank 3), downloaded through the provenance log (raw CSV kept).

Rule (fixed before any result):
- exclude GICS sectors Financials and Real Estate (revenue, margins and debt-to-equity are
  not comparable for banks, insurers and REITs);
- stage sizes: a seeded random sample (SEED) of the remaining members, then all of them;
- membership at date T: a stock is in the universe only from its 'Date added' to the index,
  so later inclusions are not used before they happened;
- one listing per company: share classes of the same CIK (GOOG / GOOGL, FOX / FOXA, NWS / NWSA)
  are kept once (first ticker alphabetically), otherwise one company would count twice.

Known biases (reported with every result):
- survivorship: companies that left the index before today are absent (no free
  point-in-time membership history);
- GICS sector is today's classification, used as a static label.
"""

import csv
import io
import random

from ..common import utc_now_iso
from ..database import Database

LIST_SOURCE = 'S&P 500 list (datasets/s-and-p-500-companies)'
LIST_URL = ('https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/'
            'constituents.csv')
EXCLUDED_SECTORS = ('Financials', 'Real Estate')
SEED = 2026


def parse_constituents(text):
    """Rows {ticker, yahoo_ticker, name, sector, sub_industry, date_added, cik}."""
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        symbol = (r.get('Symbol') or '').strip()
        if not symbol:
            continue
        added = (r.get('Date added') or '').strip()[:10] or None
        rows.append({'ticker': symbol, 'yahoo_ticker': symbol.replace('.', '-'),
                     'name': (r.get('Security') or '').strip(),
                     'sector': (r.get('GICS Sector') or '').strip(),
                     'sub_industry': (r.get('GICS Sub-Industry') or '').strip(),
                     'date_added': added,
                     'cik': str(r['CIK']).zfill(10) if (r.get('CIK') or '').strip() else None})
    return rows


class Universe:
    def __init__(self, db=None, session=None):
        self.db = db or Database()
        self.session = session
        self.rows = None
        self.fetch = None

    def load(self):
        """Download the list (logged, raw stored); returns the rows."""
        import requests
        session = self.session or requests.Session()
        requested_at = utc_now_iso()
        try:
            response = session.get(LIST_URL, timeout=30)
            response.raise_for_status()
        except Exception as e:  # noqa: BLE001 - recorded and re-raised: no universe, no study
            self.db.record_fetch(LIST_SOURCE, LIST_URL, requested_at=requested_at,
                                 status='DATA UNAVAILABLE', error=f'{type(e).__name__}: {e}')
            raise
        self.rows = parse_constituents(response.text)
        self.fetch = self.db.record_fetch(LIST_SOURCE, LIST_URL, requested_at=requested_at,
                                          status='OK', raw=response.text, raw_ext='csv',
                                          n_records=len(self.rows))
        return self.rows

    def eligible(self):
        seen, out = set(), []
        for r in sorted(self.rows or self.load(), key=lambda r: r['ticker']):
            if r['sector'] in EXCLUDED_SECTORS or (r['cik'] and r['cik'] in seen):
                continue
            seen.add(r['cik'])
            out.append(r)
        return out

    def stage(self, size=None, seed=SEED):
        """Seeded random sample of eligible members (all of them when size is None)."""
        rows = sorted(self.eligible(), key=lambda r: r['ticker'])
        if size is None or size >= len(rows):
            return rows
        return sorted(random.Random(seed).sample(rows, size), key=lambda r: r['ticker'])


def member_at(row, day):
    """True if the stock was in the index at `day` (unknown date added: assumed member)."""
    return row.get('date_added') is None or row['date_added'] <= str(day)[:10]
