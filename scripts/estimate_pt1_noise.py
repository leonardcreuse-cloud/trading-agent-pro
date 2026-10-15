#!/usr/bin/env python3
"""
Estimate src/uncertainty.WEEKLY_EXCESS_SD: how far an 8-stock equal-weight portfolio drawn at random from the 40
tickers of stage 3 / PT1 strays from the 40-ticker average, week by week.

Inputs: the stored yfinance adjusted closes (observations, source 'yfinance', metric 'close') of the 40 tickers,
2021-10-01 to 2026-10-09; weekly returns Friday to Friday. 2,000 random portfolios (seed 1); the median of their
weekly excess-return SDs is the estimate.

No signal and no PT1 result is used: this measures portfolio noise only.
Run on 2026-10-14 and 2026-10-15: 260 weeks, 40 tickers, SD 1.6050% per week (±11.6% over 52 weeks at one SD).

Usage: python scripts/estimate_pt1_noise.py
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common import data_dir  # noqa: E402
from src.prospective import UNIVERSE  # noqa: E402

START, END, DRAWS, SEED, SIZE = '2021-10-01', '2026-10-09', 2000, 1, 8


def main():
    conn = sqlite3.connect(data_dir() / 'trading_pro.db')
    rows = conn.execute(
        f"SELECT entity, as_of_date, value FROM observations WHERE source='yfinance' AND metric='close' AND entity IN "
        f"({','.join('?' * len(UNIVERSE))}) AND as_of_date BETWEEN ? AND ? ORDER BY retrieved_at, fetch_id",
        (*UNIVERSE, START, END)).fetchall()
    df = (pd.DataFrame(rows, columns=['t', 'd', 'v']).drop_duplicates(['t', 'd'], keep='last')
          .pivot(index='d', columns='t', values='v').sort_index())
    df.index = pd.to_datetime(df.index)
    weekly = df.resample('W-FRI').last().pct_change().iloc[1:]
    weekly = weekly.dropna(axis=1, thresh=int(len(weekly) * 0.9))
    rng = np.random.default_rng(SEED)
    ew = weekly.mean(axis=1)
    sds = [(weekly[rng.choice(weekly.columns, SIZE, replace=False)].mean(axis=1) - ew).std() for _ in range(DRAWS)]
    sd = float(np.median(sds))
    print(f'weeks {len(weekly)}, tickers {weekly.shape[1]}: weekly excess SD {sd:.4%}; '
          f'one SD over 52 weeks {sd * np.sqrt(52):.1%}; 95% band over 52 weeks ±{1.96 * sd * np.sqrt(52):.1%}')


if __name__ == '__main__':
    main()
