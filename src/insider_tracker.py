#!/usr/bin/env python3
"""
Insider Tracker - SEC Form 4

P0.1: the previous version always returned a NEUTRAL signal with zero buys/sells
without reading any filing. Form 4 transactions are not parsed yet, so the module
now reports DATA UNAVAILABLE. Real parsing (transaction codes P/S/M/A) is phase P0.3.
"""

import sqlite3

from .common import db_path, unavailable


class InsiderTracker:
    """Track insider transactions from SEC Form 4"""

    def __init__(self):
        self.init_db()

    def init_db(self):
        """Initialize SQLite for insider data"""
        conn = sqlite3.connect(db_path())
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS insider_transactions (
            ticker TEXT,
            insider_name TEXT,
            insider_role TEXT,
            transaction_type TEXT,
            shares INTEGER,
            price REAL,
            amount REAL,
            date TEXT,
            filing_date TEXT,
            source TEXT,
            confidence INTEGER,
            PRIMARY KEY (ticker, insider_name, date, transaction_type)
        )''')
        conn.commit()
        conn.close()

    def run(self, ticker):
        """Insider analysis for ticker: not implemented, reported as unavailable."""
        print(f"\n[INSIDER TRACKER] {ticker}")
        print("=" * 60)
        print("  Form 4 transaction parsing not implemented yet -> DATA UNAVAILABLE")
        print("=" * 60)

        result = unavailable('SEC Form 4', 'Form 4 transaction parsing not implemented yet (phase P0.3)')
        result.update({
            'ticker': ticker,
            'insider_buys': None,
            'insider_sells': None,
            'signal': None,
        })
        return result


if __name__ == "__main__":
    from .common import tickers
    tracker = InsiderTracker()
    for t in tickers():
        tracker.run(t)
