#!/usr/bin/env python3
import yfinance as yf
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

class BacktesterNoLeak:
    def run(self, ticker):
        print(f"\n[NO BIAS] {ticker}")
        print("=" * 60)

        end_date = datetime.now()
        start_date = end_date - timedelta(days=730)
        data = yf.download(ticker, start=start_date, end=end_date, progress=False)

        if data.empty or len(data) < 100:
            return

        split_idx = int(len(data) * 0.8)
        train = data.iloc[:split_idx].copy()
        test = data.iloc[split_idx:].copy()

        train['mom'] = (train['Close'] / train['Close'].rolling(20).mean() - 1) * 100
        mom_mean = train['mom'].mean()
        mom_std = train['mom'].std()

        test['mom'] = (test['Close'] / test['Close'].rolling(20).mean() - 1) * 100
        test['signal'] = 'HOLD'
        test.loc[test['mom'] > mom_mean + mom_std, 'signal'] = 'BUY'
        test.loc[test['mom'] < mom_mean - mom_std, 'signal'] = 'SELL'

        test = test[:-5]
        test['ret'] = test['Close'].shift(-5) / test['Close'] - 1
        test = test.dropna()

        correct = 0
        for i in range(len(test)):
            sig = test['signal'].values[i]
            ret = test['ret'].values[i]
            dir = 'UP' if ret > 0.02 else ('DOWN' if ret < -0.02 else 'FLAT')
            if (sig == 'BUY' and dir == 'UP') or (sig == 'SELL' and dir == 'DOWN') or (sig == 'HOLD' and dir == 'FLAT'):
                correct += 1

        acc = (correct / len(test)) * 100
        wins = sum(1 for r in test['ret'].values if r > 0)
        wr = (wins / len(test)) * 100

        print(f"  Accuracy: {acc:.2f}%")
        print(f"  Win Rate: {wr:.2f}%")
        print("=" * 60)

if __name__ == "__main__":
    b = BacktesterNoLeak()
    for t in ['CRWD', 'NET', 'RKLB', 'MP']:
        b.run(t)
