"""
Phases P1.3 / P1.6 (first version) - continuous features and walk-forward-fitted model (offline).

Synthetic panels only check the protocol: predictions for a fold never depend on that
fold's outcomes, a real relationship is recovered out-of-sample, noise is not "found".
"""

from datetime import date, timedelta

import numpy as np
import pytest

from src.features import FEATURES


def test_price_features():
    from src.features import price_features
    values = np.linspace(100, 200, 300)
    f = price_features(values)
    assert f['mom_1m'] == pytest.approx(200 / values[-22] - 1)
    assert f['mom_12_1'] == pytest.approx(values[-22] / values[-253] - 1)
    assert f['dist_high_1y'] == 0.0 and f['vol_3m'] > 0
    short = price_features(values[:100])
    assert short['mom_6m'] is None and short['mom_12_1'] is None and short['dist_high_1y'] is None


def test_fundamental_and_insider_features_keep_missing_values_missing():
    from src.features import feature_vector
    f = feature_vector(np.linspace(1, 2, 50), {'revenue': None, 'revenue_growth_pct': 12.0,
                                                 'debt_to_equity': None}, None)
    assert f['revenue_growth'] == 12.0 and f['log_revenue'] is None and f['debt_to_equity'] is None
    assert all(f[k] is None for k in ('insider_buyers', 'insider_sell_log', 'insider_disc_sell_log'))
    summary = {'distinct_buyers': 2, 'sell_value_usd': 999.0, 'discretionary_sell_value_usd': 0.0}
    g = feature_vector(np.linspace(1, 2, 50), None, summary)
    assert g['insider_buyers'] == 2.0 and g['insider_sell_log'] == 3.0 and g['insider_disc_sell_log'] == 0.0


def test_ranks_are_centred_and_handle_ties_and_missing():
    from src.model import _ranks
    assert _ranks([3, 1, 2]) == [0.5, -0.5, 0.0]
    assert _ranks([1, 1, 2, None]) == [-0.25, -0.25, 0.5, None]
    assert _ranks([None, 5]) == [None, None]


def panel(n_tickers=20, n_dates=160, signal=0.02, seed=0):
    """Weekly panel; forward return = signal * feature + noise."""
    rng = np.random.default_rng(seed)
    start = date(2022, 1, 7)
    rows = []
    for d in range(n_dates):
        day = start + timedelta(weeks=d)
        for t in range(n_tickers):
            x = float(rng.normal())
            row = {'ticker': f'T{t}', 'date': day.isoformat(), 'combined': float(rng.normal()),
                   'technical': None,
                   'features': {f: None for f in FEATURES}}
            row['features']['mom_3m'] = x
            row['features']['vol_3m'] = float(rng.normal())
            for h in (5, 20):
                row[f'fwd_{h}d'] = signal * x + float(rng.normal()) * 0.05
                row[f'exit_{h}d'] = (day + timedelta(days=7 * h // 5 + 1)).isoformat()
            rows.append(row)
    return rows


def test_design_ranks_per_date_and_zeroes_sparse_features():
    from src.model import design
    rows = panel(n_tickers=12, n_dates=2)
    rows[0]['features']['mom_3m'] = None
    X, y, ordered = design(rows, 5)
    i = FEATURES.index('mom_3m')
    assert X.shape == (24, len(FEATURES)) and X[0, i] == 0.0          # missing -> median rank
    assert np.all(X[:, FEATURES.index('debt_to_equity')] == 0)        # never reported
    assert max(X[:12, i]) == 0.5 and min(X[:12, i]) == -0.5


def test_model_recovers_real_relationship_out_of_sample():
    from src.model import walk_forward_model
    result = walk_forward_model(panel(signal=0.03), horizon=5, step=5)
    assert result['status'] == 'OK'
    assert result['model_oos']['ic']['mean'] > 0.2 and result['model_oos']['ic']['significant']
    assert result['final_coefficients_all_data']['mom_3m'] > 0
    assert result['coefficient_sign_stability_pct']['mom_3m'] == 100.0
    assert result['folds']['2022H1']['status'] == 'skipped'          # < 1 year of history


def test_model_does_not_find_signal_in_noise():
    from src.model import walk_forward_model
    result = walk_forward_model(panel(signal=0.0, seed=3), horizon=5, step=5)
    assert abs(result['model_oos']['ic']['mean']) < 0.05
    assert not result['model_oos']['ic']['significant']


def test_fold_predictions_do_not_depend_on_test_period_outcomes():
    from src.model import walk_forward_model
    rows = panel(signal=0.03)
    base = walk_forward_model(rows, horizon=5, step=5)
    fold = '2024H1'
    tampered = [dict(r) for r in rows]
    for r in tampered:
        if r['date'] >= '2024-01-01':          # rewrite test-period and later outcomes
            r['fwd_5d'] = -r['fwd_5d']
    changed = walk_forward_model(tampered, horizon=5, step=5)
    assert changed['folds'][fold]['coefficients'] == base['folds'][fold]['coefficients']


def test_training_samples_are_purged_before_the_fold():
    from src.model import walk_forward_model
    rows = panel(signal=0.03)
    for r in rows:                              # outcomes resolved after the next fold starts
        r['exit_5d'] = '2099-01-01'
    result = walk_forward_model(rows, horizon=5, step=5)
    assert result['status'] == 'INSUFFICIENT DATA'


def test_score_predictions_quintile_spread():
    from src.model import score_predictions
    rows = [{'date': '2024-01-05', 'p': t, 'fwd_5d': t / 100} for t in range(10)] + \
           [{'date': '2024-01-12', 'p': t, 'fwd_5d': t / 100} for t in range(10)] + \
           [{'date': '2024-01-19', 'p': t, 'fwd_5d': t / 50} for t in range(10)]
    out = score_predictions(rows, 'p', horizon=5, step=5)
    assert out['ic']['mean'] == 1.0
    assert out['top_minus_bottom_quintile_pct']['mean'] == pytest.approx((8 + 8 + 16) / 3, abs=1e-4)   # top 2 minus bottom 2
