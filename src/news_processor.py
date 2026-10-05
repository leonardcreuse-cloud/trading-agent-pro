#!/usr/bin/env python3
"""
News Processor - Fetch and analyze news sentiment
"""

import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from .news_sentiment import NewsSentiment

load_dotenv()


class NewsProcessor:
    """Analyze news sentiment for stocks"""

    def __init__(self):
        self.sentiment = NewsSentiment()
        self.newsapi_key = os.getenv('NEWSAPI_KEY', 'demo')

    def fetch_news(self, ticker):
        """Fetch recent news from NewsAPI"""
        if self.newsapi_key == 'demo':
            return {
                'articles': [],
                'totalResults': 0
            }

        try:
            url = f"https://newsapi.org/v2/everything?q={ticker}&sortBy=publishedAt&language=en&apiKey={self.newsapi_key}"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                return {
                    'articles': data.get('articles', []),
                    'totalResults': data.get('totalResults', 0)
                }
            else:
                print(f"  Warning NewsAPI error {response.status_code}")
                return {
                    'articles': [],
                    'totalResults': 0
                }
        except Exception as e:
            print(f"  Warning NewsAPI fetch failed: {e}")
            return {
                'articles': [],
                'totalResults': 0
            }

    def analyze_articles(self, articles):
        """Analyze sentiment from articles"""
        if not articles:
            return {
                'avg_sentiment': 50,
                'article_count': 0,
                'sentiments': []
            }

        sentiments = []
        for article in articles:
            title = article.get('title', '')
            description = article.get('description', '')
            text = f"{title} {description}"

            sentiment = self.sentiment.analyze_sentiment(text)
            sentiments.append(sentiment)

        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 50

        return {
            'avg_sentiment': round(avg_sentiment, 2),
            'article_count': len(articles),
            'sentiments': sentiments
        }

    def analyze(self, ticker):
        """Complete news analysis"""
        print(f"  [NEWS] {ticker}...")

        news_data = self.fetch_news(ticker)
        articles = news_data.get('articles', [])

        analysis = self.analyze_articles(articles)
        avg_sentiment = analysis['avg_sentiment']

        signal, score = self.sentiment.score_sentiment(avg_sentiment)

        return {
            'ticker': ticker,
            'signal': signal,
            'news_score': score,
            'avg_sentiment': avg_sentiment,
            'articles_count': analysis['article_count'],
            'timestamp': datetime.now().isoformat(),
            'source': 'NewsAPI (Sentiment Analysis)',
            'confidence': 70 if articles else 40
        }


if __name__ == "__main__":
    print("[TEST] NewsProcessor")
    np = NewsProcessor()
    for ticker in ['CRWD', 'NET']:
        result = np.analyze(ticker)
        print(f"  OK {ticker}: {result['signal']}")
