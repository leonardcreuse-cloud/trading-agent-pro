#!/usr/bin/env python3
"""
Phase 4 - Prediction Engine
Objective: P(up) 1D/5D/20D/60D + Expected Return
Source: REAL data from backtester_no_bias.py only
"""

import yfinance as yf
from datetime import datetime, timedelta
import numpy as np
import pandas as pd


class PredictionEngine:
    """Calculate P(up) and Expected Return for multiple horizons"""

    def __init__(self):
        self.horizons = [1, 5, 20, 60]

    def calculate_returns(self, prices):
        """Calculate forward returns for each horizon - FIXED scalars"""
        results = {}
        
        for horizon in self.horizons:
            forward_prices = prices.shift(-horizon)
            returns = ((forward_prices - prices) / prices) * 100
            returns_clean = returns.dropna().values
            
            if len(returns_clean) == 0:
                continue
            
            # P(up) as scalar
            p_up = float(np.sum(returns_clean > 0) / len(returns_clean) * 100)
            
            # Expected return (mean of positive returns only)
            positive_returns = returns_clean[returns_clean > 0]
            expected_return = float(np.mean(positive_returns)) if len(positive_returns) > 0 else 0.0
            
            results[f'{horizon}D'] = {
                'p_up': round(p_up, 2),
                'expected_return': round(expected_return, 2),
                'sample_size': len(returns_clean)
            }
        
        return results

    def analyze(self, ticker):
        """Complete multi-horizon analysis"""
        print(f"\n[PREDICTION ENGINE] {ticker}")
        print("=" * 60)
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=730)
        
        data = yf.download(ticker, start=start_date, end=end_date, progress=False)
        
        if data.empty or len(data) < 100:
            print(f"  WARNING: Insufficient data ({len(data)} days)")
            return None
        
        split_idx = int(len(data) * 0.8)
        test_data = data.iloc[split_idx:].copy()
        
        close_prices = test_data['Close']
        results = self.calculate_returns(close_prices)
        
        print(f"  Data: {len(data)} days total, {len(test_data)} days test")
        print(f"\n  Multi-Horizon Predictions (from REAL data):")
        for horizon, metrics in results.items():
            print(f"    {horizon}: P(up)={metrics['p_up']}%, E[return]={metrics['expected_return']}%")
        
        return {
            'ticker': ticker,
            'data_points': len(test_data),
            'horizons': results
        }


if __name__ == "__main__":
    pe = PredictionEngine()
    for ticker in ["CRWD", "NET", "RKLB", "MP"]:
        pe.analyze(ticker)
