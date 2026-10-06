#!/usr/bin/env python3
"""
Scoring Fundamentals

P0.1 changes:
- Missing inputs produce None, never a neutral 50.
- Revenue and debt-to-equity are DATA UNAVAILABLE until XBRL ingestion (phase P0.3),
  so the fundamental score is currently unavailable.
- The Form 4 "insider score" was removed: it treated MORE Form 4 filings as bullish,
  but for these companies Form 4s are mostly sales and RSU vesting. Insider activity
  will come back once transactions are parsed (buy vs sell).
- Thresholds remain heuristic (not calibrated) and will be replaced in phase P1.
"""


from .common import DATA_UNAVAILABLE, is_missing, utc_now_iso
from .sec_parser import SECParser


class ScoringFundamentals:
    """Heuristic fundamental score from SEC data (None when inputs are missing)."""

    WEIGHTS = {'revenue_scale': 0.55, 'leverage': 0.45}

    def __init__(self, sec_parser=None):
        self.sec_parser = sec_parser or SECParser()

    def get_sec_data(self, ticker):
        return {
            'revenue': self.sec_parser.fetch_revenue(ticker),
            'debt_to_equity': self.sec_parser.fetch_debt_equity(ticker),
        }

    @staticmethod
    def calculate_revenue_scale_score(revenue):
        """Heuristic score on revenue size (not profitability). None if missing."""
        if is_missing(revenue):
            return None
        if revenue > 1_000_000_000:
            return 80
        if revenue > 500_000_000:
            return 70
        if revenue > 200_000_000:
            return 60
        return 45

    @staticmethod
    def calculate_leverage_score(de_ratio):
        """Heuristic score on debt-to-equity. None if missing."""
        if is_missing(de_ratio):
            return None
        if de_ratio < 0.5:
            return 90
        if de_ratio < 1.0:
            return 75
        if de_ratio < 1.5:
            return 60
        if de_ratio < 2.0:
            return 45
        return 30

    def calculate_composite_score(self, components):
        """Weighted average over AVAILABLE components only; None if all missing."""
        available = {k: v for k, v in components.items() if v is not None}
        if not available:
            return None
        total_weight = sum(self.WEIGHTS[k] for k in available)
        return round(sum(v * self.WEIGHTS[k] for k, v in available.items()) / total_weight, 2)

    def analyze(self, ticker):
        print(f"  [FUNDAMENTALS] {ticker}...")
        sec_data = self.get_sec_data(ticker)

        components = {
            'revenue_scale': self.calculate_revenue_scale_score(sec_data['revenue']),
            'leverage': self.calculate_leverage_score(sec_data['debt_to_equity']),
        }
        composite = self.calculate_composite_score(components)
        available = [k for k, v in components.items() if v is not None]

        if composite is None:
            signal = None
        elif composite >= 70:
            signal = 'BUY'
        elif composite <= 40:
            signal = 'SELL'
        else:
            signal = 'HOLD'

        return {
            'ticker': ticker,
            'fundamental_score': composite,
            'signal': signal,
            'status': 'OK' if composite is not None else DATA_UNAVAILABLE,
            'coverage': f"{len(available)}/{len(components)}",
            'components': components,
            'inputs': sec_data,
            'score_type': 'heuristic 0-100 score, not a probability',
            'reason': None if composite is not None else
                      'Revenue and debt-to-equity not available (SEC XBRL ingestion planned P0.3)',
            'timestamp': utc_now_iso(),
            'source': 'SEC EDGAR',
        }


if __name__ == "__main__":
    from .common import tickers
    fund = ScoringFundamentals()
    for t in tickers():
        r = fund.analyze(t)
        print(f"    {t}: score={r['fundamental_score']}, status={r['status']}")
