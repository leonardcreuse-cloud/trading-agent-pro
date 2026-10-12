#!/usr/bin/env python3
"""
Intrinsic value scenarios (master mission P1) - a two-stage discounted free-cash-flow estimate, descriptive only

The output is an ESTIMATE UNDER STATED ASSUMPTIONS, never a fair value or a price target. Every input says where
it comes from; assumptions that have no allowed external source are configurable (scheduler_config.json
valuation.dcf) and labelled as assumptions.

  FCF0        free cash flow TTM = operating cash flow - capital expenditure (SEC). Treated as free cash flow to
              equity: interest is already paid inside operating cash flow, net borrowing is ignored (limitation),
              so it is discounted at the cost of equity and net debt is NOT subtracted.
              FCF0 <= 0: no value is computed (reliability NOT RELIABLE).
  g (base)    revenue TTM CAGR over the last 3 years (SEC, point-in-time), clipped to config growth_bounds_pct;
              FCF grows with revenue (constant FCF margin: assumption). bear = base - bear_minus_pts,
              bull = base + bull_plus_pts. Without 3 years of revenue: config default_growth_pct (assumption).
  path        years 1..N (config years): growth fades linearly from g to the terminal growth gT
  gT          config terminal_growth_pct (assumption); must be at least 1 point below the discount rate
  r           cost of equity = risk-free + beta x equity risk premium (CAPM)
                risk-free: 10-year Treasury yield (FRED DGS10) known at T (passed in by the caller)
                beta: OLS slope of weekly log returns of the stock on the benchmark's (SPY) over config beta_weeks
                      (at least MIN_BETA_WEEKS weeks), computed from observed closes
                equity risk premium: config equity_risk_premium_pct (assumption)
  value       sum of FCF_t / (1 + r)^t + TV / (1 + r)^N, TV = FCF_N x (1 + gT) / (r - gT); per share with the
              cover-page shares outstanding (else diluted weighted shares, flagged)
  sensitivity base case with r +/- 1 point and gT +/- 0.5 point (3 x 3)
  implied     reverse DCF: the starting growth g (same fade, same r and gT) at which the base value equals the
              market capitalisation (bisection on [-50%, +300%]); None when outside that range. It states what the
              price assumes under these rates, not what will happen.
Reliability: NOT RELIABLE (no value: FCF <= 0, no discount rate, no share count) / LOW (any flag: terminal value
> 75% of the total, FCF margin moved > 10 points in a year, growth from the default, share-count approximation,
possible split) / ASSUMPTION-DRIVEN (no flag). Never higher: the model's assumptions are not validated.
"""

import math
from datetime import date

DEFAULTS = {'years': 5, 'equity_risk_premium_pct': 5.0, 'terminal_growth_pct': 2.5,
            'growth_bounds_pct': [-5.0, 25.0], 'bear_minus_pts': 10.0, 'bull_plus_pts': 5.0,
            'default_growth_pct': 3.0, 'beta_weeks': 104}
MIN_BETA_WEEKS = 52
TV_SHARE_FLAG = 0.75
FCF_MARGIN_MOVE_FLAG = 10.0
GROWTH_YEARS = 3


def settings(config=None):
    """DCF settings: config valuation.dcf over DEFAULTS; returns (settings, list of keys taken from defaults)."""
    cfg = ((config or {}).get('valuation') or {}).get('dcf') or {}
    out = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    return out, [k for k in DEFAULTS if k not in cfg]


def weekly_returns(closes):
    """Weekly log returns from {iso date: close}: last close of each ISO week."""
    weeks = {}
    for day in sorted(closes):
        weeks[tuple(date.fromisoformat(day).isocalendar()[:2])] = closes[day]
    values = [weeks[k] for k in sorted(weeks)]
    keys = sorted(weeks)
    return {keys[i]: math.log(values[i] / values[i - 1]) for i in range(1, len(values)) if values[i - 1] > 0}


def beta(stock_closes, market_closes, weeks):
    """(beta, n_weeks) of weekly log returns over the last `weeks` common weeks; (None, n) below MIN_BETA_WEEKS."""
    a, b = weekly_returns(stock_closes), weekly_returns(market_closes)
    common = sorted(set(a) & set(b))[-weeks:]
    n = len(common)
    if n < MIN_BETA_WEEKS:
        return None, n
    xs, ys = [b[k] for k in common], [a[k] for k in common]
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs) / (n - 1)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n - 1)
    return (round(cov / var, 3) if var > 0 else None), n


def present_value(fcf0, growth, terminal, rate, years):
    """(value, pv of explicit years, pv of terminal value, cash flows) for a linearly fading growth path."""
    flows, fcf, pv = [], fcf0, 0.0
    for t in range(1, years + 1):
        g = growth + (terminal - growth) * (t - 1) / years
        fcf *= 1 + g
        flows.append(fcf)
        pv += fcf / (1 + rate) ** t
    tv = flows[-1] * (1 + terminal) / (rate - terminal)
    pv_tv = tv / (1 + rate) ** years
    return pv + pv_tv, pv, pv_tv, flows


def implied_growth(fcf0, market_cap, rate, terminal, years, lo=-0.5, hi=3.0):
    """Starting growth (%) whose fading path values the FCF stream at market_cap; None outside [lo, hi]."""
    if not market_cap or fcf0 is None or fcf0 <= 0:
        return None

    def gap(g):
        return present_value(fcf0, g, terminal, rate, years)[0] - market_cap
    if gap(lo) > 0 or gap(hi) < 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if gap(mid) < 0 else (lo, mid)
    return round((lo + hi) / 2 * 100, 2)


def dcf(X, close, risk_free_pct, beta_value, revenue_3y_ago=None, config=None, shares=None, shares_basis=None,
        share_flags=()):
    """
    Scenarios from extended fundamentals X (src/fundamentals_ext.py). risk_free_pct: DGS10 known at T (None ->
    no discount rate). beta_value: beta() result or None. revenue_3y_ago: revenue TTM ~3 years before X's TTM end.
    shares: per-share basis (valuation.shares_for). Returns a dict with 'reliability', 'reasons', 'flags',
    'assumptions', 'scenarios', 'sensitivity'.
    """
    s, defaulted = settings(config)
    out = {'reliability': 'NOT RELIABLE', 'reasons': [], 'flags': list(share_flags), 'scenarios': {},
           'sensitivity': None, 'assumptions': {}, 'defaulted_settings': defaulted}
    fcf0, rev = X.get('free_cash_flow_ttm'), X.get('revenue')
    if fcf0 is None:
        out['reasons'].append('free cash flow TTM unavailable')
    elif fcf0 <= 0:
        out['reasons'].append(f'free cash flow TTM is not positive ({fcf0:,.0f} USD): a cash-flow DCF is not meaningful')
    if risk_free_pct is None:
        out['reasons'].append('risk-free rate (10-year Treasury, FRED DGS10) unavailable at T')
    if beta_value is None:
        out['reasons'].append(f'beta unavailable (fewer than {MIN_BETA_WEEKS} weeks of common weekly returns)')
    if not shares:
        out['reasons'].append('no share count')
    if out['reasons']:
        return out
    erp, gT = s['equity_risk_premium_pct'] / 100, s['terminal_growth_pct'] / 100
    rate = risk_free_pct / 100 + beta_value * erp
    if rate - gT < 0.01:
        out['reasons'].append(f'discount rate {rate:.2%} is not at least 1 point above terminal growth {gT:.2%}')
        return out
    lo, hi = (x / 100 for x in s['growth_bounds_pct'])
    if rev and revenue_3y_ago and revenue_3y_ago > 0:
        cagr = (rev / revenue_3y_ago) ** (1 / GROWTH_YEARS) - 1
        base = min(max(cagr, lo), hi)
        growth_basis = (f'revenue TTM CAGR over {GROWTH_YEARS} years {cagr:.2%} (SEC)'
                        + (f', clipped to [{lo:.0%}, {hi:.0%}]' if base != cagr else ''))
    else:
        base = s['default_growth_pct'] / 100
        growth_basis = f"default_growth_pct {s['default_growth_pct']}% (assumption: revenue 3 years earlier unavailable)"
        out['flags'].append('growth from the configured default, not from the company history')
    out['assumptions'] = {
        'free_cash_flow_ttm': fcf0, 'risk_free_pct': risk_free_pct, 'beta': beta_value,
        'equity_risk_premium_pct': s['equity_risk_premium_pct'], 'cost_of_equity_pct': round(rate * 100, 2),
        'terminal_growth_pct': s['terminal_growth_pct'], 'years': s['years'], 'base_growth_pct': round(base * 100, 2),
        'growth_basis': growth_basis, 'shares': shares, 'shares_basis': shares_basis,
        'assumption_keys': ['equity_risk_premium_pct', 'terminal_growth_pct', 'growth_bounds_pct', 'bear_minus_pts',
                            'bull_plus_pts', 'years', 'constant FCF margin', 'FCF as free cash flow to equity']}
    scen = {'bear': base - s['bear_minus_pts'] / 100, 'base': base, 'bull': base + s['bull_plus_pts'] / 100}
    for name, g in scen.items():
        value, pv, pv_tv, flows = present_value(fcf0, g, gT, rate, s['years'])
        per_share = value / shares
        out['scenarios'][name] = {'growth_pct': round(g * 100, 2), 'equity_value': round(value),
                                  'per_share': round(per_share, 2), 'terminal_share_pct': round(pv_tv / value * 100, 1),
                                  'vs_close_pct': round((per_share / close - 1) * 100, 1) if close else None}
    grid = []
    for dr in (-0.01, 0.0, 0.01):
        row = []
        for dg in (-0.005, 0.0, 0.005):
            r2, g2 = rate + dr, gT + dg
            row.append(round(present_value(fcf0, base, g2, r2, s['years'])[0] / shares, 2) if r2 - g2 >= 0.01 else None)
        grid.append({'cost_of_equity_pct': round((rate + dr) * 100, 2), 'per_share_by_terminal_growth':
                     dict(zip([round((gT + d) * 100, 2) for d in (-0.005, 0.0, 0.005)], row))})
    out['sensitivity'] = grid
    out['implied_growth_pct'] = implied_growth(fcf0, close * shares if close else None, rate, gT, s['years'])
    if out['scenarios']['base']['terminal_share_pct'] > TV_SHARE_FLAG * 100:
        out['flags'].append(f"terminal value is {out['scenarios']['base']['terminal_share_pct']}% of the base value "
                            f'(> {TV_SHARE_FLAG:.0%}): the estimate rests mostly on the long-run assumptions')
    move = X.get('fcf_margin_pct_change_pts')
    if move is not None and abs(move) > FCF_MARGIN_MOVE_FLAG:
        out['flags'].append(f'free cash flow margin moved {move:+.1f} points in a year: FCF0 may not be representative')
    out['reliability'] = 'LOW' if out['flags'] else 'ASSUMPTION-DRIVEN'
    return out
