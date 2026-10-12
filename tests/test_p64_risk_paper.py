"""
Master mission P4: risk engine, append-only journals and the paper simulator.

Prices, records and corporate actions below are SYNTHETIC (logic tests only; the simulator writes to the temporary
reports folder of the test).
"""

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

S = {'target_risk_pct': 1.0, 'max_risk_pct': 2.0, 'max_position_pct': 20.0, 'max_gross_exposure_pct': 100.0,
     'max_sector_pct': 40.0, 'max_positions': 10, 'max_adv_participation_pct': 1.0, 'min_avg_dollar_volume': 1e6,
     'stop_atr_multiple': 2.0, 'commission_bps': 1.0, 'slippage_bps': 5.0, 'half_spread_bps': 2.0, 'metrics_window': 60}


# ---------------------------------------------------------------- risk engine

def test_position_sizing_rules():
    from src.risk import size_position
    r = size_position(100_000, 100_000, 100.0, 95.0, 1_000_000, S)
    per_share = 5 + 2 * 100 * 8 / 1e4                                   # risk + round-trip costs
    assert r['accepted'] and r['shares'] == int(1000 // per_share)
    assert r['planned_loss'] <= 1000 and r['position_risk_pct'] <= 1.0
    assert r['notional_pct'] == pytest.approx(r['shares'] * 100 / 1000)  # risk is not the capital invested
    tight = size_position(100_000, 100_000, 100.0, 99.0, 1_000_000, S)
    assert tight['shares'] == 200 and 'max_position_pct' in tight['binding']
    thin = size_position(100_000, 100_000, 100.0, 95.0, 15_000, S)
    assert thin['shares'] == 150 and 'max_adv_participation_pct' in thin['binding']
    assert not size_position(100_000, 100_000, 100.0, 95.0, 5_000, S)['accepted']          # < 1 M USD traded
    assert not size_position(100_000, 100_000, 100.0, 101.0, 1e6, S)['accepted']           # stop above entry
    hard = size_position(100_000, 100_000, 100.0, 95.0, 1e6, dict(S, target_risk_pct=3.0, max_position_pct=100))
    assert not hard['accepted'] and 'hard limit' in hard['reasons'][0]
    assert size_position(100_000, 500.0, 100.0, 95.0, 1e6, S)['shares'] == 4                # cash binds


def test_portfolio_checks_and_metrics():
    from src.risk import check_portfolio, drawdown_stats, portfolio_metrics
    breaches = check_portfolio({'A': 30_000, 'B': 25_000, 'C': 60_000}, 100_000, {'A': 'x', 'B': 'x', 'C': 'y'}, S)
    assert any(b.startswith('gross exposure') for b in breaches)
    assert any(b.startswith('sector x') for b in breaches) and any(b.startswith('position C') for b in breaches)
    idx = pd.bdate_range('2026-01-01', periods=80)
    rng = np.random.default_rng(1)
    m = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 80))), index=idx)
    closes = pd.DataFrame({'A': m ** 2 / 100, 'B': m})
    out = portfolio_metrics({'A': 0.5, 'B': 0.5}, closes, m)
    assert out['beta'] == pytest.approx(1.5, abs=0.05) and out['mean_pairwise_correlation'] > 0.9
    assert drawdown_stats([100, 120, 90, 110]) == {'current_drawdown_pct': -8.33, 'max_drawdown_pct': -25.0}


# ---------------------------------------------------------------- journals

def test_journal_chain_and_tamper_detection():
    from src.journal import Journal
    j = Journal('transactions')
    j.append([{'type': 'start', 'capital': 1.0}, {'type': 'mark', 'equity': 1.0}])
    assert j.verify() == {'n': 2, 'ok': True, 'problem': None, 'head': j.entries()[-1]['hash']}
    lines = j.path.read_text().splitlines()
    first = json.loads(lines[0])
    first['capital'] = 2.0                                               # rewritten history
    j.path.write_text('\n'.join([json.dumps(first)] + lines[1:]) + '\n')
    assert not j.verify()['ok']
    with pytest.raises(RuntimeError, match='hash chain broken'):
        j.append([{'type': 'mark', 'equity': 3.0}])


# ---------------------------------------------------------------- paper simulator

TICKERS = [f'T{i:02d}' for i in range(12)]
S0 = '2026-03-06'                                                         # a Friday


def bars(base, n=60, end='2026-03-13', open_gap=None, low_override=None):
    idx = pd.bdate_range(end=end, periods=n)
    close = pd.Series(base + np.arange(n) * 0.1, index=idx)
    f = pd.DataFrame({'close_raw': close, 'open_raw': close - 0.05, 'high_raw': close + 1.0, 'low_raw': close - 1.0,
                      'volume': 2_000_000.0})
    f['close'], f['open'], f['high'], f['low'] = f['close_raw'], f['open_raw'], f['high_raw'], f['low_raw']
    for day, value in (open_gap or {}).items():
        f.loc[pd.Timestamp(day), 'open_raw'] = value
    for day, value in (low_override or {}).items():
        f.loc[pd.Timestamp(day), 'low_raw'] = value
    return f


class Feed:
    def __init__(self, frames):
        self.frames = frames

    def get(self, t):
        f = self.frames.get(t)
        if f is None:
            return {'status': 'DATA UNAVAILABLE', 'frame': None, 'close': None, 'reason': 'none'}
        return {'status': 'OK', 'frame': f, 'close': f['close'], 'reason': None}


def record(base):
    from src import prospective as p
    from tests.test_p50_prospective import craft
    scores = {t: 50.0 + i for i, t in enumerate(TICKERS)}                 # T11 best
    path = craft(p, S0, '2026-03-07T12:00:00+00:00', scores)
    rec = json.loads(path.read_text())
    rec['signal_instant'] = f'{S0}T21:00:00+00:00'
    return rec


@pytest.fixture
def market():
    frames = {t: bars(100.0 + i) for i, t in enumerate(TICKERS)}
    frames['SPY'] = bars(400.0)
    # T11 (rank 1) gaps down through its stop on Tuesday 2026-03-10; T10 pays a dividend on Wednesday;
    # T09 splits 2:1 on Thursday 2026-03-12 (Yahoo bars before the split are already halved, as Yahoo does)
    frames['T11'] = bars(111.0, open_gap={'2026-03-10': 90.0}, low_override={'2026-03-10': 89.0})
    f = bars(218.0)
    f.loc[f.index < pd.Timestamp('2026-03-12'), ['close_raw', 'open_raw', 'high_raw', 'low_raw']] /= 2
    frames['T09'] = f
    actions = {t: {'splits': {}, 'dividends': {}} for t in TICKERS}
    actions['T10']['dividends'] = {'2026-03-11': 1.5}
    actions['T09']['splits'] = {'2026-03-12': 2.0}
    return frames, actions


def make_paper(frames, actions, monkeypatch):
    from src import paper as P
    monkeypatch.setattr(P.Paper, '_sector', lambda self, t: f'SIC {int(t[1:]) % 4}')
    cfg = {'risk': S, 'paper': {'initial_capital': 100_000, 'top_n': 3, 'min_scored': 10}}
    return P.Paper(price_feed=Feed(frames), config=cfg, actions=actions)


def test_paper_cycle_fills_stops_dividends_splits(market, monkeypatch):
    frames, actions = market
    record(None)
    paper = make_paper(frames, actions, monkeypatch)
    out = paper.rebalance(now='2026-03-07T20:00:00+00:00')
    assert out['status'] == 'ORDERS' and 'T11, T10, T09' in out['message']
    assert paper.rebalance(now='2026-03-07T21:00:00+00:00')['status'] == 'UP TO DATE'
    preds = [e for e in paper.pred.entries() if e['type'] == 'prediction']
    assert len(preds) == 12 and preds[0]['expected_outcome'].startswith('no directional claim')
    res = paper.update(now='2026-03-14T12:00:00+00:00')
    assert res['status'] == 'OK' and '5 session(s) processed (2026-03-09 to 2026-03-13)' in res['message']
    tx = paper.tx.entries()
    fills = {e['ticker']: e for e in tx if e['type'] == 'fill'}
    t11 = fills['T11']
    assert t11['session'] == '2026-03-09'                                 # Monday open: first open after the order
    monday_open = frames['T11'].loc[pd.Timestamp('2026-03-09'), 'open_raw']
    assert t11['price'] == pytest.approx(monday_open * (1 + 7e-4))        # slippage + half-spread
    assert t11['position_risk_pct'] <= 1.0 and t11['stop'] < t11['price']
    t09 = fills['T09']
    assert t09['open'] == pytest.approx(frames['T09'].loc[pd.Timestamp('2026-03-09'), 'open_raw'] * 2)   # as traded
    stop = next(e for e in tx if e['type'] == 'stop_exit')
    assert stop['ticker'] == 'T11' and stop['session'] == '2026-03-10' and stop['gap_through_stop']
    assert stop['price'] == pytest.approx(90.0 * (1 - 7e-4))              # filled at the gapped open, below the stop
    div = next(e for e in tx if e['type'] == 'dividend')
    assert div['ticker'] == 'T10' and div['amount'] == pytest.approx(1.5 * fills['T10']['shares'])
    split = next(e for e in tx if e['type'] == 'split')
    assert split['ticker'] == 'T09' and split['shares_after'] == 2 * t09['shares']
    marks = [e for e in tx if e['type'] == 'mark']
    last = marks[-1]
    assert last['equity'] == pytest.approx(last['cash'] + last['positions_value'], abs=0.02)
    value = sum(p['shares'] * p['close'] for p in last['positions'].values())
    assert last['positions_value'] == pytest.approx(value, abs=0.02)
    assert set(last['positions']) == {'T10', 'T09'} and last['bench_state']['spy_return_pct'] is not None
    assert paper.tx.verify()['ok'] and paper.update(now='2026-03-14T13:00:00+00:00')['message'].startswith('0 session')
    st = paper.status()
    assert st['stops'] == 1 and st['risk_score'].startswith('NOT IMPLEMENTED') and st['sharpe'] is None


def test_paper_refuses_a_record_after_the_entry_open(market, monkeypatch):
    frames, actions = market
    record(None)
    paper = make_paper(frames, actions, monkeypatch)
    out = paper.rebalance(now='2026-03-09T14:00:00+00:00')                # Monday after the open
    assert out['status'] == 'TOO LATE'
    assert [e['type'] for e in paper.tx.entries()] == ['start']
