#!/usr/bin/env python3
"""
Risk engine (master mission P4) - position sizing, portfolio limits and risk metrics, all configurable

Settings: scheduler_config.json `risk` (RISK_DEFAULTS below are used, and named, for any missing key). They are
ASSUMPTIONS of the paper-trading rules, not validated optima.

Position sizing (size_position)
  risk per share   = entry - stop (long) + round-trip cost per share (commission, slippage and half-spread, both legs)
  planned loss     = shares x risk per share
  shares           = floor(equity x target_risk_pct / risk per share), then reduced by every limit that binds:
                     max_position_pct of equity (concentration), max_adv_participation_pct of the 20-day average
                     volume (liquidity), available cash
  rejected when    planned loss > max_risk_pct of equity (hard limit), stop >= entry, no volume history, average
                   daily traded value < min_avg_dollar_volume, or the size rounds to 0 shares
Position risk (planned loss / equity) is not the share of capital invested (notional / equity): both are reported.
A stop does NOT cap the realised loss: a gap through the stop, low liquidity or slippage can make the exit price
worse than the stop (the simulator fills a gapped stop at the open, below the stop).

Portfolio checks (check_portfolio): gross exposure <= max_gross_exposure_pct, per-sector exposure <= max_sector_pct,
largest position <= max_position_pct, number of positions <= max_positions; each breach is listed.

Risk metrics (portfolio_metrics / position_metrics): annualised volatility (daily log returns, 60 sessions), beta vs
the benchmark (60 sessions of daily returns, OLS), mean and maximum pairwise correlation of holdings (60 sessions),
drawdown from the peak and maximum drawdown of the equity curve, downside deviation, liquidity (days to exit at the
participation limit), sector and concentration shares, event risk (an earnings date inside the holding horizon),
data risk (missing inputs) and model uncertainty (validation status). No global risk score is produced: none has
been validated (RISK SCORE: NOT IMPLEMENTED).
"""

import math

import numpy as np
import pandas as pd

RISK_DEFAULTS = {
    'target_risk_pct': 1.0, 'max_risk_pct': 2.0, 'max_position_pct': 20.0, 'max_gross_exposure_pct': 100.0,
    'max_sector_pct': 40.0, 'max_positions': 10, 'max_adv_participation_pct': 1.0,
    'min_avg_dollar_volume': 20_000_000, 'stop_atr_multiple': 2.0, 'commission_bps': 1.0, 'slippage_bps': 5.0,
    'half_spread_bps': 2.0, 'metrics_window': 60,
}
RISK_SCORE_STATUS = 'NOT IMPLEMENTED: no global risk score has been validated; risk is reported as separate metrics'


def settings(config=None):
    cfg = (config or {}).get('risk') or {}
    return {k: cfg.get(k, v) for k, v in RISK_DEFAULTS.items()}, [k for k in RISK_DEFAULTS if k not in cfg]


def cost_per_share(price, s):
    """One-way cost per share (commission + slippage + half-spread, in bps of the price)."""
    return price * (s['commission_bps'] + s['slippage_bps'] + s['half_spread_bps']) / 1e4


def size_position(equity, cash, entry, stop, adv_shares, s):
    """
    {'accepted', 'shares', 'planned_loss', 'position_risk_pct', 'notional', 'notional_pct', 'binding', 'reasons'}
    for a long position (see module docstring).
    """
    out = {'accepted': False, 'shares': 0, 'planned_loss': None, 'position_risk_pct': None, 'notional': 0.0,
           'notional_pct': 0.0, 'binding': [], 'reasons': []}
    if entry is None or stop is None or entry <= 0:
        out['reasons'].append('no entry or stop price')
        return out
    if stop >= entry:
        out['reasons'].append(f'stop {stop:.4f} is not below the entry {entry:.4f}')
        return out
    if not adv_shares or adv_shares <= 0:
        out['reasons'].append('no average volume: liquidity unknown')
        return out
    if adv_shares * entry < s['min_avg_dollar_volume']:
        out['reasons'].append(f"average traded value {adv_shares * entry:,.0f} USD below "
                              f"{s['min_avg_dollar_volume']:,.0f} USD")
        return out
    per_share = entry - stop + 2 * cost_per_share(entry, s)
    shares = math.floor(equity * s['target_risk_pct'] / 100 / per_share)
    limits = {'max_position_pct': math.floor(equity * s['max_position_pct'] / 100 / entry),
              'max_adv_participation_pct': math.floor(adv_shares * s['max_adv_participation_pct'] / 100),
              'cash': math.floor(max(cash, 0) / (entry + cost_per_share(entry, s)))}
    for name, cap in limits.items():
        if cap < shares:
            shares = cap
            out['binding'].append(name)
    if shares <= 0:
        out['reasons'].append('size rounds to 0 shares (' + ', '.join(out['binding'] or ['risk budget']) + ')')
        return out
    loss = shares * per_share
    if loss > equity * s['max_risk_pct'] / 100:
        out['reasons'].append(f"planned loss {loss:,.2f} USD above the hard limit of {s['max_risk_pct']}% of equity")
        return out
    out.update(accepted=True, shares=shares, planned_loss=round(loss, 2),
               position_risk_pct=round(loss / equity * 100, 3), notional=round(shares * entry, 2),
               notional_pct=round(shares * entry / equity * 100, 2))
    return out


def check_portfolio(positions, equity, sectors, s):
    """positions: {ticker: notional}; sectors: {ticker: sector}. Returns the list of breaches (empty when fine)."""
    breaches = []
    gross = sum(abs(v) for v in positions.values())
    if equity > 0 and gross / equity * 100 > s['max_gross_exposure_pct'] + 1e-9:
        breaches.append(f"gross exposure {gross / equity * 100:.1f}% > {s['max_gross_exposure_pct']}%")
    by_sector = {}
    for t, v in positions.items():
        by_sector[sectors.get(t, 'unknown')] = by_sector.get(sectors.get(t, 'unknown'), 0) + abs(v)
    for sector, v in by_sector.items():
        if equity > 0 and v / equity * 100 > s['max_sector_pct'] + 1e-9:
            breaches.append(f"sector {sector} {v / equity * 100:.1f}% > {s['max_sector_pct']}%")
    for t, v in positions.items():
        if equity > 0 and abs(v) / equity * 100 > s['max_position_pct'] + 1e-9:
            breaches.append(f"position {t} {abs(v) / equity * 100:.1f}% > {s['max_position_pct']}%")
    if len(positions) > s['max_positions']:
        breaches.append(f"{len(positions)} positions > {s['max_positions']}")
    return breaches


def _returns(closes):
    return np.log(closes / closes.shift(1)).dropna()


def portfolio_metrics(weights, closes, bench, window=60):
    """
    weights: {ticker: weight of equity}; closes: DataFrame of closes (columns tickers); bench: benchmark closes.
    Annualised volatility, beta, correlations and downside deviation of the CURRENT weights over `window` sessions.
    """
    tickers = [t for t in weights if t in closes]
    if not tickers:
        return {'status': 'DATA UNAVAILABLE', 'reason': 'no price history for the holdings'}
    r = _returns(closes[tickers]).iloc[-window:]
    if len(r) < window // 2:
        return {'status': 'DATA UNAVAILABLE', 'reason': f'only {len(r)} common daily returns'}
    w = np.array([weights[t] for t in tickers])
    port = r.to_numpy() @ w
    out = {'status': 'OK', 'n_returns': len(r),
           'volatility_ann_pct': round(float(np.std(port, ddof=1) * math.sqrt(252) * 100), 2),
           'downside_dev_ann_pct': round(float(np.sqrt(np.mean(np.minimum(port, 0) ** 2)) * math.sqrt(252) * 100), 2)}
    if bench is not None:
        b = _returns(bench).reindex(r.index).to_numpy()
        ok = ~np.isnan(b)
        if ok.sum() >= window // 2 and np.var(b[ok], ddof=1) > 0:
            out['beta'] = round(float(np.cov(port[ok], b[ok], ddof=1)[0, 1] / np.var(b[ok], ddof=1)), 3)
    if len(tickers) >= 2:
        c = r.corr().to_numpy()
        off = c[~np.eye(len(tickers), dtype=bool)]
        out['mean_pairwise_correlation'] = round(float(np.nanmean(off)), 3)
        out['max_pairwise_correlation'] = round(float(np.nanmax(off)), 3)
    return out


def drawdown_stats(equity_curve):
    """{'current_drawdown_pct', 'max_drawdown_pct'} of an equity series."""
    e = pd.Series(equity_curve, dtype=float)
    if e.empty:
        return {'current_drawdown_pct': None, 'max_drawdown_pct': None}
    dd = e / e.cummax() - 1
    return {'current_drawdown_pct': round(float(dd.iloc[-1]) * 100, 2), 'max_drawdown_pct': round(float(dd.min()) * 100, 2)}


def days_to_exit(shares, adv_shares, s):
    """Sessions needed to sell `shares` at the participation limit (None without volume)."""
    if not adv_shares:
        return None
    return round(shares / (adv_shares * s['max_adv_participation_pct'] / 100), 2)
