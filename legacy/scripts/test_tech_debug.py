from src.price_technical import PriceTechnical
import traceback

pt = PriceTechnical()
ticker = 'CRWD'
print(f'Testing {ticker}...')

# Test fetch
prices = pt.fetch_price_data(ticker)
print(f'Prices fetched: {len(prices) if prices is not None else None}')

if prices is not None:
    prices_valid = prices[-150:] if len(prices) >= 150 else prices
    print(f'Prices valid: {len(prices_valid)}')
    
    try:
        rsi = pt.indicators.calculate_rsi(prices_valid)
        print(f'RSI: {rsi[-1] if rsi is not None else None}')
    except Exception as e:
        print(f'RSI ERROR: {e}')
        traceback.print_exc()
