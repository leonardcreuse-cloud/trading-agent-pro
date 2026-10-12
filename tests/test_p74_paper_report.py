"""
Gap round G4: read-only paper trading and prediction reports (synthetic journal entries, logic only).
"""

ENTRIES = [
    {'type': 'start', 'capital': 100000.0, 'created_at': '2026-10-03T12:00:00+00:00'},
    {'type': 'order', 'id': 'o1', 'ticker': 'AAA', 'created_at': '2026-10-04T12:00:00+00:00'},
    {'type': 'order', 'id': 'o2', 'ticker': 'BBB', 'created_at': '2026-10-04T12:00:00+00:00'},
    {'type': 'fill', 'side': 'buy', 'ticker': 'AAA', 'session': '2026-10-05', 'price': 100.0, 'shares': 100,
     'cash_out': 10001.0, 'stop': 90.0, 'costs': 8.0},
    {'type': 'fill', 'side': 'buy', 'ticker': 'BBB', 'session': '2026-10-05', 'price': 50.0, 'shares': 200,
     'cash_out': 10002.0, 'stop': 45.0, 'costs': 9.0},
    {'type': 'mark', 'session': '2026-10-05', 'created_at': '2026-10-05T22:00:00+00:00', 'equity': 100000.0,
     'positions': {'AAA': {'shares': 100, 'close': 98.0}, 'BBB': {'shares': 200, 'close': 51.0}}},
    {'type': 'split', 'ticker': 'BBB', 'session': '2026-10-06', 'ratio': 2.0, 'shares_after': 400, 'stop_after': 22.5,
     'cost_after': 25.005},
    {'type': 'stop_exit', 'ticker': 'AAA', 'session': '2026-10-06', 'price': 89.5, 'realised_pnl': -1060.1,
     'cash_in': 8940.0, 'costs': 8.0, 'notional': 8950.0},
    {'type': 'mark', 'session': '2026-10-06', 'created_at': '2026-10-06T22:00:00+00:00', 'equity': 98900.0,
     'positions': {'BBB': {'shares': 400, 'close': 24.0}}},
    {'type': 'mark', 'session': '2026-10-07', 'created_at': '2026-10-12T22:00:00+00:00', 'equity': 99500.0,
     'positions': {'BBB': {'shares': 400, 'close': 26.0}}},
]


def test_trades_realised_unrealised_split_and_drawdown():
    from src.paper_report import trades
    by = {p['ticker']: p for p in trades(ENTRIES)}
    a, b = by['AAA'], by['BBB']
    assert a['exit_type'] == 'stop' and a['pnl'] == -1060.1 and a['pnl_kind'] == 'realised'
    assert a['holding_sessions'] == 1 and a['worst_drawdown_pct'] == round((98.0 / 100.01 - 1) * 100, 3)
    assert a['return_pct'] == round((89.5 / 100.01 - 1) * 100, 3)
    assert b['exit_type'] is None and b['shares'] == 400 and b['cost_per_share'] == 25.005     # split applied
    assert b['pnl'] == round((26.0 - 25.005) * 400, 2) and b['pnl_kind'] == 'unrealised'
    # split-invariant: position values 51 x 200, 24 x 400, 26 x 400 against the total cost 10,002
    assert b['holding_sessions'] == 3 and b['worst_drawdown_pct'] == round((24.0 * 400 / 10002.0 - 1) * 100, 3)


def test_entries_known_at_a_cutoff():
    from src.paper_report import known_at, trades
    known = known_at(ENTRIES, '2026-10-10T05:00:00+00:00')
    assert [e['type'] for e in known][-1] == 'mark' and len(known) == len(ENTRIES) - 1     # the 10-12 mark is later
    early = known_at(ENTRIES, '2026-10-05T23:00:00+00:00')
    assert {e['type'] for e in early} == {'start', 'order', 'fill', 'mark'}                # split / stop: next batch
    assert {p['ticker'] for p in trades(early) if p['exit_type'] is None} == {'AAA', 'BBB'}


def test_outcomes_by_horizon_and_rank_correlation():
    from src.paper_report import CALIBRATION_STATUS, outcomes_by_horizon
    preds, outs = [], []
    for i in range(12):
        preds.append({'type': 'prediction', 'id': f'p{i}', 'signal_instant': '2026-10-09T21:00:00+00:00',
                      'model_output': {'rank': i + 1, 'combined': 80.0 - i}})
        outs.append({'type': 'outcome', 'prediction_id': f'p{i}', 'horizon_sessions': 5,
                     'realised_return': 0.05 - 0.01 * i})                 # perfectly ordered by the score
    r = outcomes_by_horizon(preds + outs, top_n=8)[5]
    assert r['outcomes'] == 12 and r['weeks'] == 1 and r['ic_weeks'] == 1 and r['mean_weekly_ic'] == 1.0
    assert r['mean_top_pct'] == round(sum(0.05 - 0.01 * i for i in range(8)) / 8 * 100, 3)
    assert r['positive_share_pct'] == round(5 / 12 * 100, 1) and r['calibration'] == CALIBRATION_STATUS
    assert outcomes_by_horizon(preds) == {}


def test_backtest_vs_paper_rows():
    from src.paper_report import backtest_vs_paper, performance
    ev = {'sample': {'dates': 220, 'period': ['2022-05-12', '2026-09-24']}, 'costs': '10 bps',
          'horizons': {'5d': {'portfolios': {'long_only_top_quintile_net': {
              'annualised_return_pct': 26.0, 'annualised_vol_pct': 27.8, 'sharpe': 0.97, 'sortino': 0.94,
              'max_drawdown_pct': -27.3}}}}}
    marks = [m for m in ENTRIES if m['type'] == 'mark']
    perf = performance(marks, 100000.0)
    assert perf['total_return_pct'] == -0.5 and perf['max_drawdown_pct'] == -1.1 and perf['sharpe'] is None
    rows = {r[0]: r[1:] for r in backtest_vs_paper(ev, perf, 1)}
    assert rows['Sharpe'] == [0.97, None] and rows['annualised return %'][1] == 'fewer than 20 sessions'
    assert rows['comparable?'][1].startswith('no: fewer than 52')
    assert backtest_vs_paper(None, {'status': 'NO MARK'}, 0)[0][1] is None
