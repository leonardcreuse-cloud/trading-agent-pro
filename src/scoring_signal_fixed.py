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

P0.3: insider activity (SEC Form 4 open-market transactions) is a fourth component.

P1.4 relabel: the output is a QUANTITATIVE SIGNAL, not a trade recommendation.
- Labels POSITIVE / NEUTRAL / NEGATIVE describe the direction of the heuristic score
  (formerly BUY / HOLD / SELL). Keys: quantitative_signal, signal_strength, signal_summary.
- validation_status() states whether the walk-forward validation has demonstrated
  statistically significant out-of-sample predictive power (multiple-testing aware).
- No score is converted into a probability: model prediction, prediction confidence and
  risk score are reported as NOT IMPLEMENTED with their reason.
"""

import math

from .common import NOT_IMPLEMENTED, to_utc_iso, utc_now_iso

INSUFFICIENT_DATA = 'INSUFFICIENT DATA'


NOT_A_RECOMMENDATION = ('Quantitative signal derived from heuristic scores. It is not a trade '
                        'recommendation and not a probability.')
VALIDATION_ALPHA = 0.05
VALIDATION_COMPONENT = 'combined'


def two_sided_p(t_stat):
    """Two-sided p-value of a t statistic (normal approximation; large samples)."""
    return math.erfc(abs(t_stat) / math.sqrt(2))


def research_summary(stage, path=None, as_of=None):
    """
    One-line summary of a research stage from its results file (None if not run, or if it was
    computed after `as_of`: a later result was not known at that instant).
    """
    import json
    from .common import reports_dir
    path = path or reports_dir() / f'research_stage{stage}.json'
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    if as_of is not None and (data.get('computed_at') or '') > to_utc_iso(as_of):
        return None
    tests = data.get('feature_tests', []) + data.get('group_tests', []) + data.get('model_tests', [])
    conf = data.get('confirmatory') or []
    return {'stage': stage, 'computed_at': data.get('computed_at'),
            'n_stocks': (data.get('universe') or {}).get('n_stocks_with_data'),
            'n_tests': len(tests),
            'n_significant_bh': sum(bool(t.get('significant_bh')) for t in tests),
            'n_significant_bonferroni': sum(bool(t.get('significant_bonferroni')) for t in tests),
            'confirmatory': [{'id': c['id'], 'confirmed': c['confirmed'], 'p_holm': c.get('p_holm')}
                             for c in conf]}


def _research_sentence(research):
    parts = []
    for r in research or []:
        if r is None:
            continue
        line = (f"research stage {r['stage']} ({r['n_stocks']} stocks, {r['computed_at']}): "
                f"{r['n_significant_bh']} of {r['n_tests']} pre-registered factor and model tests "
                f"significant after Benjamini-Hochberg, {r['n_significant_bonferroni']} after Bonferroni")
        if r['confirmatory']:
            confirmed = [c['id'] for c in r['confirmatory'] if c['confirmed']]
            line += (f"; confirmatory family: {len(confirmed)} of {len(r['confirmatory'])} confirmed"
                     + (f" ({', '.join(confirmed)})" if confirmed else ''))
        parts.append(line)
    return ('; '.join(parts) + '.') if parts else ''


def _sentence(text):
    """Capitalised sentence ending with a full stop ('' for empty text)."""
    text = (text or '').strip()
    if not text:
        return ''
    text = text[0].upper() + text[1:]
    return text if text.endswith('.') else text + '.'


def validation_status(walk_forward, research=None):
    """
    Has the combined signal demonstrated out-of-sample predictive power?
    Criterion: cross-sectional IC of the combined score significant at VALIDATION_ALPHA after
    Bonferroni correction over the horizons tested, in a walk-forward run that is not stale.
    """
    wf = walk_forward or {}
    research_text = _research_sentence(research)
    news_note = ('The live signal includes a news component (weight 0.20) that has never been '
                 'validated (no news history). ')
    if wf.get('status') != 'OK' or not wf.get('horizons'):
        return {'status': 'NOT VALIDATED', 'demonstrated': False,
                'statement': ('No walk-forward validation is available: this signal has NOT '
                              'demonstrated any predictive power. ' + news_note
                              + _sentence(wf.get('reason')) + (' Separately: ' + research_text
                                                               if research_text else ''))}
    horizons = wf['horizons']
    k = len(horizons)
    threshold = VALIDATION_ALPHA / k
    tests = {}
    for h, d in horizons.items():
        ic = (d.get('ic_cross_sectional') or {}).get(VALIDATION_COMPONENT)
        t = (d.get('ic_cross_sectional_t') or {}).get(VALIDATION_COMPONENT)
        p = None if t is None else round(two_sided_p(t), 4)
        tests[h] = {'cross_sectional_ic': ic, 't_stat': t, 'p_value': p,
                    'significant_after_correction': p is not None and p < threshold and ic > 0}
    demonstrated = any(x['significant_after_correction'] for x in tests.values()) and not wf.get('stale')
    detail = '; '.join(f"{h}: IC {x['cross_sectional_ic']}, t={x['t_stat']}, p={x['p_value']}"
                       for h, x in tests.items())
    if demonstrated:
        statement = (f'The combined signal showed statistically significant out-of-sample ranking '
                     f'power in the walk-forward of {wf.get("computed_at")} ({detail}; Bonferroni '
                     f'threshold p < {threshold:.4f}). Past skill does not guarantee future skill.')
    else:
        components = ', '.join(wf.get('validated_components') or []) or 'technical, fundamentals, insider'
        statement = (f'This signal has NOT demonstrated statistically significant predictive power '
                     f'out-of-sample. The walk-forward ({wf.get("computed_at")}, {wf.get("n_tickers")} '
                     f'tickers) evaluated the signal WITHOUT news ({components}): {detail}; required '
                     f'p < {threshold:.4f} after Bonferroni correction over {k} horizons. ' + news_note
                     + ('The validation is stale. ' if wf.get('stale') else '')
                     + ('Separately, ' + research_text if research_text else ''))
    return {'status': 'DEMONSTRATED' if demonstrated else 'NOT DEMONSTRATED',
            'demonstrated': demonstrated, 'criterion': f'cross-sectional IC of the {VALIDATION_COMPONENT} '
            f'score, two-sided p < {VALIDATION_ALPHA} / {k} horizons, IC > 0',
            'tests': tests, 'computed_at': wf.get('computed_at'), 'stale': wf.get('stale'),
            'live_signal_validated': False, 'research': [r for r in (research or []) if r],
            'excluded_from_validation': wf.get('excluded'), 'statement': statement}


def not_implemented_fields(walk_forward=None):
    """Model prediction / confidence / risk: explicitly unavailable (never a placeholder)."""
    return {
        'model_prediction': {
            'status': NOT_IMPLEMENTED,
            'reason': ('The walk-forward-fitted model has not shown out-of-sample skill; it is not '
                       'used for live predictions.')},
        'prediction_confidence': {
            'status': NOT_IMPLEMENTED,
            'reason': 'No calibrated model: no probability or confidence is produced.'},
        'risk_score': {'status': NOT_IMPLEMENTED, 'reason': 'Risk engine not built yet (phase P3.1).'},
    }


class ScoringSignalFixed:
    """Quantitative signal from technical / fundamental / news / insider heuristic scores."""

    WEIGHTS = {'technical': 0.25, 'fundamentals': 0.40, 'news': 0.20, 'insider': 0.15}
    MIN_COMPONENTS = 2
    POSITIVE_THRESHOLD = 65
    NEGATIVE_THRESHOLD = 40

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
        if combined_score >= self.POSITIVE_THRESHOLD:
            return 'POSITIVE'
        if combined_score <= self.NEGATIVE_THRESHOLD:
            return 'NEGATIVE'
        return 'NEUTRAL'

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

    def analyze(self, ticker, tech_result, fund_result, news_result, insider_result=None):
        print(f"  [SIGNAL] {ticker}...")
        insider_result = insider_result or {}

        scores = {
            'technical': tech_result.get('technical_score'),
            'fundamentals': fund_result.get('fundamental_score'),
            'news': news_result.get('news_score'),
            'insider': insider_result.get('insider_score'),
        }
        signals = {
            'technical': tech_result.get('signal'),
            'fundamentals': fund_result.get('signal'),
            'news': news_result.get('signal'),
            'insider': insider_result.get('signal'),
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
            summary = (f"{INSUFFICIENT_DATA} ({len(available)}/{len(scores)} sources available; "
                       f"missing: {', '.join(missing)})")
        else:
            summary = (f"Quantitative signal {final_signal} (signal strength {combined}/100, "
                       f"coverage {len(available)}/{len(scores)}"
                       + (f", missing: {', '.join(missing)}" if missing else '') + ")")

        return {
            'ticker': ticker,
            'quantitative_signal': final_signal,
            'signal_strength': combined,
            'signal_agreement': agreement,
            'coverage': f"{len(available)}/{len(scores)}",
            'available_components': available,
            'missing_components': missing,
            'component_scores': scores,
            'component_signals': signals,
            'score_type': 'heuristic 0-100 score, not a probability; weights not validated',
            'signal_summary': summary,
            'disclaimer': NOT_A_RECOMMENDATION,
            'timestamp': utc_now_iso(),
            'source': 'Multi-Source heuristic v4',
        }


if __name__ == "__main__":
    pass
