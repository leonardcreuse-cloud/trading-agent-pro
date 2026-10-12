#!/usr/bin/env python3
"""
Scoring Confidence - Based on real backtest accuracy
"""

import sqlite3
from datetime import datetime

from .common import db_path


class ScoringConfidence:
    """Score confidence based on backtester accuracy"""
    
    def __init__(self):
        self.db_path = db_path()
    
    def get_backtest_accuracy(self, ticker):
        """Fetch real backtest accuracy from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            c.execute('''SELECT accuracy_5d FROM backtest_results 
                        WHERE ticker=? 
                        ORDER BY date DESC 
                        LIMIT 100''', (ticker,))
            
            results = c.fetchall()
            conn.close()
            
            if not results:
                return 50
            
            wins = sum(1 for r in results if r[0] == 1)
            accuracy = (wins / len(results)) * 100 if results else 50
            return accuracy
        except:
            return 50
    
    def accuracy_to_confidence(self, accuracy):
        """Convert accuracy % to confidence score (0-100)"""
        if accuracy >= 65:
            return 90
        elif accuracy >= 55:
            return 75
        elif accuracy >= 45:
            return 60
        elif accuracy >= 35:
            return 45
        else:
            return 30
    
    def calculate_composite_confidence(self, backtest_conf, data_quality):
        """Combine backtest confidence with data quality"""
        weights = {
            'backtest': 0.65,
            'data_quality': 0.35
        }
        
        confidence = (backtest_conf * weights['backtest'] +
                     data_quality * weights['data_quality'])
        
        return round(confidence, 2)
    
    def analyze(self, ticker, reliability_score):
        """Complete confidence analysis"""
        print(f"  [CONFIDENCE] {ticker}...")
        
        accuracy = self.get_backtest_accuracy(ticker)
        backtest_conf = self.accuracy_to_confidence(accuracy)
        
        composite = self.calculate_composite_confidence(backtest_conf, reliability_score)
        
        return {
            'ticker': ticker,
            'confidence_score': composite,
            'components': {
                'backtest_accuracy': round(accuracy, 2),
                'backtest_confidence': backtest_conf,
                'data_quality': reliability_score
            },
            'interpretation': 'HIGH' if composite >= 70 else ('MEDIUM' if composite >= 50 else 'LOW'),
            'timestamp': datetime.now().isoformat(),
            'source': 'Backtest + Data Quality'
        }


if __name__ == "__main__":
    print("[TEST] ScoringConfidence")
    conf = ScoringConfidence()
    print("  Analyzing CRWD...")
    result = conf.analyze('CRWD', 85)
    print(f"  ✓ Confidence Score: {result['confidence_score']} ({result['interpretation']})")
    print(f"  Accuracy: {result['components']['backtest_accuracy']}%")
