import json

# 1. Backtester sans biais - win rates reels
print("[1] BACKTESTER NO LEAK - Win rates reels:")
from src.backtester_no_bias import BacktesterNoLeak
bt = BacktesterNoLeak()
for ticker in ["CRWD", "NET", "RKLB", "MP"]:
    result = bt.run(ticker)
    if result:
        wr = result.get("win_rate", "N/A")
        acc = result.get("accuracy", "N/A")
        print(f"{ticker}: Win Rate {wr}%, Accuracy {acc}%")

# 2. Donnees reelles yfinance
print("\n[2] DONNEES TEMPORELLES DISPONIBLES:")
import yfinance as yf
from datetime import datetime, timedelta
end = datetime.now()
start = end - timedelta(days=730)
print(f"Periode: {start.date()} -> {end.date()} (730 jours)")
for ticker in ["CRWD", "NET", "RKLB", "MP"]:
    try:
        data = yf.download(ticker, start=start, end=end, progress=False)
        if not data.empty:
            print(f"{ticker}: {len(data)} jours reels")
    except Exception as e:
        print(f"{ticker}: Erreur - {e}")
