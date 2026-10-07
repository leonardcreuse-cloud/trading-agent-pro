#!/usr/bin/env python3
"""
Statistics for the research study (phase P2.1)

- Rank IC per date: Spearman correlation across stocks of a score and the forward return.
- Mean IC test: Newey-West (Bartlett kernel) standard error with lag L = ceil(H / STEP) - 1,
  which accounts for the overlap of H-session windows sampled every STEP sessions;
  two-sided p from the normal distribution; 95 % confidence interval mean +/- 1.96 se.
- Multiple testing: Benjamini-Hochberg q-values (false discovery rate) and Bonferroni within a
  family of tests, both reported; a result is called significant only after correction.
- Portfolios (non-overlapping): rebalanced every H sessions; top and bottom quintile, equal
  weight; turnover = sum of |weight changes| per leg; cost = COST_BPS per unit of turnover;
  Sharpe / Sortino with a zero risk-free rate (stated), annualised with 252 / H periods;
  max drawdown of the compounded net series; benchmarks SPY and the equal-weight universe.
"""

import math

import numpy as np

COST_BPS = 10.0
QUANTILE = 0.2
MIN_STOCKS = 20


def rankdata(values):
    """Average ranks (1-based) of a 1-D array."""
    values = np.asarray(values, dtype=float)
    order = np.argsort(values, kind='mergesort')
    ranks = np.empty(len(values))
    sorted_values = values[order]
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and sorted_values[j + 1] == sorted_values[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3:
        return None
    rx, ry = rankdata(x), rankdata(y)
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def normal_p(z):
    return math.erfc(abs(z) / math.sqrt(2))


def newey_west(series, lags):
    """(mean, standard error, n) with a Bartlett-kernel HAC variance."""
    x = np.asarray([v for v in series if v is not None], dtype=float)
    n = len(x)
    if n < 3:
        return None, None, n
    mean = float(x.mean())
    e = x - mean
    gamma0 = float(e @ e) / n
    var = gamma0
    for lag in range(1, min(lags, n - 1) + 1):
        w = 1 - lag / (lags + 1)
        var += 2 * w * float(e[lag:] @ e[:-lag]) / n
    var = max(var, 0.0)
    return mean, math.sqrt(var / n) if var > 0 else None, n


def mean_test(series, lags):
    mean, se, n = newey_west(series, lags)
    if mean is None or not se:
        return {'n': n, 'mean': mean, 'se': se, 't_stat': None, 'p_value': None, 'ci95': None}
    t = mean / se
    return {'n': n, 'mean': round(mean, 6), 'se': round(se, 6), 't_stat': round(t, 3),
            'p_value': normal_p(t), 'ci95': [round(mean - 1.96 * se, 6), round(mean + 1.96 * se, 6)]}


def nw_lags(horizon, step):
    return max(0, math.ceil(horizon / step) - 1)


def daily_ics(by_date, min_stocks=MIN_STOCKS):
    """{date: IC} from {date: [(score, return)]} (dates with >= min_stocks pairs)."""
    out = {}
    for day, pairs in sorted(by_date.items()):
        pairs = [(s, r) for s, r in pairs if s is not None and r is not None]
        if len(pairs) >= min_stocks:
            ic = spearman([p[0] for p in pairs], [p[1] for p in pairs])
            if ic is not None:
                out[day] = ic
    return out


def benjamini_hochberg(pvalues):
    """q-values in the input order (None stays None)."""
    idx = [i for i, p in enumerate(pvalues) if p is not None]
    m = len(idx)
    q = [None] * len(pvalues)
    if not m:
        return q
    order = sorted(idx, key=lambda i: pvalues[i])
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m / rank)
        q[i] = min(1.0, running)
    return q


def correct(tests, alpha=0.05):
    """Add q_value (BH), p_bonferroni and significant flags to a list of test dicts in place."""
    p = [t.get('p_value') for t in tests]
    q = benjamini_hochberg(p)
    m = sum(v is not None for v in p)
    for t, qv in zip(tests, q):
        t['q_value_bh'] = None if qv is None else round(qv, 4)
        t['p_bonferroni'] = None if t.get('p_value') is None else round(min(1.0, t['p_value'] * m), 4)
        t['significant_bh'] = qv is not None and qv < alpha
        t['significant_bonferroni'] = t['p_bonferroni'] is not None and t['p_bonferroni'] < alpha
        if t.get('p_value') is not None:
            t['p_value'] = round(t['p_value'], 5)
    return tests


# ---------------------------------------------------------------- portfolios

def _perf(returns, periods_per_year):
    r = np.asarray(returns, float)
    if len(r) < 2:
        return {'n_periods': len(r)}
    mean, sd = float(r.mean()), float(r.std(ddof=1))
    downside = r[r < 0]
    dd = float(np.sqrt((downside ** 2).mean())) if len(downside) else 0.0
    wealth = np.cumprod(1 + r)
    peak = np.maximum.accumulate(wealth)
    t = mean / (sd / math.sqrt(len(r))) if sd > 0 else None
    return {'n_periods': len(r),
            'mean_period_return_pct': round(mean * 100, 4),
            'annualised_return_pct': round(((wealth[-1]) ** (periods_per_year / len(r)) - 1) * 100, 3)
            if wealth[-1] > 0 else None,
            'annualised_vol_pct': round(sd * math.sqrt(periods_per_year) * 100, 3),
            'sharpe': round(mean / sd * math.sqrt(periods_per_year), 3) if sd > 0 else None,
            'sortino': round(mean / dd * math.sqrt(periods_per_year), 3) if dd > 0 else None,
            'max_drawdown_pct': round(float((wealth / peak - 1).min()) * 100, 3),
            'hit_rate_pct': round(float((r > 0).mean()) * 100, 2),
            't_stat_mean': round(t, 3) if t is not None else None,
            'p_value_mean': normal_p(t) if t is not None else None}


def quintile_portfolios(by_date, rebalance_dates, horizon, benchmark=None, cost_bps=COST_BPS,
                        min_stocks=MIN_STOCKS):
    """
    by_date: {date: [(ticker, score, forward_return)]}; rebalance_dates: non-overlapping dates.
    Returns long-short, long-only (top quintile) and benchmark performance, gross and net.
    """
    prev_long, prev_short = {}, {}
    ls_gross, ls_net, long_gross, long_net, ew, spy, turnovers = [], [], [], [], [], [], []
    for day in rebalance_dates:
        pairs = [(t, s, r) for t, s, r in by_date.get(day, []) if s is not None and r is not None]
        if len(pairs) < min_stocks:
            continue
        pairs.sort(key=lambda p: p[1])
        q = max(1, int(len(pairs) * QUANTILE))
        short, long_ = pairs[:q], pairs[-q:]
        w_long = {t: 1 / q for t, _, _ in long_}
        w_short = {t: 1 / q for t, _, _ in short}
        to_long = sum(abs(w_long.get(t, 0) - prev_long.get(t, 0)) for t in set(w_long) | set(prev_long))
        to_short = sum(abs(w_short.get(t, 0) - prev_short.get(t, 0)) for t in set(w_short) | set(prev_short))
        prev_long, prev_short = w_long, w_short
        r_long = float(np.mean([r for _, _, r in long_]))
        r_short = float(np.mean([r for _, _, r in short]))
        cost = cost_bps / 1e4
        ls_gross.append(r_long - r_short)
        ls_net.append(r_long - r_short - cost * (to_long + to_short))
        long_gross.append(r_long)
        long_net.append(r_long - cost * to_long)
        ew.append(float(np.mean([r for _, _, r in pairs])))
        if benchmark and benchmark.get(day, {}).get(f'fwd_{horizon}d') is not None:
            spy.append(benchmark[day][f'fwd_{horizon}d'])
        turnovers.append((to_long + to_short) / 2)
    ppy = 252 / horizon
    long_excess_ew = [a - b for a, b in zip(long_net, ew)]
    return {
        'rebalance_every_sessions': horizon, 'cost_bps_per_unit_turnover': cost_bps,
        'risk_free_rate': 0.0,
        'mean_turnover_per_rebalance': round(float(np.mean(turnovers)), 3) if turnovers else None,
        'long_short_gross': _perf(ls_gross, ppy), 'long_short_net': _perf(ls_net, ppy),
        'long_only_top_quintile_net': _perf(long_net, ppy),
        'long_only_net_minus_equal_weight': _perf(long_excess_ew, ppy),
        'benchmark_equal_weight_universe': _perf(ew, ppy),
        'benchmark_spy': _perf(spy, ppy) if len(spy) == len(ew) else {'n_periods': len(spy),
                                                                     'note': 'SPY periods misaligned'},
    }
