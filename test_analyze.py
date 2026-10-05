from src.price_technical import PriceTechnical
import traceback

pt = PriceTechnical()
try:
    result = pt.analyze('CRWD')
    print(f'Signal: {result["signal"]}')
    print(f'Score: {result["technical_score"]}')
    print(f'Components: {result["components"]}')
except Exception as e:
    print(f'ERROR: {e}')
    traceback.print_exc()
