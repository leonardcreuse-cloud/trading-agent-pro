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

P1.6 changes:
- Fixed window: articles published in the last WINDOW_DAYS days only (the latest 100 articles
  covered 4 days for one company and 26 for another, so scores were not comparable).
- Coverage: returned / totalResults is reported; partial coverage is flagged (the free plan
  returns at most 100 results and cannot be paginated further).
- Articles without any lexicon word carry no sentiment; the score averages the others. No
  scored article -> news_score None (DATA UNAVAILABLE), never a neutral 50.
- Status PROVISIONAL: the lexicon method is naive and has never been validated.
"""

from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from .common import company_name, redact, secret_env, unavailable, utc_now_iso, DATA_UNAVAILABLE
from .database import Database
from .news_sentiment import NewsSentiment

load_dotenv()

NEWS_SOURCE = 'NewsAPI (aggregator)'
DB_SOURCE = 'NewsAPI'
WINDOW_DAYS = 7


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
            return {'articles': [], 'error': self.key_problem, 'query': query, 'fetch': None,
                    'total_results': None, 'window_start': None}

        window_start = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).strftime('%Y-%m-%dT%H:%M:%S')
        params = {'q': query, 'sortBy': 'publishedAt', 'language': 'en', 'pageSize': 100,
                  'from': window_start, 'apiKey': self.newsapi_key}
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
            return {'articles': [], 'error': error, 'query': query, 'fetch': fetch,
                    'total_results': None, 'window_start': None}

        articles = data.get('articles', [])
        total_results = data.get('totalResults')
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
        return {'articles': articles, 'error': None, 'query': query, 'fetch': fetch,
                'total_results': total_results, 'window_start': params['from'] + '+00:00'}

    def analyze_articles(self, articles):
        """Average lexicon sentiment over articles that contain a lexicon word."""
        sentiments = []
        for article in articles or []:
            text = f"{article.get('title') or ''} {article.get('description') or ''}"
            sentiments.append(self.sentiment.analyze_sentiment(text))
        scored = [s for s in sentiments if s is not None]
        return {
            'avg_sentiment': round(sum(scored) / len(scored), 2) if scored else None,
            'article_count': len(articles or []),
            'scored_article_count': len(scored),
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
        published = sorted(a['publishedAt'] for a in articles if a.get('publishedAt'))
        total = news_data.get('total_results')
        coverage = round(len(articles) / total, 3) if total else None
        if analysis['avg_sentiment'] is None:
            result = unavailable(NEWS_SOURCE, f'none of the {len(articles)} articles contains a lexicon '
                                              'word: no sentiment can be measured')
            result.update({'ticker': ticker, 'signal': None, 'news_score': None, 'avg_sentiment': None,
                           'articles_count': len(articles), 'scored_articles_count': 0,
                           'query': news_data['query'],
                           'provenance': self.db.provenance(news_data['fetch'], cadence='news')})
            return result
        signal, score = self.sentiment.score_sentiment(analysis['avg_sentiment'])
        partial = total is not None and len(articles) < total

        return {
            'ticker': ticker,
            'status': 'PROVISIONAL',
            'warning': ('Naive word-count lexicon, never validated; '
                        + (f'partial coverage: {len(articles)} of {total} articles in the window. '
                           if partial else '') + 'Aggregator source (rank 3).'),
            'signal': signal,
            'news_score': score,
            'avg_sentiment': analysis['avg_sentiment'],
            'articles_count': analysis['article_count'],
            'scored_articles_count': analysis['scored_article_count'],
            'total_results': total,
            'coverage': coverage,
            'partial_coverage': partial,
            'window_days': WINDOW_DAYS,
            'window_start': news_data.get('window_start'),
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
