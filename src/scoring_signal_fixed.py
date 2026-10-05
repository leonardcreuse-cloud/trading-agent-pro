#!/usr/bin/env python3
"""
Scoring Signal Fixed v2 - NOW: Signal Agreement (not prediction)
"""

from datetime import datetime


class ScoringSignalFixed:
    """Final recommendation - CORRECTED"""

    def __init__(self):
        pass

    def combine_scores(self, tech_score, fund_score, news_score):
        """Weighted combination"""
        weights = {
            'technical': 0.25,
            'fundamentals': 0.50,
            'news': 0.25
        }

        combined = (tech_score * weights['technical'] +
                   fund_score * weights['fundamentals'] +
                   news_score * weights['news'])

        return round(combined, 2)

    def generate_final_signal(self, combined_score):
        """Convert combined score to BUY/SELL/HOLD"""
        if combined_score >= 65:
            return 'BUY'
        elif combined_score <= 40:
            return 'SELL'
        else:
            return 'HOLD'

    def _calculate_signal_agreement(self, tech_score, fund_score, news_score, combined):
        """
        SIGNAL AGREEMENT (NOT prediction confidence!)
        
        Measures:
        1. How aligned are the 3 sources? (spread)
        2. How far from neutral (50) is the signal?
        
        This is a RELIABILITY metric, not a predictive probability.
        """
        scores = [tech_score, fund_score, news_score]
        score_mean = sum(scores) / len(scores)
        spread = max(scores) - min(scores)
        
        # Lower spread = higher agreement
        agreement_pct = max(0, 100 - spread)
        
        # Strength: distance from neutral
        strength = abs(combined - 50)
        strength_pct = min(100, (strength / 50) * 100)
        
        # 60% agreement + 40% strength
        signal_agreement = (agreement_pct * 0.60) + (strength_pct * 0.40)
        
        return round(max(0, min(100, signal_agreement)), 2)

    def analyze(self, ticker, tech_result, fund_result, news_result):
        """Complete signal analysis"""
        print(f"  [SIGNAL_FIXED] {ticker}...")

        tech_score = tech_result.get('technical_score', 50)
        fund_score = fund_result.get('fundamental_score', 50)
        news_score = news_result.get('news_score', 50)

        tech_signal = tech_result.get('signal', 'HOLD')
        fund_signal = fund_result.get('signal', 'HOLD')
        news_signal = news_result.get('signal', 'HOLD')

        combined = self.combine_scores(tech_score, fund_score, news_score)
        final_signal = self.generate_final_signal(combined)

        # Agreement = measure of source alignment (NOT prediction)
        signal_agreement = self._calculate_signal_agreement(tech_score, fund_score, news_score, combined)

        return {
            'ticker': ticker,
            'signal': final_signal,
            'combined_score': combined,
            'signal_agreement': signal_agreement,  # RENAMED from confidence
            'component_scores': {
                'technical': tech_score,
                'fundamentals': fund_score,
                'news': news_score
            },
            'component_signals': {
                'technical': tech_signal,
                'fundamentals': fund_signal,
                'news': news_signal
            },
            'recommendation': f"{final_signal} (Score: {combined}, Agreement: {signal_agreement}%)",
            'timestamp': datetime.now().isoformat(),
            'source': 'Multi-Source Fixed v2'
        }


if __name__ == "__main__":
    pass
