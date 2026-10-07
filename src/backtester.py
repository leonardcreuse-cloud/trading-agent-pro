#!/usr/bin/env python3
"""
Backtester - 2-year momentum signal check with yfinance (PROVISIONAL)

P0.1 changes - only metrics that are actually valid are reported:
- Removed sharpe_ratio, max_drawdown and total_profit: they were computed on
  overlapping 5-day returns of ALL days (not strategy returns), the "drawdown" was
  the worst single return and the Sharpe was inflated by ~sqrt(5).
- 'win_rate' renamed 'unconditional_up_rate_pct': it is the share of positive 5-day
  returns regardless of the signal, i.e. a property of the stock, not of the strategy.
- 3-class accuracy is now shown next to the majority-class baseline accuracy.
- Note: the momentum signal itself is causal (rolling mean over past prices); the
  former "split before computing momentum" did not fix any leakage. The train set
  is not used to fit anything.
- A full strategy backtest (positions, costs, benchmark, drawdown) is phase P1.1.

P0.2: prices from the shared PriceFeed; per-day results are stored in the provenance-aware
backtest_results table (schema owned by database.py) with the session that resolves the
outcome (outcome_date) and the price fetch they were computed from. The legacy table
(no provenance, ambiguous timestamps) is backed up and dropped by the v2 migration.
"""

import pandas as pd

from .common import unavailable, utc_now_iso
from .database import Database
from .market_data import PriceFeed

METHOD = 'momentum20_threshold2pct_5d_v1'
HORIZON = 5


class Backtester:
    """Backtest predictions vs real historical data"""

    def __init__(self, price_feed=None, db=None):
        self.db = db or (price_feed.db if price_feed else Database())
        self.price_feed = price_feed
        self.last_prices = None

    def fetch_historical_data(self, ticker):
        """2 years of completed daily adjusted closes from the shared price feed."""
        print(f"  [YFINANCE] 2-year prices for {ticker}...")
        if self.price_feed is None:
            self.price_feed = PriceFeed(db=self.db)
        prices = self.price_feed.get(ticker)
        self.last_prices = prices
        if prices['status'] != 'OK':
            print(f"  No data: {prices['reason']}")
            return None
        frame = pd.DataFrame({'Close': prices['close']})
        print(f"  {len(frame)} sessions (fetch #{prices['fetch']['fetch_id']})")
        return frame

    def calculate_returns(self, data):
        """Calculate 5-day forward returns"""
        data['return_5d'] = data['Close'].shift(-HORIZON) / data['Close'] - 1
        data['outcome_date'] = pd.Series(data.index, index=data.index).shift(-HORIZON)
        return data

    def generate_predictions(self, data):
        """Causal 20-day momentum signal (uses past prices only)"""
        data['momentum'] = (data['Close'] / data['Close'].rolling(20).mean() - 1) * 100

        data['signal'] = 'NEUTRAL'
        data.loc[data['momentum'] > 2, 'signal'] = 'POSITIVE'
        data.loc[data['momentum'] < -2, 'signal'] = 'NEGATIVE'

        return data

    def evaluate_predictions(self, data):
        """Evaluate prediction accuracy vs actual returns"""
        results = []

        data = data.dropna()

        for idx in range(len(data)):
            return_val = float(data['return_5d'].values[idx])
            signal = str(data['signal'].values[idx])
            date_val = data.index[idx].strftime('%Y-%m-%d')
            outcome_date = pd.Timestamp(data['outcome_date'].values[idx]).strftime('%Y-%m-%d')

            if return_val > 0.02:
                actual = 'UP'
            elif return_val < -0.02:
                actual = 'DOWN'
            else:
                actual = 'FLAT'

            correct = 0
            if (signal == 'POSITIVE' and actual == 'UP') or (signal == 'NEGATIVE' and actual == 'DOWN') or (signal == 'NEUTRAL' and actual == 'FLAT'):
                correct = 1

            results.append({
                'date': date_val,
                'outcome_date': outcome_date,
                'signal': signal,
                'actual': actual,
                'correct': correct,
                'return': return_val * 100
            })

        return results

    def save_results(self, ticker, results, fetch):
        """Store per-day results with the price fetch they come from."""
        computed_at = utc_now_iso()
        return self.db.save_backtest_results([{
            'ticker': ticker, 'signal_date': r['date'], 'horizon_days': HORIZON,
            'predicted_signal': r['signal'], 'actual_direction': r['actual'],
            'correct': r['correct'], 'forward_return_pct': r['return'],
            'outcome_date': r['outcome_date'], 'method': METHOD,
            'price_fetch_id': fetch['fetch_id'], 'computed_at': computed_at,
        } for r in results])

    def calculate_metrics(self, results):
        """Valid descriptive metrics only (see module docstring)."""
        if not results:
            return {}

        n = len(results)
        accuracy = sum(r['correct'] for r in results) / n * 100
        actual_counts = {}
        for r in results:
            actual_counts[r['actual']] = actual_counts.get(r['actual'], 0) + 1
        majority_class = max(actual_counts, key=actual_counts.get)
        baseline_accuracy = actual_counts[majority_class] / n * 100
        up_rate = sum(1 for r in results if r['return'] > 0) / n * 100

        return {
            'accuracy_3class_pct': round(accuracy, 2),
            'baseline_majority_class': majority_class,
            'baseline_accuracy_pct': round(baseline_accuracy, 2),
            'unconditional_up_rate_pct': round(up_rate, 2),
            'periods_tested': n,
            'independent_5d_periods': n // 5,
        }

    def run(self, ticker):
        """Momentum signal accuracy on the last 20% of 2 years of data (PROVISIONAL)."""
        print(f"\n[BACKTESTER - PROVISIONAL] {ticker}")
        print("=" * 60)

        data = self.fetch_historical_data(ticker)
        if data is None:
            return unavailable('yfinance', (self.last_prices or {}).get('reason') or 'no price data',
                               ticker=ticker, provenance=(self.last_prices or {}).get('provenance'))

        test_start = int(len(data) * 0.80)
        # Momentum is causal, so it can be computed on the full series; only the
        # evaluation is restricted to the last 20% of the period.
        data = self.calculate_returns(data)
        data = self.generate_predictions(data)
        data_test = data.iloc[test_start:]

        results = self.evaluate_predictions(data_test)
        self.save_results(ticker, results, self.last_prices['fetch'])
        metrics = self.calculate_metrics(results)

        print(f"  Evaluation days:       {metrics.get('periods_tested', 0)} "
              f"(~{metrics.get('independent_5d_periods', 0)} independent 5d periods)")
        print(f"  3-class accuracy:      {metrics.get('accuracy_3class_pct')}%")
        print(f"  Majority baseline:     {metrics.get('baseline_accuracy_pct')}% "
              f"(always '{metrics.get('baseline_majority_class')}')")
        print("=" * 60)

        return {
            'ticker': ticker,
            'status': 'PROVISIONAL',
            'backtest_results': metrics,
            'periods_tested': metrics.get('periods_tested', 0),
            'evaluation_start': str(data_test.index[0].date()) if len(data_test) else None,
            'evaluation_end': str(data_test.index[-1].date()) if len(data_test) else None,
            'warning': ('Signal accuracy check only: no positions, costs, benchmark or '
                        'drawdown. Small, overlapping sample. Full backtest in phase P1.1.'),
            'method': METHOD,
            'source': 'yfinance 2Y adjusted close',
            'provenance': self.last_prices['provenance'],
            'computed_at': utc_now_iso(),
        }


if __name__ == "__main__":
    from .common import tickers
    bt = Backtester()
    for t in tickers():
        bt.run(t)
