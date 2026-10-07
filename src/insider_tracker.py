#!/usr/bin/env python3
"""
Insider Tracker - SEC Form 4

P0.1: the previous version always returned a NEUTRAL signal with zero buys/sells
without reading any filing. Form 4 transactions are not parsed yet, so the module
now reports DATA UNAVAILABLE. Real parsing (transaction codes P/S/M/A) is phase P0.3.

P0.2: the legacy insider_transactions table (never filled, with an invented "confidence"
column) is no longer created; it is backed up and dropped by the v2 migration. The
provenance-aware Form 4 schema is defined with the parser in phase P0.3.
"""

from .common import unavailable


class InsiderTracker:
    """Track insider transactions from SEC Form 4"""

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
