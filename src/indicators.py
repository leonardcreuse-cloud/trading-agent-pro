#!/usr/bin/env python3
"""
Indicators - Real technical indicators (RSI, MACD, Bollinger Bands) - CLEAN
"""

import numpy as np
import pandas as pd


class Indicators:
    """Calculate professional technical indicators"""

    @staticmethod
    def calculate_rsi(prices, period=14):
        """Relative Strength Index (0-100)"""
        prices = np.array(prices, dtype=float).flatten()  # FLATTEN ICI!
        deltas = np.diff(prices)
        seed = deltas[:period+1]

        up = float(seed[seed >= 0].sum() / period)
        down = abs(float(seed[seed < 0].sum() / period))

        rsi = np.zeros_like(prices)

        # Première valeur RSI
        if down != 0:
            rs = up / down
            rsi[:period] = 100. - (100. / (1. + rs))
        else:
            rsi[:period] = 50.

        # Calcul itératif
        for i in range(period, len(prices)):
            delta = deltas[i-1]
            upval = delta if delta > 0 else 0.
            downval = abs(delta) if delta < 0 else 0.

            up = (up * (period - 1) + upval) / period
            down = (down * (period - 1) + downval) / period

            if down != 0:
                rs = up / down
                rsi[i] = 100. - (100. / (1. + rs))
            else:
                rsi[i] = 50.

        return rsi

    @staticmethod
    def calculate_macd(prices, fast=12, slow=26, signal=9):
        """MACD (Moving Average Convergence Divergence)"""
        prices = np.array(prices, dtype=float).flatten()  # FLATTEN ICI!
        s = pd.Series(prices)
        ema_fast = s.ewm(span=fast).mean().values
        ema_slow = s.ewm(span=slow).mean().values
        macd_line = ema_fast - ema_slow
        signal_line = pd.Series(macd_line).ewm(span=signal).mean().values
        histogram = macd_line - signal_line

        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram
        }

    @staticmethod
    def calculate_bollinger_bands(prices, period=20, num_std=2):
        """Bollinger Bands (SMA ± std deviations)"""
        prices = np.array(prices, dtype=float).flatten()  # FLATTEN ICI!
        s = pd.Series(prices)
        sma = s.rolling(window=period).mean().values
        std = s.rolling(window=period).std().values
        upper = sma + (std * num_std)
        lower = sma - (std * num_std)

        return {
            'upper': upper,
            'middle': sma,
            'lower': lower,
            'std': std
        }


if __name__ == "__main__":
    print("[TEST] Indicators")
    prices = np.random.randn(100).cumsum() + 100

    rsi = Indicators.calculate_rsi(prices)
    print(f"  RSI (last): {rsi[-1]:.2f}")

    macd = Indicators.calculate_macd(prices)
    print(f"  MACD (last): {macd['macd'][-1]:.4f}")

    bb = Indicators.calculate_bollinger_bands(prices)
    print(f"  BB Upper (last): {bb['upper'][-1]:.2f}")
