from src.news_processor import NewsProcessor
from src.news_sentiment import NewsSentiment

np = NewsProcessor()

# 1. Fetch articles
news_data = np.fetch_news('CRWD')
articles = news_data['articles']
print(f'[1] Articles fetched: {len(articles)}')

# 2. Analyze sentiment
analysis = np.analyze_articles(articles)
print(f'[2] Sentiment analysis:')
print(f'    avg_sentiment: {analysis["avg_sentiment"]}')
print(f'    sentiments[:10]: {analysis["sentiments"][:10]}')

# 3. Score sentiment
sentiment = NewsSentiment()
signal, score = sentiment.score_sentiment(analysis['avg_sentiment'])
print(f'[3] Score sentiment:')
print(f'    signal: {signal}')
print(f'    score: {score}')

# Show raw articles
print(f'\n[RAW] First 3 articles:')
for i, article in enumerate(articles[:3]):
    print(f'{i+1}. {article.get("title", "N/A")[:80]}...')
