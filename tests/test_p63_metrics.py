"""Master mission P3: classification / calibration metrics and the descriptive heuristic evaluation (SYNTHETIC data)."""

import pytest


def test_auc_mann_whitney_with_ties():
    from src.research.metrics import auc
    assert auc([1, 2, 3, 4], [0, 0, 1, 1]) == 1.0
    assert auc([1, 2, 3, 4], [1, 1, 0, 0]) == 0.0
    assert auc([1, 1, 1, 1], [0, 1, 0, 1]) == 0.5                 # all tied
    assert auc([1, 2, 3], [1, 1, 1]) is None                      # one class only


def test_confusion_metrics_and_undefined_ratios():
    from src.research.metrics import confusion
    m = confusion([True, True, False, False, True], [True, False, True, False, True])
    assert (m['tp'], m['fp'], m['fn'], m['tn']) == (2, 1, 1, 1)
    assert m['precision'] == pytest.approx(2 / 3, abs=1e-4) and m['recall'] == pytest.approx(2 / 3, abs=1e-4)
    assert m['f1'] == pytest.approx(2 / 3, abs=1e-4) and m['base_rate'] == 0.6
    none = confusion([False, False], [True, False])
    assert none['precision'] is None and none['f1'] is None           # no positive prediction: undefined, not 0


def test_brier_and_calibration():
    from src.research.metrics import brier, calibration
    assert brier([0.9, 0.1], [1, 0]) == pytest.approx(0.01)
    with pytest.raises(ValueError):
        brier([70], [1])                                               # a 0-100 score is not a probability
    c = calibration([0.05, 0.15, 0.95, 0.95], [0, 0, 1, 0])
    assert [b['n'] for b in c['bins']] == [1, 1, 2]
    assert c['bins'][-1]['observed_frequency'] == 0.5
    assert c['expected_calibration_error'] == pytest.approx((0.05 + 0.15 + 2 * 0.45) / 4, abs=1e-4)


def test_heuristic_evaluation_is_descriptive_and_uses_score_labels():
    from src.heuristic_evaluation import evaluate, spy_forward
    samples = []
    for d in range(30):
        day = f'2025-{1 + d // 28:02d}-{1 + d % 28:02d}'
        for t in range(25):
            score = 40 + t                                             # 40 .. 64; >= 65 never reached
            samples.append({'ticker': f'T{t}', 'date': day, 'combined': score + (5 if t > 20 else 0),
                            'signal': 'BUY', 'fwd_5d': (t - 12) / 1000, 'fwd_20d': None})
    closes = {f'2025-{1 + i // 28:02d}-{1 + i % 28:02d}': 100.0 + i for i in range(40)}
    res = evaluate({'samples': samples, 'computed_at': '2026-01-01T00:00:00+00:00'}, closes,
                   now='2026-01-02T00:00:00+00:00')
    c = res['horizons']['5d']['classification']
    assert c['positive_return']['label_positive']['tp'] > 0              # labels from the score (>= 65), not 'BUY'
    assert c['beats_cross_sectional_median']['auc_combined_score'] == 1.0
    assert c['probabilities'].startswith('NOT CALIBRATED')
    p = res['horizons']['5d']['portfolios']
    assert p['cost_bps_per_unit_turnover'] == 10.0 and p['long_only_top_quintile_net']['n_periods'] == 30
    assert 'no new hypothesis' in res['nature']
    fwd = spy_forward({'2025-01-01': 100.0, '2025-01-02': 110.0, '2025-01-03': 121.0}, ['2025-01-01'], (1,))
    assert fwd['2025-01-01']['fwd_1d'] == pytest.approx(0.1)          # entry at the next session's close
