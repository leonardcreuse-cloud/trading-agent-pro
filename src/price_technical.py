#!/usr/bin/env python3
"""
Price Technical - Real technical analysis with RSI, MACD, Bollinger Bands
"""

import yfinance as yf
from datetime import datetime, timedelta
from .indicators import Indicators
import numpy as np
import warnings
warnings.filterwarnings('ignore')


class PriceTechnical:
    """Real technical analysis using professional indicators"""

    def __init__(self):
        self.indicators = Indicators()

    def fetch_price_data(self, ticker):
        """Fetch 6 months price data"""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=180)
            data = yf.download(ticker, start=start_date, end=end_date, progress=False)

            if data.empty or len(data) < 70:
                return None

            return data['Close'].values
        except:
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

        prices = self.fetch_price_data(ticker)

        if prices is None or len(prices) < 70:
            return {
                'ticker': ticker,
                'signal': 'HOLD',
                'technical_score': 50,
                'components': {},
                'timestamp': datetime.now().isoformat(),
                'confidence': 40
            }

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
                return {
                    'ticker': ticker,
                    'signal': 'HOLD',
                    'technical_score': 50,
                    'components': {},
                    'timestamp': datetime.now().isoformat(),
                    'confidence': 40
                }

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
                'timestamp': datetime.now().isoformat(),
                'source': 'Real Technical Indicators (RSI, MACD, BB)',
                'confidence': 85
            }
        except Exception as e:
            return {
                'ticker': ticker,
                'signal': 'HOLD',
                'technical_score': 50,
                'components': {},
                'timestamp': datetime.now().isoformat(),
                'confidence': 40
            }


if __name__ == "__main__":
    print("[TEST] PriceTechnical")
    pt = PriceTechnical()
    for ticker in ['CRWD', 'NET']:
        result = pt.analyze(ticker)
        print(f"  ✓ {ticker}: {result['signal']} (Score: {result['technical_score']})")
