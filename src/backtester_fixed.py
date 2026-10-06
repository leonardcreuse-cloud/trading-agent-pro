#!/usr/bin/env python3
"""
Backtester Fixed - Correct 2-year validation WITHOUT look-ahead bias
"""

import yfinance as yf
import sqlite3
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from .common import db_path


class BacktesterFixed:
    """Backtest CORRECTLY - no look-ahead bias, proper train/test split"""
    
    def __init__(self):
        self.init_db()
    
    def init_db(self):
        """Initialize backtest results table"""
        conn = sqlite3.connect(db_path())
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS backtest_fixed (
            ticker TEXT,
            date TEXT,
            predicted_signal TEXT,
            actual_direction TEXT,
            correct INTEGER,
            return_5d REAL,
            split_type TEXT,
            timestamp TEXT,
            PRIMARY KEY (ticker, date)
        )''')
        
        conn.commit()
        conn.close()
    
    def fetch_historical_data(self, ticker):
        """Fetch 2-year historical price data"""
        print(f"  [YFINANCE] Fetching 2-year data for {ticker}...")
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=730)
            
            data = yf.download(ticker, start=start_date, end=end_date, progress=False)
            
            if data.empty or len(data) < 100:
                print(f"  ❌ Insufficient data")
                return None
            
            print(f"  ✓ Downloaded {len(data)} days")
            return data
        
        except Exception as e:
            print(f"  ❌ Error: {str(e)}")
            return None
    
    def run(self, ticker):
        """Correct backtest with train/test split FIRST"""
        print(f"\n[BACKTESTER FIXED] {ticker}")
        print("=" * 60)
        
        # Step 1: Fetch data
        data = self.fetch_historical_data(ticker)
        if data is None:
            return {'ticker': ticker, 'error': 'No data'}
        
        # Step 2: SPLIT FIRST (80% train, 20% test)
        split_idx = int(len(data) * 0.8)
        train_data = data.iloc[:split_idx].copy()
        test_data = data.iloc[split_idx:].copy()
        
        print(f"  Train: {len(train_data)} days")
        print(f"  Test:  {len(test_data)} days")
        
        # Step 3: Calculate indicators ONLY on train
        train_data['momentum_20'] = (train_data['Close'] / train_data['Close'].rolling(20).mean() - 1) * 100
        
        # Get train mean/std for train set signals
        train_momentum_mean = train_data['momentum_20'].mean()
        train_momentum_std = train_data['momentum_20'].std()
        
        # Step 4: Generate signals on train (for reference)
        train_data['signal'] = 'HOLD'
        train_data.loc[train_data['momentum_20'] > train_momentum_mean + train_momentum_std, 'signal'] = 'BUY'
        train_data.loc[train_data['momentum_20'] < train_momentum_mean - train_momentum_std, 'signal'] = 'SELL'
        
        print(f"  Train signals generated")
        
        # Step 5: Apply train parameters to test set
        test_data['momentum_20'] = (test_data['Close'] / test_data['Close'].rolling(20).mean() - 1) * 100
        test_data['signal'] = 'HOLD'
        test_data.loc[test_data['momentum_20'] > train_momentum_mean + train_momentum_std, 'signal'] = 'BUY'
        test_data.loc[test_data['momentum_20'] < train_momentum_mean - train_momentum_std, 'signal'] = 'SELL'
        
        # Step 6: Calculate FUTURE returns (shift +5, not -5)
        # At T0, return_5d = price at T+5 vs price at T0
        # This is known ONLY AFTER T+5
        test_data['return_5d'] = test_data['Close'].shift(-5) / test_data['Close'] - 1
        
        # Step 7: Evaluate (drop NaN rows at end)
        test_eval = test_data.dropna()
        
        results = []
        for idx in range(len(test_eval)):
            signal = str(test_eval['signal'].values[idx])
            return_val = float(test_eval['return_5d'].values[idx])
            date_val = test_eval.index[idx].strftime('%Y-%m-%d')
            
            # Actual direction
            if return_val > 0.02:
                actual = 'UP'
            elif return_val < -0.02:
                actual = 'DOWN'
            else:
                actual = 'FLAT'
            
            # Correctness (with transaction cost -0.05%)
            cost = -0.0005
            adjusted_return = return_val + cost
            
            correct = 0
            if (signal == 'BUY' and adjusted_return > 0) or \
               (signal == 'SELL' and adjusted_return < 0) or \
               (signal == 'HOLD' and abs(adjusted_return) <= 0.01):
                correct = 1
            
            results.append({
                'date': date_val,
                'signal': signal,
                'actual': actual,
                'return': return_val * 100,
                'correct': correct,
                'split': 'TEST'
            })
        
        # Step 8: Calculate metrics
        if results:
            correct = sum(r['correct'] for r in results)
            accuracy = (correct / len(results)) * 100
            
            returns = [r['return'] for r in results]
            wins = sum(1 for r in returns if r > 0)
            win_rate = (wins / len(returns)) * 100 if returns else 0
            
            total_profit = sum(returns)
            max_loss = min(returns) if returns else 0
            
            avg_return = np.mean(returns) if returns else 0
            std_return = np.std(returns) if returns else 1
            sharpe = (avg_return / std_return * np.sqrt(252)) if std_return > 0 else 0
            
            print(f"  Accuracy (TEST):    {accuracy:.2f}%")
            print(f"  Win Rate (TEST):    {win_rate:.2f}%")
            print(f"  Total P&L (TEST):   {total_profit:.2f}%")
            print(f"  Max Loss (TEST):    {max_loss:.2f}%")
            print(f"  Sharpe (TEST):      {sharpe:.2f}")
            print("=" * 60)
            
            return {
                'ticker': ticker,
                'accuracy': round(accuracy, 2),
                'win_rate': round(win_rate, 2),
                'total_pnl': round(total_profit, 2),
                'sharpe': round(sharpe, 2),
                'periods_tested': len(results),
                'note': 'FIXED: train/test split BEFORE indicators, shift +5'
            }
        
        return {'ticker': ticker, 'error': 'No valid results'}


if __name__ == "__main__":
    bt = BacktesterFixed()
    for ticker in ['CRWD', 'NET', 'RKLB', 'MP']:
        result = bt.run(ticker)
        print(f"  Result: {result}\n")
