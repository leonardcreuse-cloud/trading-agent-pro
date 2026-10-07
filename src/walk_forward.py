#!/usr/bin/env python3
"""
Walk-forward validation (phase P1.2) - point-in-time out-of-sample evaluation

Question answered: had the agent run every week over the last years, using only the data
public at that time, would its scores have ranked future returns correctly?

Protocol
- Evaluation dates: every STEP sessions, once MIN_HISTORY sessions of prices exist.
- Signal instant T = session close (21:00 UTC) of the evaluation date. Inputs at T:
    technical     closes up to and including T (PriceTechnical.score_closes)
    fundamentals  SEC XBRL facts whose filing was accepted by T (SECParser.fundamentals)
    insider       Form 4 transactions filed in (T - 90 d, T]; unavailable when that window
                  is not fully covered by the downloaded filing history or contains a filing
                  that could not be read (never scored as "no transaction")
    news          NOT evaluated: NewsAPI has no history (free tier: 30 days). The evaluated
                  combined signal therefore uses technical / fundamentals / insider only.
  The combined score is the production ScoringSignalFixed over those components (>= 2).
- Outcome: return from the close of session T+1 (the first close at which a decision made
  after T's close can be executed) to the close of session T+1+H, H in HORIZONS.
- Nothing is fitted: weights and thresholds are the fixed heuristics, so every evaluation
  date is out-of-sample. Folds (calendar half-years) measure stability over time.

Metrics (per horizon)
- Rank IC: Spearman correlation between score and forward return, per component, pooled
  over tickers and per ticker. n_effective = n * STEP / H accounts for overlapping
  windows when H > STEP; t = IC * sqrt((n_eff - 2) / (1 - IC^2)); |t| >= 2 flagged.
- Combined signal classes: count, mean forward return, hit rate; versus the unconditional
  mean / up-rate of all evaluation dates (baseline: always long).
- Per fold: IC of the combined score.
- Cross-sectional IC (P1.2b): on each evaluation date with >= MIN_CROSS_SECTION tickers,
  Spearman across tickers; mean over dates, t = mean / std * sqrt(n_dates_eff). This is the
  standard measure for ranking stocks against each other (removes market-wide moves).

Universe: config 'validation_universe' (default: the daily universe), or tickers on the
command line. A failing ticker is reported and skipped; the others are still evaluated.

Known limitations (reported in the output)
- Adjusted prices are today's vintage (Yahoo revises them after splits / dividends);
  the technical indicators used are scale-invariant, returns are not affected by splits.
- Universe of 4 tickers chosen today (survivorship / selection bias); no transaction costs.
"""

import json
import math
from datetime import datetime, timedelta, timezone

import pandas as pd

from .common import (DATA_UNAVAILABLE, load_config, redact, reports_dir, to_utc_iso,
                     utc_now_iso, validation_universe)
from .database import Database
from .features import feature_vector
from .model import feature_ics, walk_forward_model
from .insider_tracker import LOOKBACK_DAYS as INSIDER_WINDOW_DAYS, InsiderTracker, insider_score
from .market_data import PriceFeed, session_close_utc
from .price_technical import PriceTechnical
from .scoring_fundamentals import ScoringFundamentals
from .scoring_signal_fixed import ScoringSignalFixed
from .sec_parser import SECParser

METHOD = 'walk_forward_heuristic_v1'
HISTORY_DAYS = 1825
HORIZONS = (5, 20)
STEP = 5
MIN_HISTORY = 150
ENTRY_LAG = 1
COMPONENTS = ('technical', 'fundamentals', 'insider', 'combined')
RESULTS_FILE = 'walk_forward.json'
STALE_AFTER_DAYS = 7
MIN_CROSS_SECTION = 10


def spearman(x, y):
    """Spearman rank correlation (Pearson on average ranks); None if undefined."""
    frame = pd.DataFrame({'x': x, 'y': y}).dropna()
    if len(frame) < 3:
        return None
    rx, ry = frame['x'].rank(), frame['y'].rank()
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(rx.corr(ry))


def ic_stats(scores, returns, horizon, step=STEP):
    """IC with an overlap-adjusted t statistic."""
    pairs = [(s, r) for s, r in zip(scores, returns) if s is not None and r is not None]
    n = len(pairs)
    ic = spearman([p[0] for p in pairs], [p[1] for p in pairs]) if pairs else None
    n_eff = n * min(1.0, step / horizon)
    t_stat = None
    if ic is not None and n_eff > 2 and abs(ic) < 1:
        t_stat = ic * math.sqrt((n_eff - 2) / (1 - ic * ic))
    return {'n': n, 'n_effective': round(n_eff, 1),
            'ic': None if ic is None else round(ic, 4),
            't_stat': None if t_stat is None else round(t_stat, 2),
            'significant': bool(t_stat is not None and abs(t_stat) >= 2)}


def cross_sectional_ic(rows, component, key, horizon, step=STEP, min_tickers=MIN_CROSS_SECTION):
    """Mean over dates of the Spearman IC across tickers (see module docstring)."""
    by_date = {}
    for r in rows:
        if r[component] is not None and r[key] is not None:
            by_date.setdefault(r['date'], []).append((r[component], r[key]))
    ics = [spearman([p[0] for p in pairs], [p[1] for p in pairs])
           for pairs in by_date.values() if len(pairs) >= min_tickers]
    ics = [ic for ic in ics if ic is not None]
    if len(ics) < 3:
        return {'n_dates': len(ics), 'mean_ic': None, 't_stat': None, 'significant': False}
    mean = sum(ics) / len(ics)
    std = (sum((x - mean) ** 2 for x in ics) / (len(ics) - 1)) ** 0.5
    n_eff = len(ics) * min(1.0, step / horizon)
    t_stat = mean / std * math.sqrt(n_eff) if std > 0 else None
    return {'n_dates': len(ics), 'n_effective': round(n_eff, 1), 'mean_ic': round(mean, 4),
            'positive_dates_pct': round(sum(ic > 0 for ic in ics) / len(ics) * 100, 1),
            't_stat': None if t_stat is None else round(t_stat, 2),
            'significant': bool(t_stat is not None and abs(t_stat) >= 2)}


def class_stats(rows, key):
    """Count, mean forward return (%) and hit rate per combined signal class."""
    out = {}
    for label in ('BUY', 'HOLD', 'SELL'):
        returns = [r[key] for r in rows if r['signal'] == label and r[key] is not None]
        if not returns:
            out[label] = {'n': 0, 'mean_return_pct': None, 'hit_rate_pct': None}
            continue
        hits = [x < 0 if label == 'SELL' else x > 0 for x in returns]
        out[label] = {'n': len(returns),
                      'mean_return_pct': round(sum(returns) / len(returns) * 100, 3),
                      'hit_rate_pct': round(sum(hits) / len(hits) * 100, 2)}
    return out


def half_year(day):
    return f"{day[:4]}H{1 if int(day[5:7]) <= 6 else 2}"


def evaluate(samples, horizons=HORIZONS, step=STEP):
    """Aggregate metrics (see module docstring) from walk-forward samples."""
    metrics = {}
    for h in horizons:
        key = f'fwd_{h}d'
        rows = [s for s in samples if s[key] is not None]
        all_returns = [s[key] for s in rows]
        by_ticker = {}
        for t in sorted({s['ticker'] for s in rows}):
            t_rows = [s for s in rows if s['ticker'] == t]
            by_ticker[t] = {c: ic_stats([s[c] for s in t_rows], [s[key] for s in t_rows], h, step)
                            for c in COMPONENTS}
        folds = {}
        for fold in sorted({half_year(s['date']) for s in rows}):
            f_rows = [s for s in rows if half_year(s['date']) == fold]
            folds[fold] = ic_stats([s['combined'] for s in f_rows], [s[key] for s in f_rows], h, step)
        fold_ics = [f['ic'] for f in folds.values() if f['ic'] is not None]
        signal_rows = [s for s in rows if s['signal'] in ('BUY', 'HOLD', 'SELL')]
        classes = class_stats(signal_rows, key)
        baseline = {
            'n': len(all_returns),
            'mean_return_pct': round(sum(all_returns) / len(all_returns) * 100, 3) if all_returns else None,
            'up_rate_pct': round(sum(r > 0 for r in all_returns) / len(all_returns) * 100, 2)
            if all_returns else None,
        }
        buy, sell = classes['BUY']['mean_return_pct'], classes['SELL']['mean_return_pct']
        metrics[f'{h}d'] = {
            'ic_pooled': {c: ic_stats([s[c] for s in rows], all_returns, h, step) for c in COMPONENTS},
            'ic_cross_sectional': {c: cross_sectional_ic(rows, c, key, h, step) for c in COMPONENTS},
            'ic_by_ticker': by_ticker,
            'combined_signal_classes': classes,
            'baseline_always_long': baseline,
            'buy_excess_vs_baseline_pct': None if buy is None or baseline['mean_return_pct'] is None
            else round(buy - baseline['mean_return_pct'], 3),
            'buy_minus_sell_pct': None if buy is None or sell is None else round(buy - sell, 3),
            'folds': folds,
            'folds_with_positive_ic': f"{sum(ic > 0 for ic in fold_ics)}/{len(fold_ics)}",
        }
    return metrics


class WalkForward:
    """Point-in-time weekly re-evaluation of the heuristic signal over price history."""

    def __init__(self, db=None, price_feed=None, sec_parser=None, history_days=HISTORY_DAYS):
        self.db = db or Database()
        self.history_days = history_days
        self.prices = price_feed or PriceFeed(db=self.db, lookback_days=history_days)
        self.sec = sec_parser or SECParser(db=self.db)
        self.insider = InsiderTracker(sec_parser=self.sec)
        self.technical = PriceTechnical(price_feed=self.prices)
        self.fundamentals = ScoringFundamentals(sec_parser=self.sec)
        self.signal = ScoringSignalFixed()

    def _insider_coverage(self, ticker):
        """(earliest instant with a fully covered window or None, failed filing times) or None."""
        print(f"  [SEC] Form 4 history for {ticker} ({self.history_days} days)...")
        ingested = self.insider.ingest(ticker, days=self.history_days, progress=True)
        if ingested is None:
            return None
        n_filings, n_parsed, failures = ingested
        print(f"    {n_filings} Form 4 filings, {n_parsed} parsed, {len(failures)} failed")
        starts = [datetime.now(timezone.utc) - timedelta(days=self.history_days)]
        coverage = (self.sec._filings_cache.get(ticker) or {}).get('coverage_start')
        if coverage:
            starts.append(datetime.fromisoformat(coverage).replace(tzinfo=timezone.utc))
        first_full = max(starts) + timedelta(days=INSIDER_WINDOW_DAYS)
        return {'first_full_window': to_utc_iso(first_full),
                'failed_at': sorted(f['published_at'] for f in failures if f.get('published_at')),
                'n_filings': n_filings, 'n_parsed': n_parsed, 'n_failed': len(failures)}

    def _insider_summary_at(self, ticker, coverage, known):
        """Form 4 window summary at `known`, or None when the window is not fully covered."""
        if not coverage or known < coverage['first_full_window']:
            return None
        start = to_utc_iso(datetime.fromisoformat(known) - timedelta(days=INSIDER_WINDOW_DAYS))
        if any(start < t <= known for t in coverage['failed_at']):
            return None
        return self.insider.summarize(ticker, known_at=known)

    def _insider_at(self, ticker, coverage, known):
        summary = self._insider_summary_at(ticker, coverage, known)
        return None if summary is None else insider_score(summary)

    def samples(self, ticker):
        """One row per evaluation date: component scores, combined signal, forward returns."""
        prices = self.prices.get(ticker)
        if prices['status'] != 'OK':
            return None, {'reason': prices['reason'], 'provenance': prices['provenance']}
        close = prices['close']
        if len(close) < MIN_HISTORY + ENTRY_LAG + min(HORIZONS):
            return None, {'reason': f'only {len(close)} sessions', 'provenance': prices['provenance']}
        self.sec.last_error = None
        coverage = self._insider_coverage(ticker)
        facts = self.sec.ingest_company_facts(ticker)

        values = close.to_numpy(dtype=float)
        dates = [d.date().isoformat() for d in close.index]
        rows = []
        for i in range(MIN_HISTORY - 1, len(values) - ENTRY_LAG - min(HORIZONS), STEP):
            known = session_close_utc(dates[i])
            tech = self.technical.score_closes(values[:i + 1])
            fund, fin = None, None
            if facts:
                fin = self.sec.fundamentals(ticker, known_at=known)
                fund, _ = self.fundamentals.score_inputs(fin)
            insider = self._insider_summary_at(ticker, coverage, known)
            scores = {'technical': tech['technical_score'] if tech else None,
                      'fundamentals': fund,
                      'insider': None if insider is None else insider_score(insider)}
            available = [k for k, v in scores.items() if v is not None]
            combined = self.signal.combine_scores(scores) \
                if len(available) >= self.signal.MIN_COMPONENTS else None
            entry = i + ENTRY_LAG
            row = {'ticker': ticker, 'date': dates[i], 'known_at': known, **scores,
                   'combined': combined, 'signal': self.signal.generate_final_signal(combined),
                   'entry_date': dates[entry],
                   'features': feature_vector(values[:i + 1], fin, insider)}
            for h in HORIZONS:
                exit_ = entry + h
                row[f'fwd_{h}d'] = values[exit_] / values[entry] - 1 if exit_ < len(values) else None
                row[f'exit_{h}d'] = dates[exit_] if exit_ < len(values) else None
            rows.append(row)
        return rows, {'reason': None, 'provenance': prices['provenance'],
                      'insider_coverage': coverage, 'company_facts_fetch': facts and facts['fetch_id'],
                      'sec_error': self.sec.last_error}

    def run(self, universe=None):
        print("\n" + "=" * 80)
        print(f"[WALK-FORWARD VALIDATION] {METHOD}, history {self.history_days} days")
        print("=" * 80)
        all_samples, per_ticker = [], {}
        universe = universe or validation_universe()
        for n, ticker in enumerate(universe, 1):
            print(f"\n[{ticker}] ({n}/{len(universe)})")
            try:
                rows, info = self.samples(ticker)
            except Exception as e:  # noqa: BLE001 - one ticker must not stop the run
                rows, info = None, {'reason': redact(f'{type(e).__name__}: {e}'), 'provenance': None}
            if rows is None:
                print(f"  {DATA_UNAVAILABLE}: {info['reason']}")
                per_ticker[ticker] = {'status': DATA_UNAVAILABLE, **info}
                continue
            all_samples.extend(rows)
            per_ticker[ticker] = {'status': 'OK', 'n_dates': len(rows),
                                  'first_date': rows[0]['date'] if rows else None,
                                  'last_date': rows[-1]['date'] if rows else None, **info}
            print(f"  {len(rows)} evaluation dates ({per_ticker[ticker]['first_date']} -> "
                  f"{per_ticker[ticker]['last_date']})")

        result = {
            'method': METHOD,
            'status': 'OK' if all_samples else DATA_UNAVAILABLE,
            'computed_at': utc_now_iso(),
            'universe': universe,
            'universe_rule': load_config().get('validation_universe_rule'),
            'protocol': {'history_days': self.history_days, 'step_sessions': STEP,
                         'min_history_sessions': MIN_HISTORY, 'entry_lag_sessions': ENTRY_LAG,
                         'horizons_sessions': list(HORIZONS),
                         'components': list(COMPONENTS),
                         'excluded': {'news': 'NewsAPI has no history (free tier: 30 days)'},
                         'signal_weights': self.signal.WEIGHTS},
            'limitations': [
                'Adjusted prices are the current vintage (revised by Yahoo after splits/dividends).',
                'Universe chosen today (current large caps): selection / survivorship bias.',
                'No transaction costs, positions or risk: this measures ranking skill only (P1.1).',
                'Heuristic weights and thresholds were not fitted, so nothing is in-sample, '
                'but they were also never optimised.'],
            'tickers': per_ticker,
            'metrics': evaluate(all_samples) if all_samples else {},
            'model': {f'{h}d': walk_forward_model(all_samples, h, STEP) for h in HORIZONS}
            if all_samples else {},
            'feature_ics': {f'{h}d': feature_ics(all_samples, h, STEP) for h in HORIZONS}
            if all_samples else {},
            'samples': all_samples,
        }
        self._print(result)
        path = reports_dir() / RESULTS_FILE
        path.write_text(redact(json.dumps(result, indent=1, default=str)), encoding='utf-8')
        print(f"\n  Results: {path}")
        return result

    @staticmethod
    def _print(result):
        for horizon, fics in result.get('feature_ics', {}).items():
            print(f"\n  Feature cross-sectional IC, {horizon} (descriptive, nothing fitted)")
            for f, x in fics.items():
                flag = ' *' if x['significant'] else ''
                print(f"    {f:22} {str(x['mean']):>9}  t={str(x['t_stat']):>6}{flag}")
        for horizon, m in result.get('model', {}).items():
            print(f"\n  Fitted model, {horizon} - walk-forward out-of-sample")
            if m.get('status') != 'OK':
                print(f"    {m.get('status')}: {m.get('reason')}")
                continue
            for name in ('model_oos', 'heuristic_same_dates', 'technical_same_dates'):
                ic, sp = m[name]['ic'], m[name]['top_minus_bottom_quintile_pct']
                flag = ' *' if ic['significant'] else ''
                print(f"    {name:22} IC {str(ic['mean']):>8} t={str(ic['t_stat']):>6}{flag}   "
                      f"Q5-Q1 {str(sp['mean']):>7}% t={sp['t_stat']}")
            print(f"    Test period {m['test_period'][0]} -> {m['test_period'][1]}, "
                  f"folds with positive IC {m['folds_with_positive_ic']}")
        for horizon, m in result['metrics'].items():
            print(f"\n  Horizon {horizon} (pooled over tickers)")
            for c, s in m['ic_pooled'].items():
                flag = ' *' if s['significant'] else ''
                print(f"    IC {c:13} {str(s['ic']):>8}  t={str(s['t_stat']):>6}  "
                      f"n={s['n']} (eff. {s['n_effective']}){flag}")
            base = m['baseline_always_long']
            print(f"    Always long:     mean {base['mean_return_pct']}%  up {base['up_rate_pct']}%  n={base['n']}")
            for label, c in m['combined_signal_classes'].items():
                print(f"    {label:5} n={c['n']:4}  mean {c['mean_return_pct']}%  hit {c['hit_rate_pct']}%")
            print(f"    Folds with positive combined IC: {m['folds_with_positive_ic']}")
            print("    Cross-sectional IC (mean over dates, ranking tickers against each other):")
            for c, x in m['ic_cross_sectional'].items():
                flag = ' *' if x['significant'] else ''
                print(f"      {c:13} {str(x['mean_ic']):>8}  t={str(x['t_stat']):>6}  "
                      f"dates={x['n_dates']}{flag}")


def latest_summary(path=None):
    """Walk-forward block for the daily report, from the last saved run."""
    path = path or reports_dir() / RESULTS_FILE
    if not path.exists():
        return {'status': DATA_UNAVAILABLE,
                'reason': "walk-forward not run yet: run 'python main.py walkforward'"}
    data = json.loads(path.read_text(encoding='utf-8'))
    age = datetime.now(timezone.utc) - datetime.fromisoformat(data['computed_at'])
    summary = {
        'status': data.get('status', DATA_UNAVAILABLE),
        'method': data.get('method'),
        'computed_at': data['computed_at'],
        'stale': age > timedelta(days=STALE_AFTER_DAYS),
        'excluded': data.get('protocol', {}).get('excluded'),
        'n_tickers': len(data.get('universe') or []),
        'horizons': {h: {'ic_pooled': {c: s['ic'] for c, s in m['ic_pooled'].items()},
                         'ic_cross_sectional': {c: s['mean_ic'] for c, s in
                                                m.get('ic_cross_sectional', {}).items()},
                         'significant_cross_sectional': [c for c, s in m.get('ic_cross_sectional', {}).items()
                                                         if s['significant']],
                         'significant': [c for c, s in m['ic_pooled'].items() if s['significant']],
                         'buy_excess_vs_baseline_pct': m['buy_excess_vs_baseline_pct'],
                         'model_oos_ic': ((data.get('model') or {}).get(h) or {}).get('model_oos', {})
                         .get('ic', {}).get('mean'),
                         'model_oos_significant': ((data.get('model') or {}).get(h) or {})
                         .get('model_oos', {}).get('ic', {}).get('significant', False),
                         'folds_with_positive_ic': m['folds_with_positive_ic']}
                     for h, m in data.get('metrics', {}).items()},
    }
    if summary['stale']:
        summary['reason'] = f"last run {age.days} days ago: rerun 'python main.py walkforward'"
    return summary


if __name__ == "__main__":
    WalkForward().run()
