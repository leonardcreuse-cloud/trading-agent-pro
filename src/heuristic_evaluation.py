#!/usr/bin/env python3
"""
Descriptive evaluation of the heuristic signal over the walk-forward sample (master mission P3)

`python main.py evaluate-heuristic`

Input: the walk-forward results file (reports/walk_forward.json): one row per ticker and evaluation date (every
5 sessions) with the ex-news combined score, its label and forward returns from the close of the next session
(5 and 20 sessions), computed point-in-time with nothing fitted. This module adds the metrics required by the
master mission WITHOUT changing the signal, its weights or the sample. It tests no new hypothesis: the
confirmatory evidence stays the walk-forward criterion (scoring_signal_fixed.validation_status) and the
pre-registered stage 3 test. Everything here is descriptive and in-sample of that one walk-forward run.

  classification   (labels recomputed from the stored combined score with the production thresholds, >= 65
                   POSITIVE: files written before the P1.4 relabel store BUY / HOLD / SELL)
                   label POSITIVE as a prediction of (a) a positive forward return and (b) a return above the
                   cross-sectional median of the date (removes the market-wide move): precision, recall, F1,
                   accuracy vs base rate; AUC of the combined score for both outcomes
  probabilities    NOT CALIBRATED: the heuristic outputs a 0-100 score, not a probability; Brier score and
                   calibration are not applicable and are not computed on it
  portfolios       src/research/stats.quintile_portfolios (the research convention): every H sessions
                   (non-overlapping rebalancing), top quintile of the combined score long-only, long-short (top minus
                   bottom quintile), equal-weight universe and SPY benchmarks, costs COST_BPS per unit of turnover,
                   at least MIN_STOCKS scored tickers per date; Sharpe, Sortino, max drawdown, turnover, net returns
                   (risk-free rate 0, stated)
  sample           tickers, observations, dates and period; the universe was chosen in 2026 (current large caps,
                   no delisted company): selection and survivorship bias, stated in the output
Writes reports/heuristic_evaluation.json (and an archived copy) and docs/research/HEURISTIC_EVALUATION.md.
"""

import hashlib
import json

from .common import history_dir, reports_dir, stamp, utc_now_iso
from .research.metrics import auc, confusion
from .research.stats import COST_BPS, MIN_STOCKS, quintile_portfolios
from .scoring_signal_fixed import ScoringSignalFixed

HORIZONS = (5, 20)
STEP = 5
RESULTS_FILE = 'heuristic_evaluation.json'
DOC = 'docs/research/HEURISTIC_EVALUATION.md'


def spy_forward(closes, dates, horizons=HORIZONS):
    """{date: {'fwd_Hd': SPY return from the close of the next session to H sessions later}} from {iso: close}."""
    days = sorted(closes)
    pos = {d: i for i, d in enumerate(days)}
    out = {}
    for d in dates:
        later = [x for x in days if x > d]
        if not later:
            continue
        e = pos[later[0]]
        out[d] = {f'fwd_{h}d': closes[days[e + h]] / closes[days[e]] - 1 if e + h < len(days) else None
                  for h in horizons}
    return out


def classification(samples, key):
    rows = [s for s in samples if s.get(key) is not None and s.get('combined') is not None]
    by_date = {}
    for s in rows:
        by_date.setdefault(s['date'], []).append(s[key])
    med = {d: sorted(v)[len(v) // 2] if len(v) % 2 else (sorted(v)[len(v) // 2 - 1] + sorted(v)[len(v) // 2]) / 2
           for d, v in by_date.items()}
    up = [s[key] > 0 for s in rows]
    beat = [s[key] > med[s['date']] for s in rows]
    label = ScoringSignalFixed().generate_final_signal
    predicted = [label(s['combined']) == 'POSITIVE' for s in rows]
    scores = [s['combined'] for s in rows]
    return {'n': len(rows),
            'positive_return': {'label_positive': confusion(predicted, up), 'auc_combined_score': auc(scores, up)},
            'beats_cross_sectional_median': {'label_positive': confusion(predicted, beat),
                                             'auc_combined_score': auc(scores, beat)},
            'probabilities': 'NOT CALIBRATED: the heuristic outputs a 0-100 score, not a probability (Brier score and '
                             'calibration not applicable)'}


def evaluate(walk_forward=None, spy_closes=None, now=None):
    path = reports_dir() / 'walk_forward.json'
    raw = path.read_bytes() if walk_forward is None else None
    wf = json.loads(raw) if walk_forward is None else walk_forward
    samples = wf.get('samples') or []
    dates = sorted({s['date'] for s in samples})
    benchmark = spy_forward(spy_closes, dates) if spy_closes else None
    result = {
        'computed_at': now or utc_now_iso(),
        'input': {'file': 'reports/walk_forward.json', 'computed_at': wf.get('computed_at'), 'method': wf.get('method'),
                  'sha256': hashlib.sha256(raw).hexdigest() if raw else None},
        'sample': {'tickers': len({s['ticker'] for s in samples}), 'observations': len(samples), 'dates': len(dates),
                   'period': [dates[0], dates[-1]] if dates else None,
                   'scored_observations': sum(1 for s in samples if s.get('combined') is not None)},
        'nature': ('descriptive, in-sample of one walk-forward run; nothing fitted; no new hypothesis tested; the '
                   'confirmatory evidence is the walk-forward criterion and the pre-registered stage 3 test'),
        'biases': ['universe chosen in 2026 (current large caps): selection and survivorship bias; no delisted '
                   'company', 'adjusted prices of the current vintage', 'ex-news combined score (the news lexicon '
                   'has no history and is not validated)'],
        'costs': f'{COST_BPS} bps per unit of turnover; risk-free rate 0',
        'benchmark_spy': 'SPY forward returns with the same entry and exit sessions' if benchmark else
                         'DATA UNAVAILABLE: SPY closes not provided',
        'horizons': {},
    }
    for h in HORIZONS:
        key = f'fwd_{h}d'
        by_date = {}
        for s in samples:
            by_date.setdefault(s['date'], []).append((s['ticker'], s.get('combined'), s.get(key)))
        rebalance = dates[::max(1, h // STEP)]
        result['horizons'][f'{h}d'] = {
            'classification': classification(samples, key),
            'portfolios': quintile_portfolios(by_date, rebalance, h, benchmark=benchmark, cost_bps=COST_BPS,
                                              min_stocks=MIN_STOCKS),
            'rebalance_dates_available': len(rebalance),
        }
    return result


def write(result):
    text = json.dumps(result, indent=1, default=str)
    (reports_dir() / RESULTS_FILE).write_text(text, encoding='utf-8')
    (history_dir() / f"heuristic_evaluation_{stamp(result['computed_at'])}.json").write_text(text, encoding='utf-8')
    return text


def markdown(result):
    def pct(v):
        return 'n/a' if v is None else f'{v:+.2f}%'
    s = result['sample']
    lines = ['# Heuristic signal: descriptive evaluation on the walk-forward sample', '',
             f"Computed {result['computed_at']} by `python main.py evaluate-heuristic` from "
             f"`{result['input']['file']}` (walk-forward computed {result['input']['computed_at']}, sha256 "
             f"{result['input']['sha256']}).", '',
             f"**Nature**: {result['nature']}.", '',
             f"Sample: {s['tickers']} tickers, {s['observations']} observations ({s['scored_observations']} with a "
             f"combined score), {s['dates']} dates from {s['period'][0]} to {s['period'][1]}. Costs: "
             f"{result['costs']}. Biases: " + '; '.join(result['biases']) + '.', '']
    for h, m in result['horizons'].items():
        c, p = m['classification'], m['portfolios']
        up, beat = c['positive_return'], c['beats_cross_sectional_median']
        lines += [f'## Horizon {h}', '',
                  f"- Label POSITIVE as a prediction of a positive return: precision {up['label_positive']['precision']} "
                  f"vs base rate {up['label_positive']['base_rate']}, recall {up['label_positive']['recall']}, "
                  f"F1 {up['label_positive']['f1']}; AUC of the score {up['auc_combined_score']}.",
                  f"- As a prediction of beating the cross-sectional median: precision "
                  f"{beat['label_positive']['precision']} (base rate {beat['label_positive']['base_rate']}), AUC "
                  f"{beat['auc_combined_score']}.",
                  f"- Probabilities: {c['probabilities']}.", '',
                  '| portfolio | periods | annualised return | volatility | Sharpe | Sortino | max drawdown |',
                  '|---|---|---|---|---|---|---|']
        for name in ('long_only_top_quintile_net', 'long_short_net', 'long_only_net_minus_equal_weight',
                     'benchmark_equal_weight_universe', 'benchmark_spy'):
            x = p.get(name) or {}
            lines.append(f"| {name.replace('_', ' ')} | {x.get('n_periods')} | {pct(x.get('annualised_return_pct'))} | "
                         f"{pct(x.get('annualised_vol_pct'))} | {x.get('sharpe')} | {x.get('sortino')} | "
                         f"{pct(x.get('max_drawdown_pct'))} |")
        lines += ['', f"Mean turnover per rebalance {p.get('mean_turnover_per_rebalance')}; rebalancing every "
                      f"{h.rstrip('d')} sessions.", '']
    lines += ['These figures describe one historical run of a heuristic whose weights were never fitted. They are '
              'not evidence of a future edge: see the validation status and the stage 3 pre-registration.']
    return '\n'.join(lines) + '\n'


def run():
    from .market_data import PriceFeed
    spy = PriceFeed(lookback_days=1900).get('SPY')
    closes = {d.date().isoformat(): float(v) for d, v in spy['close'].items()} if spy['status'] == 'OK' else None
    result = evaluate(spy_closes=closes)
    write(result)
    from .common import PROJECT_ROOT
    (PROJECT_ROOT / DOC).write_text(markdown(result), encoding='utf-8')
    for h, m in result['horizons'].items():
        p = m['portfolios']
        print(f"  {h}: long-only top quintile net Sharpe {p['long_only_top_quintile_net'].get('sharpe')}, "
              f"vs equal weight {p['benchmark_equal_weight_universe'].get('sharpe')}; AUC "
              f"{m['classification']['beats_cross_sectional_median']['auc_combined_score']}")
    return result
