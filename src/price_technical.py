#!/usr/bin/env python3
"""
Price Technical - Technical analysis with RSI, MACD, Bollinger Bands

P0.1: when prices cannot be obtained or indicators are NaN, the module returns
technical_score=None / signal=None with status DATA UNAVAILABLE instead of a
fabricated neutral score (50 / HOLD). Hardcoded 'confidence' constants removed.
Scores are heuristic (not calibrated); continuous features come in phase P1.3.

P0.2: prices come from the shared provenance-aware PriceFeed (one download per run,
logged and stored); the output carries a `provenance` block (fetch id, retrieval time,
last session, freshness).
"""

from datetime import datetime, timedelta
from .indicators import Indicators
from .common import unavailable, utc_now_iso
from .market_data import PriceFeed
import numpy as np
import warnings
warnings.filterwarnings('ignore')


class PriceTechnical:
    """Real technical analysis using professional indicators"""

    LOOKBACK_DAYS = 180

    def __init__(self, price_feed=None):
        self.indicators = Indicators()
        self.price_feed = price_feed
        self.last_error = None
        self.last_price_date = None
        self.last_provenance = None

    def _unavailable(self, ticker, reason):
        result = unavailable('yfinance', reason)
        result.update({'ticker': ticker, 'signal': None, 'technical_score': None,
                       'components': {}, 'provenance': self.last_provenance})
        return result

    def fetch_price_data(self, ticker):
        """Last 6 months of completed daily closes from the shared price feed."""
        try:
            if self.price_feed is None:
                self.price_feed = PriceFeed()
            prices = self.price_feed.get(ticker)
            self.last_provenance = prices['provenance']
            if prices['status'] != 'OK':
                self.last_error = prices['reason'] or 'yfinance returned no data'
                return None
            cutoff = datetime.now() - timedelta(days=self.LOOKBACK_DAYS)
            close = prices['close'][prices['close'].index >= cutoff]
            if len(close) < 70:
                self.last_error = f'only {len(close)} price observations (70 required)'
                return None
            self.last_price_date = str(close.index[-1].date())
            return close.values
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            return None

    def score_rsi(self, rsi_value):
        """Score based on RSI (oversold < 30, overbought > 70)"""
        rsi_val = float(rsi_value)
        if rsi_val < 30:
            return 80, 'BUY'
        elif rsi_val > 70:
            return 20, 'SELL'
        elif rsi_val < 50:
            return 40, 'HOLD'
        else:
            return 60, 'HOLD'

    def score_macd(self, histogram):
        """Score based on MACD histogram (bullish if > 0)"""
        hist_val = float(histogram)
        if hist_val > 0:
            return 65, 'BUY'
        elif hist_val < 0:
            return 35, 'SELL'
        else:
            return 50, 'HOLD'

    def score_bollinger_bands(self, price, upper, middle, lower):
        """Score based on price position in Bollinger Bands"""
        price_val = float(price)
        upper_val = float(upper)
        middle_val = float(middle)
        lower_val = float(lower)

        if price_val > upper_val:
            return 25, 'SELL'
        elif price_val < lower_val:
            return 75, 'BUY'
        elif price_val > middle_val:
            return 60, 'HOLD'
        else:
            return 40, 'HOLD'

    def analyze(self, ticker):
        """Complete technical analysis"""
        print(f"  [TECHNICAL] {ticker}...")

        self.last_error = None
        self.last_price_date = None
        self.last_provenance = None
        prices = self.fetch_price_data(ticker)

        if prices is None or len(prices) < 70:
            return self._unavailable(ticker, self.last_error or 'insufficient price data')

        try:
            # Use 150 days (enough for Bollinger Bands + MACD + RSI)
            prices_valid = prices[-150:] if len(prices) >= 150 else prices
            prices_valid = np.array(prices_valid, dtype=float).flatten()

            # Calculate indicators
            rsi = self.indicators.calculate_rsi(prices_valid)
            macd = self.indicators.calculate_macd(prices_valid)
            bb = self.indicators.calculate_bollinger_bands(prices_valid)

            # Get latest values
            rsi_val = float(rsi[-1])
            macd_hist = float(macd['histogram'][-1])
            price_last = float(prices_valid[-1])
            bb_upper = float(bb['upper'][-1])
            bb_middle = float(bb['middle'][-1])
            bb_lower = float(bb['lower'][-1])

            # Check NaN
            if np.isnan(rsi_val) or np.isnan(macd_hist) or np.isnan(bb_upper):
                return self._unavailable(ticker, 'indicator computation returned NaN')

            # Score each indicator
            rsi_score, rsi_signal = self.score_rsi(rsi_val)
            macd_score, macd_signal = self.score_macd(macd_hist)
            bb_score, bb_signal = self.score_bollinger_bands(price_last, bb_upper, bb_middle, bb_lower)

            # Combined technical score (weighted average)
            technical_score = round((rsi_score * 0.4 + macd_score * 0.35 + bb_score * 0.25), 2)

            # Final signal
            if technical_score >= 65:
                final_signal = 'BUY'
            elif technical_score <= 35:
                final_signal = 'SELL'
            else:
                final_signal = 'HOLD'

            return {
                'ticker': ticker,
                'signal': final_signal,
                'technical_score': technical_score,
                'components': {
                    'rsi': {'value': round(rsi_val, 2), 'signal': rsi_signal, 'score': rsi_score},
                    'macd': {'histogram': round(macd_hist, 4), 'signal': macd_signal, 'score': macd_score},
                    'bollinger': {'price': round(price_last, 2), 'signal': bb_signal, 'score': bb_score}
                },
                'status': 'OK',
                'last_price_date': self.last_price_date,
                'score_type': 'heuristic 0-100 score, not a probability',
                'provenance': self.last_provenance,
                'timestamp': utc_now_iso(),
                'source': 'yfinance prices; RSI/MACD/Bollinger computed locally'
            }
        except Exception as e:  # noqa: BLE001 - reported, not hidden
            return self._unavailable(ticker, f'indicator computation failed: {type(e).__name__}: {e}')


if __name__ == "__main__":
    print("[TEST] PriceTechnical")
    pt = PriceTechnical()
    for ticker in ['CRWD', 'NET']:
        result = pt.analyze(ticker)
        print(f"  ✓ {ticker}: {result['signal']} (Score: {result['technical_score']})")
