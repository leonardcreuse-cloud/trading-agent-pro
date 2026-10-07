#!/usr/bin/env python3
"""
Continuous features (phase P1.3) - point-in-time inputs for the fitted model

Every feature is computed from data available at the evaluation instant T only:
closes up to T, SEC XBRL facts accepted by T, Form 4 filings in (T - 90 d, T].
A feature that cannot be computed is None (never a placeholder); the model decides how
missing values enter the fit (see model.py).

Price (sessions, adjusted closes):
  mom_1m, mom_3m, mom_6m   return over the last 21 / 63 / 126 sessions
  mom_12_1                 return from 252 to 21 sessions ago (skips the last month)
  vol_3m                   annualised std of daily log returns over 63 sessions
  dist_high_1y             close / max close of the last 252 sessions - 1  (<= 0)
Fundamentals (SEC XBRL):
  revenue_growth           YoY TTM revenue growth (%)
  log_revenue              log10 TTM revenue (USD)
  debt_to_equity           debt / stockholders' equity
Insider (Form 4, open-market only):
  insider_buyers           distinct insiders with purchases
  insider_sell_log         log10(1 + open-market sale value, USD)
  insider_disc_sell_log    log10(1 + discretionary sale value, USD) (not under 10b5-1)
"""

import math

import numpy as np

PRICE_FEATURES = ('mom_1m', 'mom_3m', 'mom_6m', 'mom_12_1', 'vol_3m', 'dist_high_1y')
FUNDAMENTAL_FEATURES = ('revenue_growth', 'log_revenue', 'debt_to_equity')
INSIDER_FEATURES = ('insider_buyers', 'insider_sell_log', 'insider_disc_sell_log')
FEATURES = PRICE_FEATURES + FUNDAMENTAL_FEATURES + INSIDER_FEATURES


def _ret(values, back, skip=0):
    if len(values) <= back:
        return None
    start, end = values[-1 - back], values[-1 - skip]
    return float(end / start - 1) if start > 0 else None


def price_features(values):
    values = np.asarray(values, dtype=float)
    out = {'mom_1m': _ret(values, 21), 'mom_3m': _ret(values, 63), 'mom_6m': _ret(values, 126),
           'mom_12_1': _ret(values, 252, skip=21), 'vol_3m': None, 'dist_high_1y': None}
    if len(values) > 63:
        daily = np.diff(np.log(values[-64:]))
        out['vol_3m'] = float(daily.std(ddof=1) * math.sqrt(252))
    if len(values) >= 252:
        out['dist_high_1y'] = float(values[-1] / values[-252:].max() - 1)
    return out


def fundamental_features(fin):
    fin = fin or {}
    revenue = fin.get('revenue')
    return {'revenue_growth': fin.get('revenue_growth_pct'),
            'log_revenue': math.log10(revenue) if revenue and revenue > 0 else None,
            'debt_to_equity': fin.get('debt_to_equity')}


def insider_features(summary):
    if summary is None:
        return dict.fromkeys(INSIDER_FEATURES)
    return {'insider_buyers': float(summary['distinct_buyers']),
            'insider_sell_log': math.log10(1 + summary['sell_value_usd']),
            'insider_disc_sell_log': math.log10(1 + summary['discretionary_sell_value_usd'])}


def feature_vector(values, fin, insider_summary):
    """All features at T (dict name -> float or None)."""
    out = {**price_features(values), **fundamental_features(fin), **insider_features(insider_summary)}
    return {k: (None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(v, 6))
            for k, v in out.items()}
