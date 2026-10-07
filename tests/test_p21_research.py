"""
Phase P2.1 - research study building blocks (offline). Synthetic data only checks logic.
"""

import math
from datetime import date, timedelta

import numpy as np
import pytest

from src.research.factors import FEATURES, GROUPS, HORIZONS


# ---------------------------------------------------------------- hypotheses

def test_every_feature_is_preregistered_with_sign_and_basis():
    for f, (group, sign, basis) in FEATURES.items():
        assert group in GROUPS and sign in (-1, 1) and len(basis) > 5
    assert HORIZONS == (5, 20, 60, 120, 252)


def test_universe_rule_excludes_financials_and_uses_date_added():
    from src.research.universe import Universe, member_at, parse_constituents
    text = ('Symbol,Security,GICS Sector,GICS Sub-Industry,Headquarters Location,Date added,CIK,Founded\n'
            'AAA,A,Information Technology,x,y,2015-01-02,1,1990\n'
            'BBB,B,Financials,x,y,2010-01-04,2,1990\n'
            'BF.B,C,Consumer Staples,x,y,,3,1990\n')
    rows = parse_constituents(text)
    u = Universe.__new__(Universe)
    u.rows = rows
    assert [r['ticker'] for r in u.eligible()] == ['AAA', 'BF.B']
    assert rows[2]['yahoo_ticker'] == 'BF-B' and rows[0]['cik'] == '0000000001'
    assert not member_at(rows[0], '2014-12-31') and member_at(rows[0], '2015-01-02')
    assert member_at(rows[2], '2000-01-01')          # unknown date added: assumed member
    assert [r['ticker'] for r in u.stage(1)] == [r['ticker'] for r in u.stage(1)]   # seeded


# ---------------------------------------------------------------- point in time

def fact(metric, as_of, value, published, start=None):
    return {'metric': metric, 'as_of_date': as_of, 'value': value, 'value_text': start,
            'published_at': published}


def test_point_in_time_replay_uses_only_published_versions():
    from src.research.panel import PointInTimeFacts
    pit = PointInTimeFacts([
        fact('xbrl:Assets', '2025-12-31', 100.0, '2026-02-20T21:00:00+00:00'),
        fact('xbrl:Assets', '2025-12-31', 110.0, '2026-05-01T21:00:00+00:00'),   # restated later
    ])
    assert pit.advance('2026-01-31T00:00:00+00:00').latest_instant('Assets') == (None, None)
    assert pit.advance('2026-03-01T00:00:00+00:00').latest_instant('Assets')[0] == 100.0
    assert pit.advance('2026-06-01T00:00:00+00:00').latest_instant('Assets')[0] == 110.0


def test_market_cap_converts_split_adjusted_price_to_reported_share_basis():
    from src.research.panel import fundamental_features, split_factor_after
    splits = [('2024-06-10', 10.0)]
    assert split_factor_after(splits, '2024-01-28') == 10.0
    assert split_factor_after(splits, '2024-07-28') == 1.0
    f = dict.fromkeys(['revenue', 'revenue_prior', 'net_income', 'operating_income', 'gross_profit',
                       'cfo', 'fcf', 'fcf_prior', 'da', 'eps', 'eps_prior', 'equity', 'debt', 'assets',
                       'assets_prior', 'cash'])
    # before the split: 2.46 B shares reported, true price 900 -> split-adjusted close 90
    f.update(shares=2.46e9, shares_as_of='2024-01-28', net_income=30e9, equity=43e9)
    feats = fundamental_features(f, 90.0, splits)
    assert feats['log_market_cap'] == pytest.approx(math.log10(900 * 2.46e9))
    assert feats['earnings_yield'] == pytest.approx(30e9 / (900 * 2.46e9))
    assert fundamental_features(f, 90.0, None)['log_market_cap'] is None     # no split history


def test_ratios_never_invent_values():
    from src.research.panel import fundamental_features
    f = dict.fromkeys(['revenue', 'revenue_prior', 'net_income', 'operating_income', 'gross_profit',
                       'cfo', 'fcf', 'fcf_prior', 'da', 'eps', 'eps_prior', 'equity', 'debt', 'assets',
                       'assets_prior', 'cash', 'shares', 'shares_as_of'])
    assert all(v is None for v in fundamental_features(f, 10.0, []).values())
    f.update(net_income=-5.0, equity=-1.0)
    assert fundamental_features(f, 10.0, [])['roe'] is None                 # negative equity


def test_price_features_ignore_future_prices():
    from src.research.panel import price_features
    rng = np.random.default_rng(0)
    adj = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))
    spy = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    vol = rng.uniform(1e6, 2e6, 400)
    base = price_features(adj, adj, vol, spy, 300)
    future = adj.copy()
    future[301:] *= 5
    assert price_features(future, future, vol, spy, 300) == base
    assert base['dist_high_1y'] <= 0 and base['vol_3m'] > 0


# ---------------------------------------------------------------- statistics

def test_newey_west_widens_standard_error_for_autocorrelated_series():
    from src.research.stats import newey_west
    rng = np.random.default_rng(1)
    noise = rng.normal(size=2000)
    ar = np.convolve(noise, np.ones(10) / 10, mode='valid')      # overlapping-window style
    _, se0, _ = newey_west(ar, 0)
    _, se9, _ = newey_west(ar, 9)
    assert se9 > 2 * se0


def test_benjamini_hochberg_known_values():
    from src.research.stats import benjamini_hochberg, correct
    q = benjamini_hochberg([0.01, 0.04, 0.03, 0.5])
    assert q == pytest.approx([0.04, 0.0533333, 0.0533333, 0.5])
    tests = correct([{'p_value': 0.01}, {'p_value': 0.06}, {'p_value': None}])   # m = 2
    assert tests[0]['significant_bh'] and not tests[1]['significant_bh']
    assert tests[0]['p_bonferroni'] == 0.02 and tests[2]['q_value_bh'] is None


def test_quintile_portfolio_costs_and_turnover():
    from src.research.stats import quintile_portfolios
    names = [f'T{i}' for i in range(20)]
    by_date = {'2024-01-05': [(t, i, 0.01 * i) for i, t in enumerate(names)],
               '2024-02-05': [(t, i, 0.01 * i) for i, t in enumerate(names)],
               '2024-03-05': [(t, -i, 0.01 * i) for i, t in enumerate(names)]}
    out = quintile_portfolios(by_date, sorted(by_date), horizon=20, cost_bps=10)
    gross = out['long_short_gross']
    assert gross['n_periods'] == 3
    # first rebalance: buy both legs (turnover 1 + 1); second: none; third: full flip (2 + 2)
    net = out['long_short_net']
    assert gross['mean_period_return_pct'] - net['mean_period_return_pct'] == pytest.approx(
        (0.002 + 0 + 0.004) / 3 * 100, abs=1e-4)


# ---------------------------------------------------------------- end to end on synthetic panels

def synthetic_rows(signal, n_stocks=40, n_weeks=520, seed=0):
    rng = np.random.default_rng(seed)
    start = date(2015, 1, 2)
    rows = []
    calendar = [(start + timedelta(weeks=w)).isoformat() for w in range(n_weeks)]
    for w, day in enumerate(calendar):
        for s in range(n_stocks):
            feats = dict.fromkeys(FEATURES)
            x = float(rng.normal())
            feats['mom_6m'] = x
            feats['vol_3m'] = float(rng.normal())
            row = {'ticker': f'S{s}', 'date': day, 'sector': f'sec{s % 4}', 'features': feats}
            for h in HORIZONS:
                row[f'fwd_{h}d'] = signal * x * math.sqrt(h / 5) + float(rng.normal()) * 0.03 * math.sqrt(h / 5)
                exit_week = w + 1 + math.ceil(h / 5)
                row[f'exit_{h}d'] = calendar[exit_week] if exit_week < n_weeks else None
                if row[f'exit_{h}d'] is None:
                    row[f'fwd_{h}d'] = None
            rows.append(row)
    return rows, calendar


def test_walk_forward_models_purge_and_detect_planted_signal():
    from src.research.experiment import add_composites, by_date, walk_forward_models
    rows, calendar = synthetic_rows(signal=0.01)
    add_composites(by_date(rows))
    res = walk_forward_models(rows, 20, calendar, None, ('logistic_l2',))['logistic_l2']
    assert res['folds']['2015']['status'].startswith('skipped')
    tested = [f for f in res['folds'].values() if f['status'] == 'tested']
    assert all(f['train_end'] < str(int(y)) for y, f in res['folds'].items() if f['status'] == 'tested')
    assert tested and res['ic']['mean'] > 0.1 and res['ic']['p_value'] < 0.001
    assert res['auc'] > 0.55


def test_composite_ic_finds_signal_and_rejects_noise():
    from src.research.experiment import add_composites, by_date, ic_test
    for signal, expect in ((0.01, True), (0.0, False)):
        rows, _ = synthetic_rows(signal=signal, n_weeks=260, seed=3)
        dates = by_date(rows)
        add_composites(dates)
        t = ic_test(dates, lambda r: r['composites']['momentum'], 5)
        assert (t['p_value'] < 0.001 and t['mean'] > 0) == expect
