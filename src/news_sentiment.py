#!/usr/bin/env python3
"""
News Sentiment - Analyze sentiment from news articles

P0.1: words are matched as whole tokens. Substring matching made 'up' match
'update'/'supply'/'group' and 'cut' match 'executive', biasing the score.
'earnings' and 'revenue' were removed from the positive list (neutral topic words),
and 'risk' from the negative list (boilerplate). Still a naive lexicon (phase P2.2).

P1.6: a text with no lexicon word has NO sentiment (None), not a neutral 50: on real
NewsAPI payloads 56-86 % of articles matched no word and pulled every average to ~50.
"""

import re

TOKEN_RE = re.compile(r"[a-z]+")

class NewsSentiment:
    """Simple sentiment analysis for news"""

    @staticmethod
    def analyze_sentiment(text):
        """Lexicon sentiment of a text (0-100), or None when no lexicon word occurs."""
        if not text:
            return None

        tokens = set(TOKEN_RE.findall(text.lower()))

        positive_words = [
            'bullish', 'surge', 'rally', 'gain', 'growth', 'beat', 'strong',
            'upgrade', 'buy', 'outperform', 'jump', 'record', 'soar', 'profit',
            'success', 'innovation', 'leadership', 'positive',
            'top', 'leader', 'advance', 'up', 'bull', 'rising', 'momentum', 'confidence',
            'optimistic', 'bullish', 'exceeded', 'outperform', 'buy', 'achieve', 'break',
            'high', 'increases', 'improved', 'better', 'boost', 'positive'
        ]

        negative_words = [
            'bearish', 'plunge', 'crash', 'fall', 'decline', 'miss', 'weak',
            'downgrade', 'sell', 'underperform', 'drop', 'loss', 'warning',
            'scandal', 'lawsuit', 'concern', 'failed', 'negative',
            'down', 'bear', 'falling', 'bearish', 'missed', 'slump', 'tumble',
            'pessimistic', 'worst', 'worse', 'challenge', 'difficult', 'loss',
            'losses', 'bad', 'poor', 'struggle', 'cut', 'reduced'
        ]

        positive_count = len(tokens & set(positive_words))
        negative_count = len(tokens & set(negative_words))

        if positive_count == 0 and negative_count == 0:
            return None

        score = 50 + (positive_count - negative_count) * 3
        return max(0, min(100, score))

    @staticmethod
    def score_sentiment(sentiment_value):
        """Convert sentiment to trading signal - LINEAR (not step-wise)"""
        # FIXED: Use sentiment_value directly instead of ignoring it with HOLD/50
        # Score ranges: 0-100 maps to 0-100 (not quantized to 25/50/75)
        
        if sentiment_value >= 65:
            signal = 'POSITIVE'
        elif sentiment_value <= 40:
            signal = 'NEGATIVE'
        else:
            signal = 'NEUTRAL'
        
        # FIXED: Score reflects actual sentiment, not default 50
        # Linear mapping: sentiment 0-100 -> score 0-100
        score = round(sentiment_value, 2)
        
        return signal, score


if __name__ == "__main__":
    print("[TEST] NewsSentiment")
    test_text = "Stock surges on bullish earnings beat and strong growth outlook"
    sentiment = NewsSentiment.analyze_sentiment(test_text)
    signal, score = NewsSentiment.score_sentiment(sentiment)
    print(f"  Text: {test_text}")
    print(f"  Sentiment: {sentiment:.0f}/100")
    print(f"  Signal: {signal} (Score: {score})")
