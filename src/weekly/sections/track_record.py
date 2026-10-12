#!/usr/bin/env python3
"""
Weekly report section 'track_record' - report part 21 "Prediction history and performance" (master mission P5)

Everything is read as known at the cutoff (entries and files whose own timestamp is <= T_c):
  predictions   reports/paper/predictions.jsonl: predictions with timestamp <= T_c, outcomes recorded <= T_c, and
                the mean realised return of the top 8 vs the other scored tickers per horizon (descriptive)
  paper PT1     reports/paper/transactions.jsonl: the latest 'mark' created <= T_c: equity, total return, drawdown,
                benchmarks (SPY, equal-weight universe), positions, stops, costs; interim and descriptive
  PT1 risk      at that mark (report part 18): volatility, downside deviation, beta vs SPY and pairwise correlations of
                the current weights over the risk window (src/risk.py, adjusted closes up to the mark session), largest
                position and sector (SEC SIC major group recorded at the fill) shares, and days to exit at the
                participation limit (20-session mean volume); no global risk score (NOT IMPLEMENTED)
  backtest      reports/history/heuristic_evaluation_<stamp>.json computed <= T_c (python main.py evaluate-heuristic):
                descriptive metrics on the walk-forward sample, always shown apart from the prospective figures
The pre-registered tests are in docs/research (stage 3, PT1); nothing here is a test. Kind: system_output.
Sections never write files.
"""

import json

import pandas as pd

from ...common import history_dir, stamp, to_utc_iso
from ...journal import Journal
from ...paper_report import CALIBRATION_STATUS, backtest_vs_paper, known_at, outcomes_by_horizon, performance, trades
from ...risk import RISK_SCORE_STATUS, days_to_exit, portfolio_metrics, settings
from ..core import SectionResult, conclude, evidence, unavailable
from .market import prices_aligned

NAME = 'track_record'
QUESTIONS = [11]
TOP_N = 8


def _item(tm, fact, when):
    return evidence(tm, 'this system', None, fact, as_of=when[:10], published_at=when, basis='journal / file timestamp')


def _predictions(ctx, res, base):
    tm = ctx.tm
    entries = Journal('predictions', base).entries()
    preds = {e['id']: e for e in entries if e['type'] == 'prediction' and to_utc_iso(e['timestamp']) <= tm.cutoff}
    outs = [e for e in entries if e['type'] == 'outcome' and e['prediction_id'] in preds
            and to_utc_iso(e['recorded_at']) <= tm.cutoff]
    if not preds:
        res.add(unavailable('overall', 11, 'prediction journal',
                            'no prediction recorded at or before the cutoff (journal started 2026-10-12)'))
        return
    by_h = outcomes_by_horizon(list(preds.values()) + outs, TOP_N)
    rows = [[f'{h} sessions', by_h[h]['outcomes'] if h in by_h else 0,
             by_h.get(h, {}).get('mean_top_pct'), by_h.get(h, {}).get('mean_others_pct'),
             by_h.get(h, {}).get('positive_share_pct'), by_h.get(h, {}).get('mean_weekly_ic'),
             by_h.get(h, {}).get('ic_weeks', 0)] for h in (20, 5)]
    weeks = sorted({p['signal_instant'][:10] for p in preds.values()})
    res.table('Prediction journal — realised outcomes known at the cutoff (descriptive)',
              ['horizon', 'outcomes', f'mean return of the top {TOP_N} (%)', 'mean return of the others (%)',
               'positive returns (%)', 'mean weekly rank correlation score / return', 'weeks with a correlation'],
              rows, question=11, note='Predictions are never edited; outcomes are separate entries. No test: the '
                                      'stage 3 pre-registration decides when a test is run. Calibration: '
                                      + CALIBRATION_STATUS + '.')
    last = max(to_utc_iso(p['timestamp']) for p in preds.values())
    res.add(conclude('overall', 11, f'Prediction journal at the cutoff: {len(preds)} prediction(s) over {len(weeks)} '
                                    f'week(s) (first {weeks[0]}), {len(outs)} realised outcome(s) recorded.',
                     [_item(tm, f'{len(preds)} predictions', last)], 'system_output'))


def _paper(ctx, res, base):
    tm = ctx.tm
    entries = Journal('transactions', base).entries()
    start = next((e for e in entries if e['type'] == 'start'), None)
    marks = [e for e in entries if e['type'] == 'mark' and to_utc_iso(e['created_at']) <= tm.cutoff]
    if start is None:
        res.add(unavailable('overall', 11, 'paper strategy PT1', 'not started'))
        return
    if not marks:
        pending = sum(1 for e in entries if e['type'] == 'order' and to_utc_iso(e['created_at']) <= tm.cutoff)
        res.add(unavailable('overall', 11, 'paper strategy PT1 performance',
                            f'no portfolio mark at or before the cutoff ({pending} order(s) placed; the first fills '
                            'happen at the next session open)'))
        return
    m = marks[-1]
    capital = start['capital']
    eqs = [x['equity'] for x in marks]
    peak, mdd = eqs[0], 0.0
    for v in eqs:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    stops = sum(1 for e in entries if e['type'] == 'stop_exit' and e['session'] <= m['session'])
    costs = sum(e.get('costs', 0) for e in entries if e['type'] in ('fill', 'stop_exit') and e['session'] <= m['session'])
    bench = m.get('bench_state') or {}
    total = (m['equity'] / capital - 1) * 100
    res.table('Paper strategy PT1 — interim, descriptive (prospective, paper only)',
              ['measure', 'value'], [['first mark', marks[0]['session']], ['last mark', m['session']],
                                     ['equity (USD)', m['equity']], ['total return (%)', round(total, 3)],
                                     ['SPY total return since start (%)', bench.get('spy_return_pct')],
                                     ['equal-weight universe since start (%)', bench.get('ew_return_pct')],
                                     ['maximum drawdown (%)', round(mdd * 100, 3)], ['stops', stops],
                                     ['costs paid (USD)', round(costs, 2)], ['gross exposure (%)', m['gross_exposure_pct']],
                                     ['positions', ', '.join(sorted(m['positions'])) or 'none']],
              question=11, note='docs/research/PAPER_STRATEGY_PT1.md. The pre-registered evaluation needs at least 52 '
                                'weekly rebalances; interim figures are descriptive and say nothing about an edge.')
    res.add(conclude('overall', 11, f"Paper strategy PT1 (paper only) at the mark of {m['session']}: equity "
                                    f"{m['equity']:,.2f} USD ({total:+.2f}% since the start; SPY "
                                    f"{bench.get('spy_return_pct')}%, equal-weight universe {bench.get('ew_return_pct')}%), "
                                    f'maximum drawdown {mdd * 100:.2f}%, {stops} stop(s). Interim and descriptive.',
                     [_item(tm, f"PT1 mark {m['session']}", to_utc_iso(m['created_at']))], 'system_output'))
    _paper_risk(ctx, res, m, entries)
    known = known_at(entries, tm.cutoff)
    rows = [[p['ticker'], p['entry_session'], p['entry_price'], p['shares'], p['stop'], p['exit_session'],
             p['exit_type'] or 'open', p['exit_price'], p['pnl'], p['pnl_kind'], p['return_pct'], p['holding_sessions'],
             p['worst_drawdown_pct']] for p in trades(known)]
    res.table(f"Paper strategy PT1 — positions and trades known at the cutoff", [
        'ticker', 'entry session', 'fill price', 'shares', 'stop', 'exit session', 'exit', 'exit / last price',
        'P&L (USD)', 'P&L kind', 'return vs cost basis (%)', 'sessions held', 'worst position value vs cost (%)'], rows,
        question=11, note='Fill prices are as-traded opens adjusted for slippage and spread; cost basis includes '
                          'commission. Worst position value vs cost uses the daily marks (close x shares, split-invariant; '
                          'intraday lows are not marked). A stop does not guarantee its price: a gap fills at the open.')
    rebalances = sum(1 for e in known if e['type'] == 'rebalance')
    ev = _evaluation_known(tm)
    res.table('Descriptive backtest beside the prospective paper results (not comparable yet)',
              ['measure', 'backtest: heuristic, walk-forward (descriptive)', 'paper PT1 (prospective, known at T_c)'],
              backtest_vs_paper(ev, performance(marks, capital), rebalances), question=11,
              note='The backtest is in-sample of one run of a heuristic whose weights were never fitted; the paper '
                   'record is prospective. Differences are expected from the selection (top quintile vs top 8), '
                   'sizing, costs and sample length; the pre-registered PT1 evaluation needs 52 weekly rebalances.')


def _closes_to(ctx, ticker, session):
    p = prices_aligned(ctx, ticker)
    if p['status'] != 'OK':
        return None
    f = p['frame']
    return f[[d <= session for d in f.index]]


def _paper_risk(ctx, res, m, entries):
    """Risk of the PT1 holdings at mark m (prices up to the mark session only)."""
    if not m['positions']:
        return
    s, _ = settings(getattr(ctx, 'config', None))
    bench = (getattr(ctx, 'weekly', None) or {}).get('benchmark', 'SPY')
    weights = {t: h['shares'] * h['close'] / m['equity'] for t, h in m['positions'].items()}
    closes, exits, missing = {}, {}, []
    for t, h in m['positions'].items():
        f = _closes_to(ctx, t, m['session'])
        if f is None or f['close'].dropna().empty:
            missing.append(t)
            continue
        closes[t] = f['close']
        vol = f['volume'].dropna().iloc[-20:]
        exits[t] = days_to_exit(h['shares'], float(vol.mean()) if len(vol) else None, s)
    b = _closes_to(ctx, bench, m['session'])
    metrics = portfolio_metrics(weights, pd.DataFrame(closes), None if b is None else b['close'], s['metrics_window'])
    sectors = {}
    for e in entries:
        if e['type'] == 'fill' and e['side'] == 'buy' and e['session'] <= m['session']:
            sectors[e['ticker']] = e.get('sector') or 'unknown'
    by_sector = {}
    for t, w in weights.items():
        by_sector[sectors.get(t, 'unknown')] = by_sector.get(sectors.get(t, 'unknown'), 0) + w
    top_t = max(weights, key=weights.get)
    top_s = max(by_sector, key=by_sector.get)
    known_exits = {t: d for t, d in exits.items() if d is not None}
    slow = max(known_exits, key=known_exits.get) if known_exits else None
    ok = metrics.get('status') == 'OK'
    rows = [['annualised volatility (%)', metrics.get('volatility_ann_pct') if ok else metrics.get('reason')],
            ['annualised downside deviation (%)', metrics.get('downside_dev_ann_pct')],
            [f'beta vs {bench}', metrics.get('beta')],
            ['mean / max pairwise correlation', f"{metrics.get('mean_pairwise_correlation')} / "
                                                f"{metrics.get('max_pairwise_correlation')}" if ok else None],
            ['largest position (% of equity)', f'{top_t} {weights[top_t] * 100:.2f}'],
            ['largest sector, SIC major group (% of equity)', f'{top_s} {by_sector[top_s] * 100:.2f}'],
            ['longest exit (sessions at the participation limit)', f'{slow} {known_exits[slow]}' if slow else None],
            ['holdings without price history', ', '.join(missing) or 'none'],
            ['global risk score', RISK_SCORE_STATUS]]
    res.table(f"Paper strategy PT1 — portfolio risk at the mark of {m['session']} (paper only)", ['measure', 'value'],
              rows, question=11, note=f"src/risk.py over {s['metrics_window']} sessions of adjusted closes up to the "
                                      'mark session; limits from config risk (max position '
                                      f"{s['max_position_pct']}%, max sector {s['max_sector_pct']}%). Volume is "
                                      'split-adjusted while shares are as traded: days to exit are approximate around '
                                      'a split. Descriptive; no limit here is a forecast of loss.')
    if not ok:
        res.add(unavailable('overall', 11, 'PT1 portfolio risk metrics', metrics.get('reason')))


def _evaluation_known(tm):
    """The latest heuristic evaluation history file computed at or before T_c, or None."""
    cut = stamp(tm.cutoff)
    files = [p for p in sorted(history_dir().glob('heuristic_evaluation_*.json')) if p.stem.split('_', 2)[-1] <= cut]
    return json.loads(files[-1].read_text(encoding='utf-8')) if files else None


def _backtest(ctx, res):
    tm = ctx.tm
    cut = stamp(tm.cutoff)
    files = [p for p in sorted(history_dir().glob('heuristic_evaluation_*.json')) if p.stem.split('_', 2)[-1] <= cut]
    if not files:
        res.add(unavailable('overall', 11, 'descriptive backtest of the heuristic',
                            'no heuristic evaluation computed at or before the cutoff (python main.py evaluate-heuristic)'))
        return
    ev = json.loads(files[-1].read_text(encoding='utf-8'))
    rows = []
    for h, m in ev['horizons'].items():
        p = m['portfolios']
        rows.append([h, p['long_only_top_quintile_net'].get('sharpe'), p['benchmark_equal_weight_universe'].get('sharpe'),
                     (p.get('benchmark_spy') or {}).get('sharpe'),
                     p['long_only_net_minus_equal_weight'].get('annualised_return_pct'),
                     m['classification']['beats_cross_sectional_median']['auc_combined_score']])
    res.table(f"Backtest-style descriptive metrics (walk-forward sample, computed {ev['computed_at']})",
              ['horizon', 'top quintile net Sharpe', 'equal-weight Sharpe', 'SPY Sharpe',
               'top quintile minus equal weight (% a year)', 'AUC vs median'], rows, question=11,
              note=ev['nature'] + '. Shown apart from the prospective figures above.')
    res.add(conclude('overall', 11, f"Descriptive backtest of the heuristic (computed {ev['computed_at']}): "
                                    + '; '.join(f'{r[0]}: top quintile net Sharpe {r[1]} vs equal weight {r[2]}, '
                                                f'AUC {r[5]}' for r in rows) + '. Descriptive, in-sample of one run.',
                     [_item(tm, 'heuristic evaluation', to_utc_iso(ev['computed_at']))], 'system_output'))


def build(ctx, base=None):
    res = SectionResult(NAME, QUESTIONS)
    _predictions(ctx, res, base)
    _paper(ctx, res, base)
    _backtest(ctx, res)
    return res
