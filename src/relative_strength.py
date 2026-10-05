import yfinance as yf
from datetime import datetime, timedelta
import numpy as np

class RelativeStrength:
    """
    Analyse de force relative (Relative Strength Index vs secteur)
    - Compare performance ticker vs secteur (tech, software, etc)
    - Source: Yahoo Finance (Tier 2)
    """
    
    def __init__(self):
        self.sector_etfs = {
            'CRWD': 'XLK',
            'NET': 'XLK',
            'RKLB': 'XAR',
            'MP': 'XLE'
        }
    
    def get_relative_strength(self, ticker, period_days=90):
        """
        Calcule RS: % gain ticker vs % gain secteur sur N jours
        Retourne: {ticker, ticker_return, sector_return, relative_strength, signal}
        """
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=period_days)
            
            ticker_data = yf.download(ticker, start=start_date, end=end_date, progress=False)
            
            if ticker_data.empty:
                return {'error': f'No data for {ticker}', 'ticker': ticker}
            
            ticker_return = ((ticker_data['Close'].iloc[-1] / ticker_data['Close'].iloc[0]) - 1) * 100
            
            sector_etf = self.sector_etfs.get(ticker, 'XLK')
            sector_data = yf.download(sector_etf, start=start_date, end=end_date, progress=False)
            
            if sector_data.empty:
                sector_return = 0
            else:
                sector_return = ((sector_data['Close'].iloc[-1] / sector_data['Close'].iloc[0]) - 1) * 100
            
            relative_strength = ticker_return - sector_return
            
            if relative_strength > 5:
                signal = 'OUTPERFORMING'
            elif relative_strength < -5:
                signal = 'UNDERPERFORMING'
            else:
                signal = 'IN_LINE'
            
            return {
                'ticker': ticker,
                'ticker_return': round(ticker_return, 2),
                'sector_return': round(sector_return, 2),
                'relative_strength': round(relative_strength, 2),
                'signal': signal,
                'period_days': period_days,
                'source': 'Yahoo Finance',
                'source_tier': 2,
                'confidence': 0.88
            }
        
        except Exception as e:
            return {'error': str(e), 'ticker': ticker}
    
    def get_beta(self, ticker, market_index='^GSPC'):
        """
        Calcule Beta vs S&P 500
        Retourne: {ticker, beta, interpretation}
        """
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=365)
            
            ticker_data = yf.download(ticker, start=start_date, end=end_date, progress=False)
            market_data = yf.download(market_index, start=start_date, end=end_date, progress=False)
            
            ticker_returns = ticker_data['Close'].pct_change().dropna()
            market_returns = market_data['Close'].pct_change().dropna()
            
            covariance = np.cov(ticker_returns, market_returns)[0][1]
            market_variance = np.var(market_returns)
            
            beta = covariance / market_variance if market_variance != 0 else 0
            
            if beta > 1.2:
                interpretation = 'HIGH_VOLATILITY'
            elif beta > 0.8:
                interpretation = 'MARKET_CORRELATED'
            else:
                interpretation = 'LOW_VOLATILITY'
            
            return {
                'ticker': ticker,
                'beta': round(beta, 2),
                'interpretation': interpretation,
                'source': 'Yahoo Finance',
                'source_tier': 2,
                'confidence': 0.85
            }
        
        except Exception as e:
            return {'error': str(e), 'ticker': ticker}
    
    def get_momentum(self, ticker, period_days=252):
        """
        Calcule momentum annuel (252 jours)
        Retourne: {ticker, momentum, signal}
        """
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=period_days)
            
            data = yf.download(ticker, start=start_date, end=end_date, progress=False)
            
            if data.empty or len(data) < 2:
                return {'error': 'Insufficient data', 'ticker': ticker}
            
            momentum = ((data['Close'].iloc[-1] / data['Close'].iloc[0]) - 1) * 100
            
            if momentum > 20:
                signal = 'STRONG_UP'
            elif momentum > 5:
                signal = 'MODERATE_UP'
            elif momentum < -20:
                signal = 'STRONG_DOWN'
            elif momentum < -5:
                signal = 'MODERATE_DOWN'
            else:
                signal = 'SIDEWAYS'
            
            return {
                'ticker': ticker,
                'momentum': round(momentum, 2),
                'signal': signal,
                'period_days': period_days,
                'source': 'Yahoo Finance',
                'source_tier': 2,
                'confidence': 0.90
            }
        
        except Exception as e:
            return {'error': str(e), 'ticker': ticker}

if __name__ == "__main__":
    rs = RelativeStrength()
    
    for ticker in ['CRWD', 'NET', 'RKLB', 'MP']:
        print(f"\n{ticker} - Relative Strength:")
        
        rel_str = rs.get_relative_strength(ticker)
        print(f"  RS (90d): {rel_str.get('relative_strength', 'N/A')}% ({rel_str.get('signal', 'N/A')})")
        
        beta = rs.get_beta(ticker)
        print(f"  Beta: {beta.get('beta', 'N/A')} ({beta.get('interpretation', 'N/A')})")
        
        mom = rs.get_momentum(ticker)
        print(f"  Momentum (1y): {mom.get('momentum', 'N/A')}% ({mom.get('signal', 'N/A')})")
