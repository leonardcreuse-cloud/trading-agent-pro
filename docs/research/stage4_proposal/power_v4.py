#!/usr/bin/env python3
"""
Stage 4 proposal v4: sample-size validity rule and power of the primary test. NOT the experiment.

**Inputs: event COUNTS only.**
- Events per year in the v1 feasibility sample (`feasibility.json`, 60 companies).
- The share of primary-set events (`feasibility_v3.json`).
- No price, return or outcome is read.
- The simulated data below are SYNTHETIC: random numbers drawn under stated assumptions, used only to measure how
  the pre-registered test behaves (false-positive rate and power).

**Primary statistic (unchanged).** ρ̄ = the mean over the M eligible quarters of ρ_q, the Spearman correlation of
EAR and DRIFT40 within quarter q.

**Two tests are compared.**
- 'v3', the test of v1–v3: Newey–West, Bartlett kernel, lag 1. Var = (γ0 + γ1)/M; Student t with M − 1 df.
- 'v4', the test proposed in v4: a lag-1 HAC with truncated kernel (Hansen–Hodrick), the lag-1 term floored at 0,
  and two small-sample corrections:
  - Var = (γ0 + 2·max(γ1, 0)) / M × M/(M − 2);
  - Student t with floor(M/2) − 1 df.

**Evaluations.**
1. Analytic design SE from the counts, used by validity rule V2: Var(ρ_q) = 1/(n_q − 1) + σ_b², and correlation φ
   between adjacent quarters (MA(1)).
2. Monte Carlo of each test:
   - (a) event level: n_q synthetic bivariate-normal (EAR, DRIFT) pairs per quarter and the exact Spearman
     correlation, with independent quarters;
   - (b) quarter level: Gaussian ρ_q with the same variances, and MA(1) dependence (the window overlap of adjacent
     quarters) or AR(1) dependence (persistent regimes, a stress case).

Usage: python docs/research/stage4_proposal/power_v4.py -> docs/research/stage4_proposal/power_v4.json
"""

import json
import math
from pathlib import Path

import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
OUT = HERE / 'power_v4.json'
ALPHA = 0.05
DELTA_STAR = 0.03                       # effect of interest, fixed in v4
PLAN = {'sigma_b': 0.03, 'phi': 0.22}   # planning scenario used by rule V2
PLAN_PRICE_EXCLUSION = 0.05
SIGMA_B = (0.0, 0.03, 0.05)
PHI = (0.0, 0.22, 0.40)
PRICE_EXCLUSION = (0.0, 0.05, 0.10)
DELTAS = (0.0, 0.02, 0.03, 0.04, 0.05)
SEED = 20261014


# ---------------------------------------------------------------- expected counts (filings only)

def expected_counts(share, price_exclusion):
    """
    Expected eligible events per quarter, 2016Q1–2025Q4 (40 quarters).
    - Each company reports once a quarter, so a quarter holds about a quarter of the year's events.
    - Feasibility counts are scaled from 60 to 500 companies.
    """
    v1 = json.loads((HERE / 'feasibility.json').read_text())
    scale = v1['list_members_with_cik'] / v1['firms_counted'] / 4
    return [round(v1['events_per_year'][str(y)] * scale * share * (1 - price_exclusion))
            for y in range(2016, 2026) for _ in range(4)]


# ---------------------------------------------------------------- analytic design (rule V2)

def design_se(n, sigma_b, phi, adjacent=None):
    """
    Design SE of ρ̄ for quarters with counts n, in calendar order.
    - Var(ρ_q) = 1/(n_q − 1) + σ_b²: the exact null variance of a Spearman correlation, plus the between-quarter
      variance of the true correlation.
    - Correlation φ between adjacent quarters only.
    - adjacent[t] = False when quarter t−1 is missing (dropped quarters are not bridged).
    """
    w = [1 / (k - 1) + sigma_b ** 2 for k in n]
    adjacent = adjacent or [True] * len(n)
    cov = sum(math.sqrt(w[t] * w[t - 1]) for t in range(1, len(n)) if adjacent[t])
    return math.sqrt(sum(w) + 2 * phi * cov) / len(n)


def v4_df(m):
    return m // 2 - 1


def v4_half_width(se, m):
    """Planned 95% CI half-width of the v4 test: t(0.975, floor(M/2) − 1) · √(M/(M − 2)) · SE_design."""
    return float(stats.t.ppf(1 - ALPHA / 2, v4_df(m)) * math.sqrt(m / (m - 2)) * se)


def v4_power(se, delta, m):
    """Approximate power of the v4 test: noncentral t with floor(M/2) − 1 df, noncentrality δ/(SE·√(M/(M−2)))."""
    df, scale = v4_df(m), math.sqrt(m / (m - 2))
    tc, nc = stats.t.ppf(1 - ALPHA / 2, df), delta / (se * scale)
    upper, lower = stats.nct.sf(tc, df, nc), stats.nct.cdf(-tc, df, nc)
    return float(upper + (0.0 if np.isnan(lower) else lower))     # the far tail underflows to NaN for large nc


def v4_mde(se, m, power=0.80):
    lo, hi = 1e-6, 0.2
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if v4_power(se, mid, m) < power else (lo, mid)
    return hi


# ---------------------------------------------------------------- the tests on simulated ρ_q

def reject(rho, test):
    """rho: array (reps, M) of quarterly correlations of consecutive quarters. The rejection flags of `test`."""
    m = rho.shape[1]
    e = rho - rho.mean(axis=1, keepdims=True)
    g0 = (e ** 2).sum(axis=1) / m
    g1 = (e[:, 1:] * e[:, :-1]).sum(axis=1) / m
    if test == 'v3':
        var, df = (g0 + g1) / m, m - 1
    else:
        var, df = (g0 + 2 * np.maximum(g1, 0)) / m * m / (m - 2), v4_df(m)
    return np.abs(rho.mean(axis=1) / np.sqrt(var)) > stats.t.ppf(1 - ALPHA / 2, df)


def spearman_rows(x, y):
    n = x.shape[1]
    rx = x.argsort(axis=1).argsort(axis=1)
    ry = y.argsort(axis=1).argsort(axis=1)
    return 1 - 6 * ((rx - ry) ** 2).sum(axis=1) / (n * (n * n - 1))


def simulate_event_level(n, delta, sigma_b, reps, rng):
    """
    SYNTHETIC data.
    - Per quarter, the true Spearman correlation is c_q = δ + b_q, with b_q ~ N(0, σ_b²), independent across
      quarters.
    - n_q bivariate-normal pairs are drawn with the Pearson r that gives Spearman c_q: r = 2 sin(π c / 6).
    """
    rho = np.empty((reps, len(n)))
    for q, k in enumerate(n):
        c = delta + sigma_b * rng.standard_normal((reps, 1))
        r = 2 * np.sin(np.pi * c / 6)
        x = rng.standard_normal((reps, k))
        y = r * x + np.sqrt(1 - r ** 2) * rng.standard_normal((reps, k))
        rho[:, q] = spearman_rows(x, y)
    sd_error = max(abs(rho[:, q].std() / math.sqrt(1 / (k - 1) + sigma_b ** 2) - 1) for q, k in enumerate(n))
    return rho, float(sd_error)


def simulate_quarter_level(n, delta, sigma_b, phi, kind, reps, rng):
    """
    SYNTHETIC data: ρ_q = δ + d_q, with d Gaussian and Var(d_q) = 1/(n_q − 1) + σ_b².
    Dependence between quarters:
    - MA(1): correlation φ at lag 1 and 0 beyond (the overlap of adjacent quarters' windows);
    - AR(1): correlation φ^k at lag k (persistent regimes, a stress case beyond the design).
    """
    m = len(n)
    s = np.sqrt([1 / (k - 1) + sigma_b ** 2 for k in n])
    lag = np.abs(np.subtract.outer(np.arange(m), np.arange(m)))
    corr = np.where(lag == 0, 1.0, np.where(lag == 1, phi, 0.0)) if kind == 'MA1' else phi ** lag
    return delta + rng.standard_normal((reps, m)) @ np.linalg.cholesky(corr * np.outer(s, s)).T


def main():
    rng = np.random.default_rng(SEED)
    v3 = json.loads((HERE / 'feasibility_v3.json').read_text())
    share, timed = v3['primary_share'], v3['timed_sample_size']
    half = 1.96 * math.sqrt(share * (1 - share) / timed)
    shares = {'low (95% bound)': round(share - half, 3), 'central': share, 'high (95% bound)': round(share + half, 3)}

    by_counts = {}
    for label, sh in shares.items():
        for x in PRICE_EXCLUSION:
            n = expected_counts(sh, x)
            se = design_se(n, **PLAN)
            by_counts[f'share {label}, price exclusion {x:.0%}'] = {
                'total': sum(n), 'per_quarter_min': min(n), 'per_quarter_max': max(n),
                'per_quarter_mean': round(sum(n) / 40, 1), 'quarters_with_100_or_more': sum(k >= 100 for k in n),
                'design_se': round(se, 5), 'v4_half_width_95': round(v4_half_width(se, 40), 4),
                'rule_v2_passes': v4_half_width(se, 40) <= DELTA_STAR,
                'v4_power_at_0.03': round(v4_power(se, DELTA_STAR, 40), 3)}
    plan_n = expected_counts(share, PLAN_PRICE_EXCLUSION)
    plan_se = design_se(plan_n, **PLAN)
    needed = next(k for k in range(100, 3000) if v4_half_width(design_se([k] * 40, **PLAN), 40) <= DELTA_STAR)

    design = []
    for sb in SIGMA_B:
        for phi in PHI:
            se = design_se(plan_n, sb, phi)
            design.append({'sigma_b': sb, 'phi': phi, 'design_se': round(se, 5),
                           'v4_half_width_95': round(v4_half_width(se, 40), 4), 'v4_mde_80': round(v4_mde(se, 40), 4),
                           'v4_power': {f'{d:.2f}': round(v4_power(se, d, 40), 3) for d in DELTAS}})

    event_level = []
    for sb in SIGMA_B:
        for d in (0.0, 0.03):
            rho, sd_error = simulate_event_level(plan_n, d, sb, 2000, rng)
            event_level.append({'sigma_b': sb, 'delta': d, 'reps': 2000,
                                'rejection_v3_test': round(float(reject(rho, 'v3').mean()), 3),
                                'rejection_v4_test': round(float(reject(rho, 'v4').mean()), 3),
                                'max_relative_error_of_assumed_sd': round(sd_error, 3)})
    quarter_level = []
    for kind, sb, phi in (('MA1', 0.03, 0.0), ('MA1', 0.03, 0.22), ('MA1', 0.03, 0.40), ('MA1', 0.05, 0.22),
                          ('AR1', 0.03, 0.22), ('AR1', 0.03, 0.40)):
        row = {'dependence': kind, 'sigma_b': sb, 'phi': phi, 'reps': 20000}
        for d in DELTAS:
            rho = simulate_quarter_level(plan_n, d, sb, phi, kind, 20000, rng)
            row[f'v3_test_{d:.2f}'] = round(float(reject(rho, 'v3').mean()), 3)
            row[f'v4_test_{d:.2f}'] = round(float(reject(rho, 'v4').mean()), 3)
        quarter_level.append(row)
    m32 = []
    for phi in (0.0, 0.22, 0.40):
        rho = simulate_quarter_level(plan_n[:32], 0.0, 0.03, phi, 'MA1', 20000, rng)
        m32.append({'quarters': 32, 'phi': phi, 'size_v3_test': round(float(reject(rho, 'v3').mean()), 3),
                    'size_v4_test': round(float(reject(rho, 'v4').mean()), 3)})

    result = {'nature': 'design calculation: event counts and stated assumptions only; simulated data are '
                        'synthetic; no price, return or outcome is read',
              'alpha_two_sided': ALPHA, 'effect_of_interest': DELTA_STAR, 'planning_scenario': PLAN,
              'planning_price_exclusion': PLAN_PRICE_EXCLUSION, 'primary_share': shares,
              'planning_counts_per_quarter': plan_n, 'planning_total_events': sum(plan_n),
              'planning_design_se': round(plan_se, 5),
              'planning_v4_half_width_95': round(v4_half_width(plan_se, 40), 4),
              'planning_v4_power_at_0.03': round(v4_power(plan_se, DELTA_STAR, 40), 3),
              'uniform_quarterly_count_needed_for_rule_v2': needed,
              'by_counts': by_counts, 'design_by_scenario': design,
              'simulation_event_level': event_level, 'simulation_quarter_level': quarter_level,
              'simulation_size_with_32_quarters': m32, 'seed': SEED}
    OUT.write_text(json.dumps(result, indent=1), encoding='utf-8')
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
