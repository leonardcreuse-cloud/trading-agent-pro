#!/usr/bin/env python3
"""
Scoring Reliability - Measure data freshness and conflicts
"""

import sqlite3
from datetime import datetime, timedelta

from .common import db_path


class ScoringReliability:
    """Score based on data freshness and source agreement"""
    
    def __init__(self):
        self.db_path = db_path()
    
    def get_data_freshness(self, ticker, module):
        """Check how fresh the data is (0-100 score)"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            c.execute(f'SELECT timestamp FROM sec_data WHERE ticker=? LIMIT 1', (ticker,))
            row = c.fetchone()
            conn.close()
            
            if not row:
                return 50
            
            timestamp_str = row[0]
            data_time = datetime.fromisoformat(timestamp_str)
            age_hours = (datetime.now() - data_time).total_seconds() / 3600
            
            if age_hours < 24:
                return 95
            elif age_hours < 72:
                return 80
            elif age_hours < 168:
                return 60
            else:
                return 30
        except:
            return 50
    
    def check_data_conflicts(self, tech_signal, fund_signal, news_signal):
        """Detect if signals disagree"""
        signals = [tech_signal, fund_signal, news_signal]
        unique_signals = set(signals)
        
        if len(unique_signals) == 1:
            return 100
        elif len(unique_signals) == 2:
            return 70
        else:
            return 40
    
    def calculate_reliability_score(self, freshness, conflict, data_availability):
        """Weighted reliability score"""
        weights = {
            'freshness': 0.40,
            'conflict': 0.35,
            'availability': 0.25
        }
        
        score = (freshness * weights['freshness'] +
                conflict * weights['conflict'] +
                data_availability * weights['availability'])
        
        return round(score, 2)
    
    def analyze(self, ticker, tech_signal, fund_signal, news_signal):
        """Complete reliability analysis"""
        print(f"  [RELIABILITY] {ticker}...")
        
        freshness = self.get_data_freshness(ticker, 'sec')
        conflict = self.check_data_conflicts(tech_signal, fund_signal, news_signal)
        availability = 100
        
        reliability = self.calculate_reliability_score(freshness, conflict, availability)
        
        return {
            'ticker': ticker,
            'reliability_score': reliability,
            'components': {
                'freshness': freshness,
                'conflict_check': conflict,
                'availability': availability
            },
            'timestamp': datetime.now().isoformat(),
            'source': 'Data Quality Check',
            'confidence': 80
        }


if __name__ == "__main__":
    print("[TEST] ScoringReliability")
    rel = ScoringReliability()
    print("  Analyzing CRWD...")
    result = rel.analyze('CRWD', 'HOLD', 'BUY', 'HOLD')
    print(f"  ✓ Reliability Score: {result['reliability_score']}")
    print(f"  Components: {result['components']}")