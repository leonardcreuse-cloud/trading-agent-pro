#!/usr/bin/env python3
"""
Classification and calibration metrics (master mission P3)

  auc            Mann-Whitney: P(score of a random positive > score of a random negative), ties count half;
                 None when one class is empty
  confusion      precision = TP / (TP + FP), recall = TP / (TP + FN), F1 = 2PR / (P + R), accuracy, base rate;
                 a ratio with a zero denominator is None (never 0)
  brier          mean of (probability - outcome)^2, outcome in {0, 1}; only for genuine probabilities
  calibration    probabilities in CALIBRATION_BINS equal-width bins: mean predicted vs observed frequency and
                 count per bin, plus the expected calibration error (count-weighted mean |gap|)
A heuristic 0-100 score is NOT a probability: brier / calibration are never computed on it (the caller states
NOT CALIBRATED instead). These functions describe; significance is tested elsewhere (src/research/stats.py).
"""

CALIBRATION_BINS = 10


def auc(scores, labels):
    pairs = [(s, y) for s, y in zip(scores, labels) if s is not None and y is not None]
    pos = sorted(s for s, y in pairs if y)
    neg = sorted(s for s, y in pairs if not y)
    if not pos or not neg:
        return None
    # rank-based Mann-Whitney U with average ranks for ties
    allv = sorted([(s, 1) for s in pos] + [(s, 0) for s in neg], key=lambda x: x[0])
    ranks, i = {}, 0
    rank_sum = 0.0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        rank_sum += sum(avg for k in range(i, j + 1) if allv[k][1] == 1)
        i = j + 1
    u = rank_sum - len(pos) * (len(pos) + 1) / 2
    return round(u / (len(pos) * len(neg)), 4)


def confusion(predicted, actual):
    """Metrics of a binary prediction (True = predicted positive) against binary outcomes."""
    pairs = [(p, a) for p, a in zip(predicted, actual) if p is not None and a is not None]
    tp = sum(1 for p, a in pairs if p and a)
    fp = sum(1 for p, a in pairs if p and not a)
    fn = sum(1 for p, a in pairs if not p and a)
    tn = sum(1 for p, a in pairs if not p and not a)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    n = len(pairs)
    return {'n': n, 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'precision': None if precision is None else round(precision, 4),
            'recall': None if recall is None else round(recall, 4),
            'f1': None if f1 is None else round(f1, 4),
            'accuracy': round((tp + tn) / n, 4) if n else None,
            'base_rate': round((tp + fn) / n, 4) if n else None,
            'predicted_positive_rate': round((tp + fp) / n, 4) if n else None}


def brier(probabilities, outcomes):
    pairs = [(p, y) for p, y in zip(probabilities, outcomes) if p is not None and y is not None]
    if not pairs:
        return None
    if any(p < 0 or p > 1 for p, _ in pairs):
        raise ValueError('brier: probabilities must be in [0, 1]')
    return round(sum((p - float(y)) ** 2 for p, y in pairs) / len(pairs), 5)


def calibration(probabilities, outcomes, bins=CALIBRATION_BINS):
    pairs = [(p, y) for p, y in zip(probabilities, outcomes) if p is not None and y is not None]
    table = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        inside = [(p, y) for p, y in pairs if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if inside:
            table.append({'bin': [round(lo, 2), round(hi, 2)], 'n': len(inside),
                          'mean_predicted': round(sum(p for p, _ in inside) / len(inside), 4),
                          'observed_frequency': round(sum(float(y) for _, y in inside) / len(inside), 4)})
    ece = (sum(t['n'] * abs(t['mean_predicted'] - t['observed_frequency']) for t in table) / len(pairs)
           if pairs else None)
    return {'bins': table, 'expected_calibration_error': None if ece is None else round(ece, 4), 'n': len(pairs)}
