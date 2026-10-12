#!/usr/bin/env python3
"""
Paper trading and prediction tracking reports (master mission 9, 10.3; gap round G4)

Read-only views of the hash-chained journals (src/journal.py); nothing here writes a journal entry or changes the
paper strategy PT1 (docs/research/PAPER_STRATEGY_PT1.md):

  trades(entries)              one row per position: entry (fill session, as-traded fill price, shares, cost basis
                               per share incl. commission), exit (stop or sell, price, session), realised P&L (as
                               journalled) or unrealised P&L at the last mark, holding sessions (marks while held),
                               and the worst drawdown while held = lowest marked position value (close x shares)
                               / total cost - 1 (split-invariant; daily marks: closes only, intraday lows are not
                               marked)
  outcomes_by_horizon(...)     per horizon: realised outcomes known so far, mean return of the top-N ranks vs the
                               others, share of positive returns, and the mean weekly Spearman rank correlation between
                               the score and the realised return (descriptive; the pre-registered stage 3 test is the
                               only test). Calibration: NOT CALIBRATED (no probability is predicted)
  backtest_vs_paper(...)       the descriptive walk-forward evaluation of the heuristic (top quintile, net of its
                               cost assumption) beside the prospective paper results, each with its sample size; the
                               two are not comparable until the paper record is long enough (52 weekly rebalances
                               pre-registered for PT1)
"""

import pandas as pd

CALIBRATION_STATUS = 'NOT CALIBRATED: the heuristic outputs a 0-100 score and a rank, never a probability'
MIN_PAPER_WEEKS = 52


def trades(entries):
    """[{...}] one per position (open positions last), from transaction-journal entries in journal order."""
    open_, done, marks = {}, [], [e for e in entries if e['type'] == 'mark']
    for e in entries:
        t = e['type']
        if t == 'fill' and e['side'] == 'buy':
            open_[e['ticker']] = {'ticker': e['ticker'], 'entry_session': e['session'], 'entry_price': e['price'],
                                  'shares': e['shares'], 'cost_per_share': e['cash_out'] / e['shares'],
                                  'cost_total': e['cash_out'],
                                  'stop': e['stop'], 'signal_timestamp': e.get('signal_timestamp'),
                                  'entry_costs': e['costs'], 'exit_session': None, 'exit_price': None,
                                  'exit_type': None, 'pnl': None, 'pnl_kind': None}
        elif t == 'split' and e['ticker'] in open_:
            p = open_[e['ticker']]
            p.update(shares=e['shares_after'], stop=e['stop_after'], cost_per_share=e['cost_after'])
        elif (t == 'stop_exit' or (t == 'fill' and e['side'] == 'sell')) and e['ticker'] in open_:
            p = open_.pop(e['ticker'])
            p.update(exit_session=e['session'], exit_price=e['price'], exit_type='stop' if t == 'stop_exit' else 'sell',
                     pnl=e.get('realised_pnl'), pnl_kind='realised')
            done.append(p)
    last = marks[-1] if marks else None
    for p in open_.values():
        held = (last or {}).get('positions', {}).get(p['ticker'])
        if held:
            p.update(pnl=round((held['close'] - p['cost_per_share']) * held['shares'], 2), pnl_kind='unrealised',
                     exit_price=held['close'])
        done.append(p)
    for p in done:
        # position value (close x shares held at that mark) against the total cost: unchanged by splits
        values = [m['positions'][p['ticker']]['close'] * m['positions'][p['ticker']]['shares'] for m in marks
                  if p['ticker'] in m.get('positions', {}) and m['session'] >= p['entry_session']
                  and (p['exit_session'] is None or m['session'] < p['exit_session'])]
        p['holding_sessions'] = len(values)
        p['worst_drawdown_pct'] = round((min(values) / p['cost_total'] - 1) * 100, 3) if values else None
        p['return_pct'] = (round((p['exit_price'] / p['cost_per_share'] - 1) * 100, 3)
                           if p['exit_price'] is not None else None)
    return done


def _spearman(a, b):
    ra, rb = pd.Series(a).rank(), pd.Series(b).rank()
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(ra.corr(rb))


def outcomes_by_horizon(pred_entries, top_n=8):
    """{horizon: {...}} from prediction-journal entries; only outcomes already recorded."""
    preds = {e['id']: e for e in pred_entries if e['type'] == 'prediction'}
    outs = [e for e in pred_entries if e['type'] == 'outcome' and e['prediction_id'] in preds]
    result = {}
    for h in sorted({o['horizon_sessions'] for o in outs}):
        rows = []
        for o in outs:
            if o['horizon_sessions'] != h:
                continue
            p = preds[o['prediction_id']]
            rows.append({'week': p['signal_instant'][:10], 'rank': p['model_output'].get('rank'),
                         'score': p['model_output'].get('combined'), 'ret': o['realised_return']})
        top = [r['ret'] for r in rows if r['rank'] is not None and r['rank'] <= top_n]
        rest = [r['ret'] for r in rows if r['rank'] is not None and r['rank'] > top_n]
        ics = []
        for week in sorted({r['week'] for r in rows}):
            w = [r for r in rows if r['week'] == week and r['score'] is not None]
            if len(w) >= 10:
                ic = _spearman([r['score'] for r in w], [r['ret'] for r in w])
                if ic is not None:
                    ics.append(ic)
        result[h] = {'outcomes': len(rows), 'weeks': len({r['week'] for r in rows}),
                     'mean_top_pct': round(sum(top) / len(top) * 100, 3) if top else None,
                     'mean_others_pct': round(sum(rest) / len(rest) * 100, 3) if rest else None,
                     'positive_share_pct': round(sum(r['ret'] > 0 for r in rows) / len(rows) * 100, 1) if rows else None,
                     'mean_weekly_ic': round(sum(ics) / len(ics), 4) if ics else None, 'ic_weeks': len(ics),
                     'calibration': CALIBRATION_STATUS}
    return result


def backtest_vs_paper(evaluation, status, rebalances):
    """Rows [measure, backtest (descriptive, walk-forward), paper PT1 (prospective)]; None where not available."""
    bt = ((evaluation or {}).get('horizons') or {}).get('5d', {}).get('portfolios', {}).get('long_only_top_quintile_net')
    ok = (status or {}).get('status') == 'OK'
    sessions = (status or {}).get('sessions') or 0
    paper_ann = None
    if ok and sessions >= 20:
        paper_ann = round(((1 + status['total_return_pct'] / 100) ** (252 / sessions) - 1) * 100, 2)
    rows = [
        ['sample', f"{(evaluation or {}).get('sample', {}).get('dates')} rebalance dates "
                   f"{(evaluation or {}).get('sample', {}).get('period')}" if bt else None,
         f'{rebalances} weekly rebalance(s), {sessions} marked session(s)' if ok else f'{rebalances} rebalance(s), no mark'],
        ['strategy', 'top quintile of the heuristic score, equal weight, rebalanced every 5 sessions' if bt else None,
         'top 8 of the stage 3 record, sized by the risk engine (PT1)'],
        ['costs', (evaluation or {}).get('costs') if bt else None, 'commission 1 + slippage 5 + half-spread 2 bps per side'],
        ['annualised return %', bt.get('annualised_return_pct') if bt else None,
         paper_ann if paper_ann is not None else 'fewer than 20 sessions'],
        ['annualised volatility %', bt.get('annualised_vol_pct') if bt else None, (status or {}).get('volatility_ann_pct')],
        ['Sharpe', bt.get('sharpe') if bt else None, (status or {}).get('sharpe')],
        ['Sortino', bt.get('sortino') if bt else None, (status or {}).get('sortino')],
        ['maximum drawdown %', bt.get('max_drawdown_pct') if bt else None, (status or {}).get('max_drawdown_pct')],
        ['comparable?', None, 'no: fewer than 52 weekly rebalances' if rebalances < MIN_PAPER_WEEKS else
         'sample length reached; the pre-registered evaluation decides'],
    ]
    return rows


def performance(marks, capital):
    """Paper performance from a list of marks (e.g. those known at a cutoff): the measures of Paper.status()."""
    if not marks:
        return {'status': 'NO MARK'}
    eq = pd.Series([m['equity'] for m in marks], index=[m['session'] for m in marks])
    rets = eq.pct_change().dropna()
    dd = eq / eq.cummax() - 1
    out = {'status': 'OK', 'sessions': len(marks), 'first_session': marks[0]['session'],
           'last_session': marks[-1]['session'], 'equity': marks[-1]['equity'],
           'total_return_pct': round((marks[-1]['equity'] / capital - 1) * 100, 3),
           'max_drawdown_pct': round(float(dd.min()) * 100, 3), 'volatility_ann_pct': None, 'sharpe': None,
           'sortino': None}
    if len(rets) >= 20:
        sd = float(rets.std(ddof=1))
        down = float((rets.clip(upper=0) ** 2).mean() ** 0.5)
        out['volatility_ann_pct'] = round(sd * 252 ** 0.5 * 100, 2)
        out['sharpe'] = round(float(rets.mean()) / sd * 252 ** 0.5, 3) if sd else None
        out['sortino'] = round(float(rets.mean()) / down * 252 ** 0.5, 3) if down else None
    return out


def known_at(entries, cutoff):
    """
    Entries written at or before `cutoff`. Fills, stops, dividends and splits carry no timestamp of their own: they
    are appended in one batch with the session's mark, so each is dated by the next timestamped entry (created_at or
    timestamp) in journal order; trailing undated entries are excluded.
    """
    from .common import to_utc_iso
    dated, nxt = [], None
    for e in reversed(entries):
        own = to_utc_iso(e.get('created_at') or e.get('timestamp') or e.get('recorded_at'))
        nxt = own or nxt
        dated.append((e, own or nxt))
    return [e for e, when in reversed(dated) if when is not None and when <= cutoff]
