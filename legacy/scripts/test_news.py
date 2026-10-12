import requests
import os
from dotenv import load_dotenv

load_dotenv()
key = os.getenv('NEWSAPI_KEY')
print(f'Cle: {key[:20]}...')
url = f'https://newsapi.org/v2/everything?q=CRWD&apiKey={key}&pageSize=1'
r = requests.get(url, timeout=5)
print(f'Status: {r.status_code}')
data = r.json()
print(f'Articles trouves: {data.get("totalResults", 0)}')
