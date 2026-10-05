from src.price_technical import PriceTechnical

pt = PriceTechnical()
for ticker in ['CRWD', 'NET', 'RKLB', 'MP']:
    result = pt.analyze(ticker)
    print(f'{ticker}: Signal={result["signal"]}, Score={result["technical_score"]}, Components={result["components"]}')
