from src.price_technical import PriceTechnical
import numpy as np

pt = PriceTechnical()
prices = pt.fetch_price_data('CRWD')
prices_valid = prices[-150:] if len(prices) >= 150 else prices

print(f'prices_valid shape: {prices_valid.shape}')
print(f'prices_valid type: {type(prices_valid)}')

rsi = pt.indicators.calculate_rsi(prices_valid)
print(f'rsi shape: {rsi.shape}')
print(f'rsi[-1] type: {type(rsi[-1])}')

try:
    rsi_val = float(rsi[-1])
    print(f'rsi_val: {rsi_val}')
except Exception as e:
    print(f'rsi_val ERROR: {e}')

macd = pt.indicators.calculate_macd(prices_valid)
print(f'macd histogram shape: {macd["histogram"].shape}')
try:
    macd_hist = float(macd['histogram'][-1])
    print(f'macd_hist: {macd_hist}')
except Exception as e:
    print(f'macd_hist ERROR: {e}')

bb = pt.indicators.calculate_bollinger_bands(prices_valid)
print(f'bb upper shape: {bb["upper"].shape}')
try:
    bb_upper = float(bb['upper'][-1])
    print(f'bb_upper: {bb_upper}')
except Exception as e:
    print(f'bb_upper ERROR: {e}')

price_last = float(prices_valid[-1])
print(f'price_last: {price_last}')
