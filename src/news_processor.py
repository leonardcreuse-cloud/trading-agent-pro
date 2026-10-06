#!/usr/bin/env python3
"""
News Processor - Fetch and analyze news sentiment (NewsAPI aggregator)

P0.1 changes:
- No key / API error / zero articles -> news_score=None with status DATA UNAVAILABLE
  (previously a neutral 50 / HOLD was produced from no data at all).
- Query uses the company name from config (e.g. "Cloudflare") instead of ambiguous
  tickers such as "NET" or "MP".
- publishedAt range of the analysed articles is reported for traceability.
- NewsAPI is an aggregator: it is never sufficient proof of an event on its own.
  Deduplication, source validation and event classification come in phase P2.2.
"""

import os

import requests
from dotenv import load_dotenv

from .common import company_name, unavailable, utc_now_iso
from .news_sentiment import NewsSentiment

load_dotenv()

NEWS_SOURCE = 'NewsAPI (aggregator)'


class NewsProcessor:
    """Analyze news sentiment for stocks"""

    URL = "https://newsapi.org/v2/everything"

    def __init__(self):
        self.sentiment = NewsSentiment()
        self.newsapi_key = os.getenv('NEWSAPI_KEY', '').strip()

    def fetch_news(self, ticker):
        """
        Fetch recent articles. Returns {'articles': [...], 'error': str|None, 'query': str}.
        """
        query = f'"{company_name(ticker)}"'
        if not self.newsapi_key or self.newsapi_key == 'demo':
            return {'articles': [], 'error': 'NEWSAPI_KEY not set', 'query': query}

        try:
            response = requests.get(
                self.URL,
                params={'q': query, 'sortBy': 'publishedAt', 'language': 'en',
                        'pageSize': 100, 'apiKey': self.newsapi_key},
                timeout=10)
            if response.status_code != 200:
                return {'articles': [], 'error': f'NewsAPI HTTP {response.status_code}',
                        'query': query}
            data = response.json()
            return {'articles': data.get('articles', []), 'error': None, 'query': query}
        except Exception as e:
            return {'articles': [], 'error': f"{type(e).__name__}: {e}", 'query': query}

    def analyze_articles(self, articles):
        """Average lexicon sentiment over articles (None if no articles)."""
        if not articles:
            return {'avg_sentiment': None, 'article_count': 0, 'sentiments': []}

        sentiments = []
        for article in articles:
            text = f"{article.get('title') or ''} {article.get('description') or ''}"
            sentiments.append(self.sentiment.analyze_sentiment(text))

        return {
            'avg_sentiment': round(sum(sentiments) / len(sentiments), 2),
            'article_count': len(articles),
            'sentiments': sentiments,
        }

    def analyze(self, ticker):
        print(f"  [NEWS] {ticker}...")

        news_data = self.fetch_news(ticker)
        articles = news_data['articles']

        if not articles:
            reason = news_data['error'] or 'no articles returned'
            result = unavailable(NEWS_SOURCE, reason)
            result.update({'ticker': ticker, 'signal': None, 'news_score': None,
                           'avg_sentiment': None, 'articles_count': 0,
                           'query': news_data['query']})
            return result

        analysis = self.analyze_articles(articles)
        signal, score = self.sentiment.score_sentiment(analysis['avg_sentiment'])
        published = sorted(a['publishedAt'] for a in articles if a.get('publishedAt'))

        return {
            'ticker': ticker,
            'status': 'OK',
            'signal': signal,
            'news_score': score,
            'avg_sentiment': analysis['avg_sentiment'],
            'articles_count': analysis['article_count'],
            'query': news_data['query'],
            'oldest_article_published_at': published[0] if published else None,
            'newest_article_published_at': published[-1] if published else None,
            'method': 'word-level lexicon count (naive, not deduplicated); replaced in P2.2',
            'score_type': 'heuristic 0-100 score, not a probability',
            'timestamp': utc_now_iso(),
            'source': NEWS_SOURCE,
        }


if __name__ == "__main__":
    from .common import tickers
    processor = NewsProcessor()
    for t in tickers():
        r = processor.analyze(t)
        print(f"  {t}: {r.get('status')} {r.get('signal')} ({r.get('articles_count')} articles)")
