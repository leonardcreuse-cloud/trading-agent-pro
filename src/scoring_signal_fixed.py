#!/usr/bin/env python3
"""
Scoring Signal Fixed v3 - combined heuristic score with explicit data coverage

P0.1 changes:
- Missing component scores are no longer replaced by 50. The combined score is a
  weighted average over the AVAILABLE components only (weights renormalized).
- A combined signal requires at least MIN_COMPONENTS available components;
  otherwise the signal is 'INSUFFICIENT DATA'.
- The output states its coverage (e.g. "2/3") and that the score is a heuristic,
  not a probability. Weights and thresholds are NOT empirically validated yet
  (phase P1 replaces them with trained, calibrated models).
"""

from .common import utc_now_iso

INSUFFICIENT_DATA = 'INSUFFICIENT DATA'


class ScoringSignalFixed:
    """Final heuristic recommendation from technical / fundamental / news scores."""

    WEIGHTS = {'technical': 0.25, 'fundamentals': 0.50, 'news': 0.25}
    MIN_COMPONENTS = 2
    BUY_THRESHOLD = 65
    SELL_THRESHOLD = 40

    def combine_scores(self, scores):
        """Weighted average over available scores (dict name -> score or None)."""
        available = {k: v for k, v in scores.items() if v is not None}
        if not available:
            return None
        total_weight = sum(self.WEIGHTS[k] for k in available)
        combined = sum(v * self.WEIGHTS[k] for k, v in available.items()) / total_weight
        return round(combined, 2)

    def generate_final_signal(self, combined_score):
        if combined_score is None:
            return INSUFFICIENT_DATA
        if combined_score >= self.BUY_THRESHOLD:
            return 'BUY'
        if combined_score <= self.SELL_THRESHOLD:
            return 'SELL'
        return 'HOLD'

    @staticmethod
    def _calculate_signal_agreement(available_scores, combined):
        """
        Agreement between available sources (0-100): 60% low dispersion + 40% distance
        from neutral. A descriptive metric, NOT a prediction confidence or probability.
        """
        if combined is None or len(available_scores) < 2:
            return None
        spread = max(available_scores) - min(available_scores)
        agreement_pct = max(0, 100 - spread)
        strength_pct = min(100, abs(combined - 50) / 50 * 100)
        return round(max(0, min(100, agreement_pct * 0.60 + strength_pct * 0.40)), 2)

    def analyze(self, ticker, tech_result, fund_result, news_result):
        print(f"  [SIGNAL] {ticker}...")

        scores = {
            'technical': tech_result.get('technical_score'),
            'fundamentals': fund_result.get('fundamental_score'),
            'news': news_result.get('news_score'),
        }
        signals = {
            'technical': tech_result.get('signal'),
            'fundamentals': fund_result.get('signal'),
            'news': news_result.get('signal'),
        }
        available = [k for k, v in scores.items() if v is not None]
        missing = [k for k in scores if k not in available]

        if len(available) >= self.MIN_COMPONENTS:
            combined = self.combine_scores(scores)
        else:
            combined = None
        final_signal = self.generate_final_signal(combined)
        agreement = self._calculate_signal_agreement([scores[k] for k in available], combined)

        if combined is None:
            recommendation = (f"{INSUFFICIENT_DATA} ({len(available)}/{len(scores)} sources available; "
                              f"missing: {', '.join(missing)})")
        else:
            recommendation = (f"{final_signal} (heuristic score {combined}, coverage "
                              f"{len(available)}/{len(scores)}"
                              + (f", missing: {', '.join(missing)}" if missing else '') + ")")

        return {
            'ticker': ticker,
            'signal': final_signal,
            'combined_score': combined,
            'signal_agreement': agreement,
            'coverage': f"{len(available)}/{len(scores)}",
            'available_components': available,
            'missing_components': missing,
            'component_scores': scores,
            'component_signals': signals,
            'score_type': 'heuristic 0-100 score, not a probability; weights not validated',
            'recommendation': recommendation,
            'timestamp': utc_now_iso(),
            'source': 'Multi-Source heuristic v3',
        }


if __name__ == "__main__":
    pass
