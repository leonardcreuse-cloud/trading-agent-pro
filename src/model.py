#!/usr/bin/env python3
"""
Fitted cross-sectional model, validated walk-forward (phases P1.3 / P1.6, first version)

Model: ridge regression of the cross-sectional rank of the forward return on the
cross-sectional ranks of the features (features.py).
- On each date, every feature is rank-normalised across tickers to [-0.5, 0.5]; a missing
  value gets 0 (the cross-sectional median): it then contributes nothing to that date's
  prediction. A feature reported by fewer than MIN_CROSS_SECTION tickers on a date is 0
  for all of them. The share of missing values per feature is reported.
- Target: forward return over H sessions (close T+1 -> close T+1+H), rank-normalised the
  same way. Ranks make the fit robust to outliers and to market-wide moves.
- Ridge penalty ALPHA * n fixed a priori (not tuned on the data: no hidden selection).

Walk-forward protocol (out-of-sample):
- Test folds = calendar half-years. For each fold, the model is fitted only on samples
  whose outcome was known before the fold starts (exit date < first test date: purged,
  no overlap with the test period), with at least MIN_TRAIN_DATES evaluation dates.
- Predictions on the test fold are scored with the cross-sectional IC and a
  top-minus-bottom quintile spread, next to the fixed heuristic on the same dates.
Nothing here is a probability: the model output is a relative ranking score.
"""

import math

import numpy as np

from .features import FEATURES

ALPHA = 0.1
MIN_TRAIN_DATES = 52          # one year of weekly evaluation dates
MIN_CROSS_SECTION = 10
QUANTILE = 0.2


def half_year(day):
    return f"{day[:4]}H{1 if int(day[5:7]) <= 6 else 2}"


def _ranks(values):
    """Average ranks normalised to [-0.5, 0.5]; None stays None."""
    idx = [i for i, v in enumerate(values) if v is not None]
    out = [None] * len(values)
    if len(idx) < 2:
        return out
    order = sorted(idx, key=lambda i: values[i])
    pos = 0
    while pos < len(order):
        end = pos
        while end + 1 < len(order) and values[order[end + 1]] == values[order[pos]]:
            end += 1
        rank = (pos + end) / 2
        for k in range(pos, end + 1):
            out[order[k]] = rank / (len(order) - 1) - 0.5
        pos = end + 1
    return out


def design(rows, horizon, features=FEATURES, min_tickers=MIN_CROSS_SECTION):
    """
    Rank-normalised features X, target y (None when the outcome is unknown) and the rows,
    grouped by date. Returns (X: n x k array, y: list, rows in the same order).
    """
    key = f'fwd_{horizon}d'
    by_date = {}
    for r in rows:
        by_date.setdefault(r['date'], []).append(r)
    X, y, ordered = [], [], []
    for day in sorted(by_date):
        group = by_date[day]
        if len(group) < min_tickers:
            continue
        cols = []
        for f in features:
            raw = [g['features'].get(f) for g in group]
            ranked = _ranks(raw) if sum(v is not None for v in raw) >= min_tickers else [None] * len(raw)
            cols.append([0.0 if v is None else v for v in ranked])
        target = _ranks([g[key] for g in group])
        for j, g in enumerate(group):
            X.append([c[j] for c in cols])
            y.append(target[j])
            ordered.append(g)
    return np.array(X, dtype=float).reshape(len(X), len(features)), y, ordered


def fit_ridge(X, y, alpha=ALPHA):
    """Ridge without intercept (ranked inputs and target are centred): (X'X + a n I)^-1 X'y."""
    n, k = X.shape
    return np.linalg.solve(X.T @ X + alpha * n * np.eye(k), X.T @ np.asarray(y, dtype=float))


def _spearman(a, b):
    if len(a) < 3:
        return None
    ra, rb = _ranks(list(a)), _ranks(list(b))
    ra, rb = np.array(ra), np.array(rb)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def _summarise(daily, horizon, step):
    vals = [v for v in daily if v is not None]
    if len(vals) < 3:
        return {'n_dates': len(vals), 'mean': None, 't_stat': None, 'significant': False}
    mean = float(np.mean(vals))
    std = float(np.std(vals, ddof=1))
    n_eff = len(vals) * min(1.0, step / horizon)
    t = mean / std * math.sqrt(n_eff) if std > 0 else None
    return {'n_dates': len(vals), 'n_effective': round(n_eff, 1), 'mean': round(mean, 5),
            'positive_dates_pct': round(sum(v > 0 for v in vals) / len(vals) * 100, 1),
            't_stat': None if t is None else round(t, 2),
            'significant': bool(t is not None and abs(t) >= 2)}


def score_predictions(rows, pred_key, horizon, step, min_tickers=MIN_CROSS_SECTION):
    """Cross-sectional IC and top-minus-bottom quintile spread of rows[pred_key]."""
    key = f'fwd_{horizon}d'
    by_date = {}
    for r in rows:
        if r.get(pred_key) is not None and r[key] is not None:
            by_date.setdefault(r['date'], []).append((r[pred_key], r[key]))
    ics, spreads = [], []
    for pairs in by_date.values():
        if len(pairs) < min_tickers:
            continue
        ics.append(_spearman([p[0] for p in pairs], [p[1] for p in pairs]))
        pairs = sorted(pairs, key=lambda p: p[0])
        q = max(1, int(len(pairs) * QUANTILE))
        spreads.append(np.mean([p[1] for p in pairs[-q:]]) - np.mean([p[1] for p in pairs[:q]]))
    ic = _summarise(ics, horizon, step)
    spread = _summarise([s * 100 for s in spreads], horizon, step)
    return {'ic': ic, 'top_minus_bottom_quintile_pct': spread}


def walk_forward_model(rows, horizon, step, alpha=ALPHA, features=FEATURES):
    """Fit on the past, predict the next half-year, for every fold (see module docstring)."""
    X, y, ordered = design(rows, horizon, features)
    if not ordered:
        return {'status': 'INSUFFICIENT DATA', 'reason': f'no date with >= {MIN_CROSS_SECTION} tickers'}
    exit_key = f'exit_{horizon}d'
    dates = [r['date'] for r in ordered]
    folds = sorted({half_year(d) for d in dates})
    preds = [None] * len(ordered)
    fold_info = {}
    for fold in folds:
        test = [i for i, d in enumerate(dates) if half_year(d) == fold]
        start = min(dates[i] for i in test)
        train = [i for i, r in enumerate(ordered)
                 if y[i] is not None and r[exit_key] is not None and r[exit_key] < start]
        n_train_dates = len({dates[i] for i in train})
        if n_train_dates < MIN_TRAIN_DATES:
            fold_info[fold] = {'status': 'skipped', 'train_dates': n_train_dates}
            continue
        beta = fit_ridge(X[train], [y[i] for i in train], alpha)
        for i in test:
            preds[i] = float(X[i] @ beta)
        fold_info[fold] = {'status': 'tested', 'train_dates': n_train_dates,
                           'train_end_before': start,
                           'coefficients': {f: round(float(b), 4) for f, b in zip(features, beta)}}
    scored = [dict(r, model=p) for r, p in zip(ordered, preds)]
    tested = [r for r in scored if r['model'] is not None]
    if not tested:
        return {'status': 'INSUFFICIENT DATA', 'folds': fold_info,
                'reason': f'less than {MIN_TRAIN_DATES} training dates before every fold'}

    per_fold = {}
    for fold, info in fold_info.items():
        if info['status'] == 'tested':
            fold_rows = [r for r in tested if half_year(r['date']) == fold]
            per_fold[fold] = score_predictions(fold_rows, 'model', horizon, step)['ic']['mean']
    final_train = [i for i in range(len(ordered)) if y[i] is not None]
    final = fit_ridge(X[final_train], [y[i] for i in final_train], alpha)
    coef_signs = {f: [fold_info[k]['coefficients'][f] > 0 for k in fold_info
                      if fold_info[k]['status'] == 'tested'] for f in features}
    return {
        'status': 'OK',
        'alpha': alpha,
        'features': list(features),
        'missing_share_pct': {f: round(sum(r['features'].get(f) is None for r in ordered)
                                       / len(ordered) * 100, 1) for f in features},
        'test_period': [min(r['date'] for r in tested), max(r['date'] for r in tested)],
        'model_oos': score_predictions(tested, 'model', horizon, step),
        'heuristic_same_dates': score_predictions(tested, 'combined', horizon, step),
        'technical_same_dates': score_predictions(tested, 'technical', horizon, step),
        'fold_ic': per_fold,
        'folds_with_positive_ic': f"{sum(v > 0 for v in per_fold.values() if v is not None)}/"
                                  f"{sum(v is not None for v in per_fold.values())}",
        'folds': fold_info,
        'coefficient_sign_stability_pct': {
            f: round(max(sum(s), len(s) - sum(s)) / len(s) * 100, 1) if s else None
            for f, s in coef_signs.items()},
        'final_coefficients_all_data': {f: round(float(b), 4) for f, b in zip(features, final)},
    }


def feature_ics(rows, horizon, step, features=FEATURES):
    """Cross-sectional IC of each raw feature (descriptive, nothing fitted)."""
    out = {}
    for f in features:
        flat = [dict(r, _f=r['features'].get(f)) for r in rows]
        out[f] = score_predictions(flat, '_f', horizon, step)['ic']
    return out
