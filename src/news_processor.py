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

P0.2 changes (provenance):
- Every NewsAPI call is logged in source_fetches with its raw JSON in data/raw/
  (the API key is a request parameter and is never stored).
- Each article is stored as an observation (metric 'news_article', value_text = URL)
  with published_at = the article's publishedAt.
- A placeholder key such as "<key>" is rejected before any call.
"""

import requests
from dotenv import load_dotenv

from .common import company_name, redact, secret_env, unavailable, utc_now_iso, DATA_UNAVAILABLE
from .database import Database
from .news_sentiment import NewsSentiment

load_dotenv()

NEWS_SOURCE = 'NewsAPI (aggregator)'
DB_SOURCE = 'NewsAPI'


class NewsProcessor:
    """Analyze news sentiment for stocks"""

    URL = "https://newsapi.org/v2/everything"

    def __init__(self, db=None):
        self.db = db or Database()
        self.sentiment = NewsSentiment()
        self.newsapi_key, self.key_problem = secret_env('NEWSAPI_KEY')

    def fetch_news(self, ticker):
        """
        Fetch recent articles.
        Returns {'articles': [...], 'error': str|None, 'query': str, 'fetch': dict|None}.
        """
        query = f'"{company_name(ticker)}"'
        if self.key_problem:
            return {'articles': [], 'error': self.key_problem, 'query': query, 'fetch': None}

        params = {'q': query, 'sortBy': 'publishedAt', 'language': 'en', 'pageSize': 100,
                  'apiKey': self.newsapi_key}
        requested_at = utc_now_iso()
        response = None
        try:
            response = requests.get(self.URL, params=params, timeout=10)
            if response.status_code != 200:
                error = f'NewsAPI HTTP {response.status_code}'
                try:
                    detail = response.json().get('code')
                    error += f' ({detail})' if detail else ''
                except (ValueError, AttributeError):
                    pass
            else:
                data = response.json()
                error = None
        except Exception as e:  # noqa: BLE001 - recorded and surfaced
            error = redact(f"{type(e).__name__}: {e}")

        if error:
            fetch = self.db.record_fetch(DB_SOURCE, self.URL, params=params,
                                         requested_at=requested_at, status=DATA_UNAVAILABLE,
                                         error=error,
                                         http_status=getattr(response, 'status_code', None))
            return {'articles': [], 'error': error, 'query': query, 'fetch': fetch}

        articles = data.get('articles', [])
        raw = getattr(response, 'content', None)
        fetch = self.db.record_fetch(DB_SOURCE, self.URL, params=params,
                                     requested_at=requested_at, status='OK',
                                     http_status=response.status_code, n_records=len(articles),
                                     raw=raw if isinstance(raw, (bytes, str)) else data)
        self.db.upsert_observations(fetch, [{
            'entity': ticker, 'metric': 'news_article', 'as_of_date': a['publishedAt'][:10],
            'value_text': a.get('url') or a.get('title') or '(untitled)',
            'published_at': a['publishedAt'], 'published_at_basis': 'NewsAPI publishedAt'}
            for a in articles if a.get('publishedAt')])
        return {'articles': articles, 'error': None, 'query': query, 'fetch': fetch}

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
                           'query': news_data['query'],
                           'provenance': self.db.provenance(news_data['fetch'], cadence='news')
                           if news_data['fetch'] else None})
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
            'provenance': self.db.provenance(
                news_data['fetch'], cadence='news',
                as_of_date=published[-1][:10] if published else None,
                published_at=published[-1] if published else None,
                published_at_basis='NewsAPI publishedAt of the newest article'),
            'timestamp': utc_now_iso(),
            'source': NEWS_SOURCE,
        }


if __name__ == "__main__":
    from .common import tickers
    processor = NewsProcessor()
    for t in tickers():
        r = processor.analyze(t)
        print(f"  {t}: {r.get('status')} {r.get('signal')} ({r.get('articles_count')} articles)")
