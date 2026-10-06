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
"""

import yfinance as yf
import sqlite3
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from .common import close_series, db_path, unavailable, utc_now_iso


class Backtester:
    """Backtest predictions vs real historical data"""

    def __init__(self):
        self.init_db()

    def init_db(self):
        """Initialize backtest results table"""
        conn = sqlite3.connect(db_path())
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS backtest_results (
            ticker TEXT,
            date TEXT,
            predicted_signal TEXT,
            actual_direction TEXT,
            accuracy_5d INTEGER,
            profit_loss REAL,
            timestamp TEXT,
            PRIMARY KEY (ticker, date)
        )''')

        conn.commit()
        conn.close()

    def fetch_historical_data(self, ticker):
        """Fetch real 2-year historical price data from yfinance"""
        print(f"  [YFINANCE] Fetching 2-year data for {ticker}...")

        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=730)

            data = yf.download(ticker, start=start_date, end=end_date, progress=False,
                               auto_adjust=True)

            if data is None or data.empty:
                print(f"  No data found for {ticker}")
                return None

            frame = pd.DataFrame({'Close': close_series(data)})
            print(f"  Downloaded {len(frame)} days")
            return frame

        except Exception as e:
            print(f"  Error: {str(e)}")
            return None

    def calculate_returns(self, data):
        """Calculate 5-day forward returns"""
        data['return_5d'] = data['Close'].shift(-5) / data['Close'] - 1
        return data

    def generate_predictions(self, data):
        """Causal 20-day momentum signal (uses past prices only)"""
        data['momentum'] = (data['Close'] / data['Close'].rolling(20).mean() - 1) * 100

        data['signal'] = 'HOLD'
        data.loc[data['momentum'] > 2, 'signal'] = 'BUY'
        data.loc[data['momentum'] < -2, 'signal'] = 'SELL'

        return data

    def evaluate_predictions(self, data):
        """Evaluate prediction accuracy vs actual returns"""
        results = []

        data = data.dropna()

        for idx in range(len(data)):
            return_val = float(data['return_5d'].values[idx])
            signal = str(data['signal'].values[idx])
            date_val = data.index[idx].strftime('%Y-%m-%d')

            if return_val > 0.02:
                actual = 'UP'
            elif return_val < -0.02:
                actual = 'DOWN'
            else:
                actual = 'FLAT'

            correct = 0
            if (signal == 'BUY' and actual == 'UP') or (signal == 'SELL' and actual == 'DOWN') or (signal == 'HOLD' and actual == 'FLAT'):
                correct = 1

            results.append({
                'date': date_val,
                'signal': signal,
                'actual': actual,
                'correct': correct,
                'return': return_val * 100
            })

        return results

    def save_results(self, ticker, results):
        """Save backtest results to DB"""
        conn = sqlite3.connect(db_path())
        c = conn.cursor()

        for result in results:
            c.execute('''INSERT OR IGNORE INTO backtest_results
                (ticker, date, predicted_signal, actual_direction, accuracy_5d, profit_loss, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (ticker, result['date'], result['signal'], result['actual'], result['correct'], result['return'], datetime.now().isoformat()))

        conn.commit()
        conn.close()

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
            return unavailable('yfinance', 'no price data', ticker=ticker)

        test_start = int(len(data) * 0.80)
        # Momentum is causal, so it can be computed on the full series; only the
        # evaluation is restricted to the last 20% of the period.
        data = self.calculate_returns(data)
        data = self.generate_predictions(data)
        data_test = data.iloc[test_start:]

        results = self.evaluate_predictions(data_test)
        self.save_results(ticker, results)
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
            'source': 'yfinance 2Y adjusted close',
            'computed_at': utc_now_iso(),
        }


if __name__ == "__main__":
    from .common import tickers
    bt = Backtester()
    for t in tickers():
        bt.run(t)
