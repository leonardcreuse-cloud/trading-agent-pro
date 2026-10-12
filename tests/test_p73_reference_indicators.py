"""
Gap round G2: src/technicals.py against an independent reference implementation (stockstats, requirements-dev.txt).
Synthetic bars (a seeded random walk, test only). Live check on NVDA / SPY bars (2026-10-12): the same agreement,
recorded in docs/MISSION_STATUS.md.

Documented conventions that differ from the reference:
  - Bollinger bands use the population standard deviation (ddof 0, Bollinger's definition); stockstats uses ddof 1.
  - ADX is Wilder's (Wilder average of DX over 14 periods); stockstats' default 'adx' is a 6-period average of DX.
    +DI, -DI and DX match, and Wilder's average of the reference DX matches our ADX.
"""

import numpy as np
import pandas as pd
import pytest

stockstats = pytest.importorskip('stockstats')


@pytest.fixture
def bars():
    rng = np.random.default_rng(7)
    n = 600
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
    spread = np.abs(rng.normal(0, 0.01, n)) * close
    open_ = close * (1 + rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    idx = pd.bdate_range('2024-01-01', periods=n)
    return pd.DataFrame({'open': open_, 'high': high, 'low': low, 'close': close,
                         'volume': rng.integers(1_000_000, 5_000_000, n).astype(float)}, index=idx)


def _rel(a, b, last=250):
    a = pd.Series(np.asarray(a, dtype=float)).iloc[-last:]
    b = pd.Series(np.asarray(b, dtype=float)).iloc[-last:]
    return float(((a - b).abs() / b.abs().clip(lower=1e-9)).max())


def test_indicators_match_the_reference(bars):
    from src import technicals as T
    ss = stockstats.wrap(bars.copy())
    m = T.macd(bars['close'])
    assert _rel(T.rsi(bars['close']), ss['rsi_14']) < 1e-6
    assert _rel(m['macd'], ss['macd']) < 1e-5 and _rel(m['signal'], ss['macds']) < 1e-5
    assert _rel(T.atr(bars['high'], bars['low'], bars['close']), ss['atr_14']) < 1e-6
    assert _rel(T.bollinger(bars['close'])['middle'], ss['boll']) < 1e-12
    d = T.adx(bars['high'], bars['low'], bars['close'])
    assert _rel(d['plus_di'], ss['pdi_14']) < 1e-6 and _rel(d['minus_di'], ss['ndi_14']) < 1e-6


def test_documented_conventions(bars):
    from src import technicals as T
    ss = stockstats.wrap(bars.copy())
    c = bars['close']
    sample_upper = c.rolling(20).mean() + 2 * c.rolling(20).std(ddof=1)
    assert _rel(sample_upper, ss['boll_ub']) < 1e-12                      # the reference uses ddof 1
    assert _rel(T.bollinger(c)['upper'], ss['boll_ub']) > 1e-5             # ours: ddof 0, by definition
    d = T.adx(bars['high'], bars['low'], bars['close'])
    ours_dx = 100 * (d['plus_di'] - d['minus_di']).abs() / (d['plus_di'] + d['minus_di'])
    dx = ss['dx_14'][ours_dx.notna()]                         # the reference DX on the dates where ours exists
    assert _rel(ours_dx[ours_dx.notna()], dx) < 1e-6
    v = dx.to_numpy()
    wilder = np.full(len(v), np.nan)
    wilder[13] = v[:14].mean()
    for i in range(14, len(v)):
        wilder[i] = (wilder[i - 1] * 13 + v[i]) / 14
    wilder = pd.Series(wilder, index=dx.index)
    common = d['adx'].dropna().index.intersection(wilder.dropna().index)[-250:]
    assert _rel(d['adx'][common], wilder[common]) < 1e-6                  # Wilder's average of the reference DX
