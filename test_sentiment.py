from src.news_sentiment import NewsSentiment

ns = NewsSentiment()

# Test articles réels NewsAPI
articles = [
    "Crowdstrike surges on strong earnings beat",
    "Cloudflare plunges on guidance miss",
    "Rocket Lab advanced growth momentum",
    "MarineMax sales decline sharply"
]

for text in articles:
    sentiment = ns.analyze_sentiment(text)
    signal, score = ns.score_sentiment(sentiment)
    print(f'{text[:40]:<40} → Sentiment: {sentiment:.0f} Signal: {signal}')
