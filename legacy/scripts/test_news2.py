from dotenv import load_dotenv
load_dotenv()
from src.news_processor import NewsProcessor

np = NewsProcessor()
result = np.analyze('CRWD')
print(f'Articles: {result["articles_count"]}')
print(f'Signal: {result["signal"]}')
