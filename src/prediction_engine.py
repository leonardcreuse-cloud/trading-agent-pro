#!/usr/bin/env python3
"""
Historical base rates (formerly presented as "Prediction Engine")

P0.1 changes - honest labelling of what is computed:
- These numbers are UNCONDITIONAL historical frequencies over a recent window.
  They do not depend on any signal or feature, are not a model, and are not
  calibrated. They must not be read as P(up) predictions.
- mean_return_pct is the mean of ALL forward returns. The previous
  "expected_return" averaged only the positive returns, so it was always positive.
- Sample sizes are reported: n_overlapping windows and n_independent (n // horizon).
  Fewer than MIN_INDEPENDENT independent windows -> flagged as insufficient.
- A real conditional, calibrated, walk-forward-validated model replaces this in P1.6.
"""

import numpy as np
import yfinance as yf
from datetime import datetime, timedelta

from .common import close_series, unavailable, utc_now_iso

METHOD = ('Unconditional historical frequency of positive forward returns over the '
          'window; not a model prediction, not conditional on any signal, not calibrated.')


class PredictionEngine:
    """Historical base rates per horizon (kept under this name for compatibility)."""

    MIN_INDEPENDENT = 10

    def __init__(self, horizons=(1, 5, 20, 60), lookback_days=730, window_fraction=0.2):
        self.horizons = list(horizons)
        self.lookback_days = lookback_days
        self.window_fraction = window_fraction

    def calculate_base_rates(self, close):
        """close: 1-D pandas Series of prices (oldest first)."""
        results = {}
        for horizon in self.horizons:
            forward = (close.shift(-horizon) / close - 1) * 100
            returns = forward.dropna().to_numpy(dtype=float)
            if len(returns) == 0:
                results[f'{horizon}D'] = unavailable('yfinance', 'window shorter than horizon')
                continue
            n_independent = len(returns) // horizon
            results[f'{horizon}D'] = {
                'status': 'OK',
                'historical_up_frequency_pct': round(float(np.mean(returns > 0) * 100), 2),
                'mean_return_pct': round(float(np.mean(returns)), 2),
                'median_return_pct': round(float(np.median(returns)), 2),
                'n_overlapping': int(len(returns)),
                'n_independent': int(n_independent),
                'insufficient_sample': n_independent < self.MIN_INDEPENDENT,
            }
        return results

    def analyze(self, ticker):
        print(f"\n[HISTORICAL BASE RATES] {ticker}")
        print("=" * 60)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.lookback_days)
        try:
            data = yf.download(ticker, start=start_date, end=end_date, progress=False,
                               auto_adjust=True)
        except Exception as e:
            return unavailable('yfinance', f"{type(e).__name__}: {e}", ticker=ticker)
        if data is None or data.empty:
            return unavailable('yfinance', 'no price data', ticker=ticker)

        close = close_series(data)
        if len(close) < 100:
            return unavailable('yfinance', f'only {len(close)} observations', ticker=ticker)

        window = close.iloc[int(len(close) * (1 - self.window_fraction)):]
        results = self.calculate_base_rates(window)

        for horizon, m in results.items():
            if m.get('status') == 'OK':
                flag = ' (INSUFFICIENT SAMPLE)' if m['insufficient_sample'] else ''
                print(f"  {horizon}: up-frequency={m['historical_up_frequency_pct']}%, "
                      f"mean={m['mean_return_pct']}%, n_indep={m['n_independent']}{flag}")

        return {
            'ticker': ticker,
            'status': 'OK',
            'kind': 'historical_base_rate',
            'method': METHOD,
            'is_model_prediction': False,
            'window_start': str(window.index[0].date()),
            'window_end': str(window.index[-1].date()),
            'data_points': int(len(window)),
            'horizons': results,
            'source': 'yfinance (adjusted close)',
            'computed_at': utc_now_iso(),
        }


if __name__ == "__main__":
    from .common import tickers
    engine = PredictionEngine()
    for t in tickers():
        engine.analyze(t)
