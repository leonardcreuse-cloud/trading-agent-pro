from src.price_technical import PriceTechnical
import traceback

pt = PriceTechnical()
ticker = 'CRWD'

prices = pt.fetch_price_data(ticker)
print(f'Prices shape: {prices.shape if hasattr(prices, "shape") else type(prices)}')

prices_valid = prices[-150:] if len(prices) >= 150 else prices
print(f'Prices valid shape: {prices_valid.shape if hasattr(prices_valid, "shape") else len(prices_valid)}')

try:
    rsi = pt.indicators.calculate_rsi(prices_valid)
    print(f'RSI OK: {rsi[-1]}')
    macd = pt.indicators.calculate_macd(prices_valid)
    print(f'MACD OK: {macd["histogram"][-1]}')
    bb = pt.indicators.calculate_bollinger_bands(prices_valid)
    print(f'BB OK: {bb["upper"][-1]}')
except Exception as e:
    print(f'ERROR: {e}')
    traceback.print_exc()
