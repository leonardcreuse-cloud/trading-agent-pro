#!/usr/bin/env python3
"""
Expanded predictive-edge study (phase P2.1) - `python main.py research --stage 1`

Protocol (fixed before results; see factors.py for hypotheses):
1. Panel: point-in-time features for the stage universe on weekly dates (panel.py).
2. Feature tests: cross-sectional rank IC of sign * feature vs forward return, per horizon;
   Newey-West t, p, 95 % CI. Family = all features x horizons (BH and Bonferroni).
3. Group composites (no fitting): mean of the signed cross-sectional ranks of a group's
   features; IC tests (family = groups x horizons) and non-overlapping quintile portfolios.
4. Models, strict walk-forward: test folds = calendar years; a fold is fitted only on samples
   whose outcome was known before the fold starts (purged), with >= MIN_TRAIN_YEARS of data.
   Inputs: per-date ranks of all features (missing = median); target: forward return above
   the date's median. Hyperparameters fixed a priori (no tuning, hence no validation set):
     logistic         C = 1e4 (practically unregularised)
     logistic_l2      C = 0.05
     random_forest    300 trees, max_depth 4, min_samples_leaf 200
     gradient_boosting  only if a simpler model shows a BH-significant positive IC
                        (otherwise "not justified"); max_depth 3, 200 iterations, lr 0.05
   OOS predictions are scored like the factors (IC, AUC, portfolios); family = models x
   horizons. The equal-weight composite of all groups is the no-fitting baseline.
Nothing is selected on historical return: every pre-registered test is reported.
"""

import json
import math
import pickle
from datetime import date

import numpy as np

from ..common import data_dir, redact, reports_dir, utc_now_iso
from ..database import Database
from .factors import FEATURES, GROUPS, HORIZONS, UNAVAILABLE_GROUPS, expected_sign, group_features
from .panel import STEP, PanelBuilder, check_features
from .stats import (MIN_STOCKS, correct, daily_ics, mean_test, nw_lags, quintile_portfolios,
                    spearman)
from .universe import SEED, Universe

STAGES = {0: 10, 1: 150, 2: None}      # 0 = smoke test only
MIN_TRAIN_YEARS = 3
MODEL_SPECS = ('logistic', 'logistic_l2', 'random_forest')


def make_model(name):
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    if name == 'logistic':
        return LogisticRegression(C=1e4, max_iter=2000)
    if name == 'logistic_l2':
        return LogisticRegression(C=0.05, max_iter=2000)
    if name == 'random_forest':
        return RandomForestClassifier(n_estimators=300, max_depth=4, min_samples_leaf=200,
                                      n_jobs=-1, random_state=0)
    if name == 'gradient_boosting':
        return HistGradientBoostingClassifier(max_depth=3, max_iter=200, learning_rate=0.05,
                                              random_state=0)
    raise ValueError(name)


# ---------------------------------------------------------------- helpers

def by_date(rows):
    out = {}
    for r in rows:
        out.setdefault(r['date'], []).append(r)
    return out


def centred_ranks(values):
    """Ranks in [-0.5, 0.5] for non-missing values; None stays None."""
    idx = [i for i, v in enumerate(values) if v is not None]
    out = [None] * len(values)
    if len(idx) < 2:
        return out
    from .stats import rankdata
    ranks = rankdata([values[i] for i in idx])
    for i, r in zip(idx, ranks):
        out[i] = (r - 1) / (len(idx) - 1) - 0.5
    return out


def add_composites(dates):
    """Signed per-date ranks of every feature, group composites and the all-group composite."""
    for group_rows in dates.values():
        signed = {}
        for f in FEATURES:
            ranks = centred_ranks([r['features'].get(f) for r in group_rows])
            signed[f] = [None if v is None else v * expected_sign(f) for v in ranks]
        for j, r in enumerate(group_rows):
            r['ranks'] = {f: signed[f][j] for f in FEATURES}
            comps = {}
            for g in GROUPS:
                vals = [signed[f][j] for f in group_features(g) if signed[f][j] is not None]
                comps[g] = float(np.mean(vals)) if vals else None
            avail = [v for v in comps.values() if v is not None]
            comps['all_groups'] = float(np.mean(avail)) if avail else None
            r['composites'] = comps


def ic_test(dates, score, horizon):
    key = f'fwd_{horizon}d'
    pairs = {d: [(score(r), r[key]) for r in rs] for d, rs in dates.items()}
    ics = daily_ics(pairs)
    test = mean_test(list(ics.values()), nw_lags(horizon, STEP))
    test['n_dates'] = len(ics)
    test['n_observations'] = sum(sum(1 for s, r in pairs[d] if s is not None and r is not None)
                                 for d in ics)
    test['positive_dates_pct'] = round(float(np.mean([v > 0 for v in ics.values()])) * 100, 1) \
        if ics else None
    test['period'] = [min(ics), max(ics)] if ics else None
    return test


def rebalance_dates(calendar, horizon):
    k = max(1, round(horizon / STEP))
    return calendar[::k]


def portfolio(dates, score, horizon, calendar, benchmark):
    key = f'fwd_{horizon}d'
    triples = {d: [(r['ticker'], score(r), r[key]) for r in rs] for d, rs in dates.items()}
    return quintile_portfolios(triples, rebalance_dates(calendar, horizon), horizon, benchmark)


# ---------------------------------------------------------------- models

def walk_forward_models(rows, horizon, calendar, benchmark, names):
    """OOS predictions per model on yearly folds; returns {model: result}."""
    from sklearn.metrics import roc_auc_score
    key, exit_key = f'fwd_{horizon}d', f'exit_{horizon}d'
    dates = by_date(rows)
    labelled = []
    for d, rs in dates.items():
        rets = [r[key] for r in rs if r[key] is not None]
        median = float(np.median(rets)) if len(rets) >= MIN_STOCKS else None
        for r in rs:
            x = [r['ranks'][f] if r['ranks'][f] is not None else 0.0 for f in FEATURES]
            y = None if median is None or r[key] is None else int(r[key] > median)
            labelled.append((r, x, y))
    X = np.array([l[1] for l in labelled], float)
    years = sorted({r['date'][:4] for r, _, _ in labelled})
    first_date = min(r['date'] for r, _, _ in labelled)
    results = {}
    for name in names:
        preds = [None] * len(labelled)
        folds = {}
        for year in years:
            test = [i for i, (r, _, _) in enumerate(labelled) if r['date'][:4] == year]
            start = min(labelled[i][0]['date'] for i in test)
            train = [i for i, (r, _, y) in enumerate(labelled)
                     if y is not None and r[exit_key] is not None and r[exit_key] < start]
            span = (date.fromisoformat(start) - date.fromisoformat(first_date)).days / 365.25
            if span < MIN_TRAIN_YEARS or len({labelled[i][1] is not None for i in train}) == 0 \
                    or len({labelled[i][2] for i in train}) < 2:
                folds[year] = {'status': 'skipped (training history < 3 years)'}
                continue
            model = make_model(name)
            model.fit(X[train], [labelled[i][2] for i in train])
            proba = model.predict_proba(X[test])[:, 1]
            for i, p in zip(test, proba):
                preds[i] = float(p)
            train_dates = sorted({labelled[i][0]['date'] for i in train})
            folds[year] = {'status': 'tested', 'train_start': train_dates[0],
                           'train_end': train_dates[-1], 'train_rows': len(train),
                           'test_rows': len(test)}
        scored = [dict(r, model_score=p) for (r, _, _), p in zip(labelled, preds) if p is not None]
        if not scored:
            results[name] = {'status': 'INSUFFICIENT DATA', 'folds': folds}
            continue
        oos_dates = by_date(scored)
        y_true = [int(r[key] > np.median([s[key] for s in oos_dates[r['date']] if s[key] is not None]))
                  for r in scored if r[key] is not None]
        y_score = [r['model_score'] for r in scored if r[key] is not None]
        oos_calendar = [d for d in calendar if d in oos_dates]
        results[name] = {
            'status': 'OK', 'folds': folds,
            'oos_period': [min(oos_dates), max(oos_dates)],
            'ic': ic_test(oos_dates, lambda r: r['model_score'], horizon),
            'auc': round(float(roc_auc_score(y_true, y_score)), 4) if len(set(y_true)) == 2 else None,
            'portfolio': portfolio(oos_dates, lambda r: r['model_score'], horizon, oos_calendar, benchmark),
            'baseline_all_groups_same_dates': ic_test(oos_dates, lambda r: r['composites']['all_groups'],
                                                      horizon),
        }
    return results


# ---------------------------------------------------------------- run

class Study:
    def __init__(self, stage=1, db=None):
        self.stage = stage
        self.db = db or Database()
        self.cache = data_dir() / 'research' / f'panel_stage{stage}.pkl'

    def panel(self, rebuild=False):
        universe = Universe(db=self.db)
        members = universe.stage(STAGES[self.stage])
        if self.cache.exists() and not rebuild:
            with open(self.cache, 'rb') as fh:
                cached = pickle.load(fh)
            if [m['ticker'] for m in members] == cached['tickers']:
                print(f"  panel reused from {self.cache} (built {cached['built_at']})")
                return cached, universe
        print(f"\n[PANEL] stage {self.stage}: {len(members)} stocks")
        rows, info, benchmark, calendar = PanelBuilder(self.db).build(members)
        check_features(rows)
        cached = {'tickers': [m['ticker'] for m in members], 'members': members, 'rows': rows,
                  'info': info, 'benchmark': benchmark, 'calendar': calendar,
                  'built_at': utc_now_iso(), 'universe_fetch': universe.fetch}
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache, 'wb') as fh:
            pickle.dump(cached, fh)
        return cached, universe

    def run(self, rebuild=False):
        panel, universe = self.panel(rebuild)
        rows, calendar, benchmark = panel['rows'], panel['calendar'], panel['benchmark']
        dates = by_date(rows)
        add_composites(dates)
        print(f"\n[TESTS] {len(rows)} observations, {len({r['ticker'] for r in rows})} stocks, "
              f"{len(dates)} dates")

        feature_tests = []
        for f in FEATURES:
            for h in HORIZONS:
                t = ic_test(dates, lambda r, f=f: r['ranks'][f], h)
                feature_tests.append({'feature': f, 'group': FEATURES[f][0], 'expected_sign': FEATURES[f][1],
                                      'basis': FEATURES[f][2], 'horizon': h, **t,
                                      'coverage_pct': round(100 * sum(r['features'].get(f) is not None
                                                                      for r in rows) / len(rows), 1)})
        correct(feature_tests)

        group_tests = []
        for g in GROUPS + ('all_groups',):
            for h in HORIZONS:
                t = ic_test(dates, lambda r, g=g: r['composites'][g], h)
                t.update({'group': g, 'horizon': h,
                          'portfolio': portfolio(dates, lambda r, g=g: r['composites'][g], h, calendar,
                                                 benchmark)})
                group_tests.append(t)
        correct(group_tests)

        model_tests, gb_status = [], {}
        for h in HORIZONS:
            print(f"  models, horizon {h} ...")
            res = walk_forward_models(rows, h, calendar, benchmark, MODEL_SPECS)
            for name, r in res.items():
                model_tests.append({'model': name, 'horizon': h, **r, **(r.get('ic') or {})})
        correct(model_tests)
        justified = [m for m in model_tests if m.get('significant_bh') and (m.get('mean') or 0) > 0]
        if justified:
            for h in sorted({m['horizon'] for m in justified}):
                res = walk_forward_models(rows, h, calendar, benchmark, ('gradient_boosting',))
                model_tests.append({'model': 'gradient_boosting', 'horizon': h, **res['gradient_boosting'],
                                    **(res['gradient_boosting'].get('ic') or {})})
            correct(model_tests)
            gb_status = {'run': True, 'reason': f'{len(justified)} simpler model test(s) BH-significant'}
        else:
            gb_status = {'run': False, 'reason': 'not justified: no simpler model has a BH-significant '
                                                  'positive out-of-sample IC'}

        n_tests = len(feature_tests) + len(group_tests) + len(model_tests)
        report = {
            'stage': self.stage, 'computed_at': utc_now_iso(),
            'universe': {'source': universe.fetch and universe.fetch['source'],
                         'fetch_id': panel['universe_fetch'] and panel['universe_fetch']['fetch_id'],
                         'rule': 'current S&P 500 members excl. Financials and Real Estate; '
                                 f'seeded random sample (seed {SEED}) of {STAGES[self.stage] or "all"}; '
                                 'stock included from its date added to the index',
                         'n_stocks_requested': len(panel['tickers']),
                         'n_stocks_with_data': len({r['ticker'] for r in rows}),
                         'biases': ['survivorship: members removed before today are absent',
                                    'GICS sector is the current classification']},
            'sample': {'n_observations': len(rows), 'n_dates': len(dates),
                       'first_date': min(dates), 'last_date': max(dates), 'step_sessions': STEP,
                       'stocks_per_date_median': int(np.median([len(v) for v in dates.values()]))},
            'protocol': __doc__.strip(),
            'horizons_sessions': list(HORIZONS),
            'unavailable_groups': UNAVAILABLE_GROUPS,
            'n_tests_total': n_tests,
            'feature_tests': feature_tests,
            'group_tests': group_tests,
            'model_tests': [{k: v for k, v in m.items() if k != 'ic'} for m in model_tests],
            'gradient_boosting': gb_status,
            'ticker_info': panel['info'],
        }
        report['conclusion'] = conclusion(report)
        out = reports_dir() / f'research_stage{self.stage}.json'
        out.write_text(redact(json.dumps(report, indent=1, default=str)), encoding='utf-8')
        print_summary(report)
        print(f"\n  Results: {out}")
        return report


def conclusion(report):
    sig = lambda tests: [t for t in tests if t.get('significant_bh')]  # noqa: E731
    f, g, m = sig(report['feature_tests']), sig(report['group_tests']), sig(report['model_tests'])
    right = lambda ts: [t for t in ts if (t.get('mean') or 0) > 0]  # noqa: E731
    lines = [f"{len(report['feature_tests'])} feature tests, {len(report['group_tests'])} group tests, "
             f"{len(report['model_tests'])} model tests ({report['n_tests_total']} in total)."]
    lines.append(f"After Benjamini-Hochberg correction (q < 0.05) within each family: "
                 f"{len(f)} feature, {len(g)} group and {len(m)} model results are significant "
                 f"({len(right(f))}, {len(right(g))}, {len(right(m))} in the pre-registered direction).")
    bonf = [t for t in report['feature_tests'] + report['group_tests'] + report['model_tests']
            if t.get('significant_bonferroni')]
    lines.append(f"After Bonferroni correction: {len(bonf)} significant.")
    edge = right(g) + right(m)
    lines.append('A predictive edge is SUPPORTED for: ' + ', '.join(
        f"{t.get('group') or t.get('model')} at {t['horizon']}d" for t in edge)
        if edge else 'No group composite or model shows a statistically reliable predictive edge '
                     'after correction.')
    return lines


def print_summary(report):
    print("\n  Group composites (pre-registered direction), mean daily rank IC:")
    print(f"    {'group':17}" + ''.join(f"{str(h) + 'd':>18}" for h in HORIZONS))
    for g in GROUPS + ('all_groups',):
        cells = []
        for h in HORIZONS:
            t = next(x for x in report['group_tests'] if x['group'] == g and x['horizon'] == h)
            flag = '**' if t['significant_bonferroni'] else '*' if t['significant_bh'] else ''
            cells.append(f"{t['mean']:+.4f} t={t['t_stat']:+.2f}{flag}" if t['mean'] is not None else 'n/a')
        print(f"    {g:17}" + ''.join(f"{c:>18}" for c in cells))
    print("\n  Models, out-of-sample (walk-forward yearly folds):")
    for m in report['model_tests']:
        flag = '**' if m.get('significant_bonferroni') else '*' if m.get('significant_bh') else ''
        ls = (m.get('portfolio') or {}).get('long_short_net', {})
        print(f"    {m['model']:18} {m['horizon']:>3}d  IC {m.get('mean')} t={m.get('t_stat')}{flag} "
              f"AUC {m.get('auc')}  L/S net Sharpe {ls.get('sharpe')} maxDD {ls.get('max_drawdown_pct')}%")
    print(f"\n  Gradient boosting: {report['gradient_boosting']['reason']}")
    print("  (* BH q < 0.05, ** Bonferroni p < 0.05)\n")
    for line in report['conclusion']:
        print('  ' + line)
