#!/usr/bin/env python3
"""
Scoring Signal - Combine all signals (OPTIMISÉ: sans appels redondants)
"""

from .scoring_reliability import ScoringReliability
from .scoring_confidence import ScoringConfidence
from datetime import datetime


class ScoringSignal:
    """Combine all signals into final recommendation (v3: optimisé)"""
    
    def __init__(self):
        self.reliability = ScoringReliability()
        self.confidence = ScoringConfidence()
    
    def combine_scores(self, tech_score, fund_score, reliability_score, confidence_score):
        """Weighted combination"""
        weights = {
            'technical': 0.25,
            'fundamentals': 0.55,
            'reliability': 0.10,
            'confidence': 0.10
        }
        
        combined = (tech_score * weights['technical'] +
                   fund_score * weights['fundamentals'] +
                   reliability_score * weights['reliability'] +
                   confidence_score * weights['confidence'])
        
        return round(combined, 2)
    
    def generate_final_signal(self, combined_score):
        """Convert combined score to BUY/SELL/HOLD"""
        if combined_score >= 68:
            return 'BUY'
        elif combined_score <= 35:
            return 'SELL'
        else:
            return 'HOLD'
    
    def analyze(self, ticker, tech_result, fund_result, news_result):
        """Complete signal analysis (réutilise les résultats passés - PAS DE RECALCUL)"""
        print(f"  [SIGNAL] {ticker}...")
        
        # Extraire les scores des résultats DÉJÀ calculés
        tech_score = tech_result.get('technical_score', 50)
        fund_score = fund_result.get('fundamental_score', 50)
        
        tech_signal = tech_result.get('signal', 'HOLD')
        fund_signal = fund_result.get('signal', 'HOLD')
        news_signal = news_result.get('signal', 'HOLD')
        
        # Get reliability (basé sur les signaux existants)
        reliability_result = self.reliability.analyze(
            ticker,
            tech_signal,
            fund_signal,
            news_signal
        )
        reliability_score = reliability_result.get('reliability_score', 50)
        
        # Get confidence
        confidence_result = self.confidence.analyze(ticker, reliability_score)
        confidence_score = confidence_result.get('confidence_score', 50)
        
        # Combine all
        combined = self.combine_scores(tech_score, fund_score, reliability_score, confidence_score)
        final_signal = self.generate_final_signal(combined)
        
        # Calculate agreement
        signals = [tech_signal, fund_signal, news_signal]
        agreement = signals.count(final_signal)
        confidence_pct = (agreement / len(signals)) * 100
        
        return {
            'ticker': ticker,
            'signal': final_signal,
            'combined_score': combined,
            'confidence_pct': round(confidence_pct, 2),
            'component_scores': {
                'technical': tech_score,
                'fundamentals': fund_score,
                'reliability': reliability_score,
                'confidence': confidence_score
            },
            'component_signals': {
                'technical': tech_signal,
                'fundamentals': fund_signal,
                'news': news_signal
            },
            'recommendation': f"{final_signal} (Score: {combined})",
            'timestamp': datetime.now().isoformat(),
            'source': 'Multi-Source Real Data v3',
            'confidence': round(confidence_pct, 2)
        }


if __name__ == "__main__":
    print("[TEST] ScoringSignal - v3 (optimisé)")
