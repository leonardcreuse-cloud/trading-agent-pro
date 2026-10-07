#!/usr/bin/env python3
"""
Pre-registered hypotheses (phase P2.1) - written BEFORE any result of the expanded study.

Each feature has a group, an expected sign (direction in which it should rank future
returns according to published research, not according to this data) and its basis.
Group composites average the signed cross-sectional ranks of their features, so a group is
tested in the direction stated here; a result in the opposite direction is reported as such,
never silently flipped.

Groups tested in stage 1: momentum, market structure, quality, growth, value, sector.
Not testable with free point-in-time data (reported as DATA UNAVAILABLE):
  analyst revisions (estimate / target-price history), guidance changes.
Deferred: insider (stage 2, Form 4 history), macro (time-series design: macro variables are
identical for all stocks on a date, so they cannot rank stocks), events.
"""

FEATURES = {
    # ---------------------------------------------------------------- momentum
    'mom_1m': ('momentum', -1, 'short-term reversal (Jegadeesh 1990)'),
    'mom_3m': ('momentum', +1, 'intermediate momentum (Jegadeesh & Titman 1993)'),
    'mom_6m': ('momentum', +1, 'momentum (Jegadeesh & Titman 1993)'),
    'mom_12_1': ('momentum', +1, '12-1 month momentum (Carhart 1997)'),
    'risk_adj_mom': ('momentum', +1, 'volatility-scaled momentum (Barroso & Santa-Clara 2015)'),
    # ---------------------------------------------------------------- market structure
    'vol_3m': ('market_structure', -1, 'low-volatility anomaly (Ang et al. 2006)'),
    'beta_1y': ('market_structure', -1, 'betting against beta (Frazzini & Pedersen 2014)'),
    'idio_vol_1y': ('market_structure', -1, 'idiosyncratic volatility puzzle (Ang et al. 2006)'),
    'log_dollar_volume': ('market_structure', -1, 'illiquidity premium (Amihud 2002)'),
    'volume_trend': ('market_structure', -1, 'high turnover, lower returns (Lee & Swaminathan 2000)'),
    'dist_high_1y': ('market_structure', +1, '52-week-high momentum (George & Hwang 2004)'),
    'log_market_cap': ('market_structure', -1, 'size effect (Banz 1981; Fama & French 1993)'),
    # ---------------------------------------------------------------- quality
    'gross_profitability': ('quality', +1, 'gross profits / assets (Novy-Marx 2013)'),
    'operating_margin': ('quality', +1, 'profitability (Fama & French 2015, RMW)'),
    'roe': ('quality', +1, 'return on equity (Fama & French 2015; Hou, Xue & Zhang 2015)'),
    'roa': ('quality', +1, 'return on assets (Haugen & Baker 1996)'),
    'fcf_margin': ('quality', +1, 'cash profitability (Ball et al. 2016)'),
    'accruals': ('quality', -1, 'accrual anomaly (Sloan 1996)'),
    'debt_to_equity': ('quality', -1, 'balance-sheet quality (Asness, Frazzini & Pedersen 2019)'),
    # ---------------------------------------------------------------- growth
    'revenue_growth': ('growth', +1, 'sales growth persistence (hypothesis; evidence mixed)'),
    'eps_growth': ('growth', +1, 'earnings momentum (Chan, Jegadeesh & Lakonishok 1996)'),
    'fcf_growth': ('growth', +1, 'cash-flow growth (hypothesis)'),
    'asset_growth': ('growth', -1, 'asset growth anomaly (Cooper, Gulen & Schill 2008)'),
    # ---------------------------------------------------------------- value
    'earnings_yield': ('value', +1, 'E/P (Basu 1977)'),
    'sales_to_ev': ('value', +1, 'EV/sales, inverted (value; Loughran & Wellman 2011 for EBITDA/EV)'),
    'fcf_yield': ('value', +1, 'cash-flow yield (Lakonishok, Shleifer & Vishny 1994)'),
    'ebitda_to_ev': ('value', +1, 'enterprise multiple, inverted (Loughran & Wellman 2011)'),
    'book_to_market': ('value', +1, 'B/M (Fama & French 1992)'),
    'earnings_yield_vs_sector': ('value', +1, 'within-industry value (Asness, Porter & Stevens 2000)'),
    # ---------------------------------------------------------------- sector
    'sector_mom_6m': ('sector', +1, 'industry momentum (Moskowitz & Grinblatt 1999)'),
    'mom_6m_vs_sector': ('sector', +1, 'within-industry momentum (Asness, Porter & Stevens 2000)'),
}

GROUPS = tuple(dict.fromkeys(g for g, _, _ in FEATURES.values()))
HORIZONS = (5, 20, 60, 120, 252)

UNAVAILABLE_GROUPS = {
    'analyst_revisions': 'no free point-in-time history of estimates or price targets',
    'guidance_changes': 'no free machine-readable guidance history',
    'insider': 'deferred to stage 2 (Form 4 history download)',
    'macro': 'time-series hypothesis: identical for all stocks on a date (separate design)',
    'events': 'deferred (earnings dates / 8-K items)',
}


def expected_sign(feature):
    return FEATURES[feature][1]


def group_features(group):
    return [f for f, (g, _, _) in FEATURES.items() if g == group]
