"""
Phase P1.2 - walk-forward validation (offline).

Synthetic prices / SEC documents only check the protocol: no look-ahead, entry at the
next session, overlap-adjusted statistics, insider coverage and the daily-report summary.
"""

import json
from datetime import datetime, timedelta, timezone

import yfinance

from tests.conftest import make_price_frame
from tests.test_p03_sec_fundamentals_insider import add_form4, form4_xml, sec  # noqa: F401 - fixture


def frame_with_future_change(n=400, seed=1, change_from=None):
    frame = make_price_frame(n, seed=seed)
    if change_from is not None:
        frame.iloc[change_from:, 0] = frame.iloc[change_from:, 0] * 3   # rewrite the "future"
    return frame


def walk_forward(monkeypatch, frame):
    from src.walk_forward import WalkForward
    monkeypatch.setattr(yfinance, 'download', lambda *a, **k: frame)
    return WalkForward()


# ---------------------------------------------------------------- statistics

def test_spearman_handles_ties_and_constant_series():
    from src.walk_forward import spearman
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert spearman([50, 50, 50, 50], [1, 2, 3, 4]) is None        # constant score: undefined
    assert spearman([1, None, 3], [1, 2, None]) is None              # < 3 complete pairs


def test_ic_t_stat_uses_overlap_adjusted_sample_size():
    from src.walk_forward import ic_stats
    scores, returns = list(range(100)), [x + (7 if x % 2 else -7) for x in range(100)]
    short, long_ = ic_stats(scores, returns, horizon=5), ic_stats(scores, returns, horizon=20)
    assert short['n'] == long_['n'] == 100
    assert short['n_effective'] == 100 and long_['n_effective'] == 25
    assert abs(long_['t_stat']) < abs(short['t_stat'])


def test_negative_signal_hit_rate_counts_negative_returns():
    from src.walk_forward import class_stats
    rows = [{'signal': 'NEGATIVE', 'r': -0.01}, {'signal': 'NEGATIVE', 'r': 0.02},
            {'signal': 'POSITIVE', 'r': 0.03}]
    stats = class_stats(rows, 'r')
    assert stats['NEGATIVE'] == {'n': 2, 'mean_return_pct': 0.5, 'hit_rate_pct': 50.0}
    assert stats['POSITIVE']['hit_rate_pct'] == 100.0 and stats['NEUTRAL']['n'] == 0


def test_evaluate_reports_baseline_folds_and_excess():
    from src.walk_forward import evaluate
    samples = []
    for i, day in enumerate(['2024-01-10', '2024-02-10', '2024-03-10', '2024-08-10', '2024-09-10', '2024-10-10']):
        samples.append({'ticker': 'MP', 'date': day, 'technical': i, 'fundamentals': None,
                        'insider': 50, 'combined': i, 'signal': 'POSITIVE' if i >= 3 else 'NEUTRAL',
                        'fwd_5d': 0.01 * i, 'fwd_20d': None})
    m = evaluate(samples, horizons=(5, 20))
    assert m['5d']['ic_pooled']['combined']['ic'] == 1.0
    assert m['5d']['ic_pooled']['insider']['ic'] is None
    assert m['5d']['baseline_always_long']['mean_return_pct'] == 2.5
    assert m['5d']['positive_excess_vs_baseline_pct'] == 1.5
    assert set(m['5d']['folds']) == {'2024H1', '2024H2'}
    assert m['20d']['baseline_always_long']['n'] == 0


# ---------------------------------------------------------------- protocol

def test_scores_never_use_future_prices(monkeypatch):
    base = walk_forward(monkeypatch, frame_with_future_change()).samples('MP')[0]
    cut = 300
    changed = walk_forward(monkeypatch, frame_with_future_change(change_from=cut)).samples('MP')[0]
    frame = make_price_frame(400, seed=1)
    cut_date = frame.index[cut].date().isoformat()
    before = [(a, b) for a, b in zip(base, changed) if a['date'] < cut_date]
    assert before and all(a['technical'] == b['technical'] for a, b in before)
    assert any(a['technical'] != b['technical'] for a, b in zip(base, changed) if a['date'] >= cut_date)


def test_entry_is_next_session_and_dates_are_weekly(monkeypatch):
    from src.walk_forward import ENTRY_LAG, MIN_HISTORY, STEP
    frame = make_price_frame(400, seed=2)
    rows, _ = walk_forward(monkeypatch, frame).samples('MP')
    close = frame.iloc[:, 0].to_numpy()
    dates = [d.date().isoformat() for d in frame.index]
    first = rows[0]
    i = MIN_HISTORY - 1
    assert first['date'] == dates[i] and first['entry_date'] == dates[i + ENTRY_LAG]
    assert abs(first['fwd_5d'] - (close[i + 1 + 5] / close[i + 1] - 1)) < 1e-12
    assert rows[1]['date'] == dates[i + STEP]
    assert rows[-1]['fwd_20d'] is None                              # outcome not known yet


def test_without_sec_only_technical_is_available_so_no_combined_signal(monkeypatch):
    rows, info = walk_forward(monkeypatch, make_price_frame(300)).samples('MP')
    assert all(r['fundamentals'] is None and r['insider'] is None for r in rows)
    assert all(r['combined'] is None and r['signal'] == 'INSUFFICIENT DATA' for r in rows)
    assert info['insider_coverage'] is None


def test_fundamentals_and_insider_are_point_in_time(monkeypatch, sec):  # noqa: F811
    payloads, _ = sec
    now = datetime.now(timezone.utc)
    add_form4(payloads, [('w-1', 20, form4_xml([('P', '2026-09-01', 10, 20.0)]))])
    frame = make_price_frame(500, seed=3)
    frame.index = frame.index + (now.date() - timedelta(days=2) - frame.index[-1].date())
    wf = walk_forward(monkeypatch, frame)
    wf.history_days = 400
    rows, info = wf.samples('MP')
    assert info['insider_coverage']['n_parsed'] == 1
    filed = (now - timedelta(days=20)).isoformat()
    window_start = info['insider_coverage']['first_full_window']
    for r in rows:
        if r['known_at'] < window_start:
            assert r['insider'] is None                             # history not covered
        elif r['known_at'] < filed:
            assert r['insider'] == 50                               # covered, no purchase yet
        elif r['known_at'] <= (now - timedelta(days=20) + timedelta(days=89)).isoformat():
            assert r['insider'] == 60                               # purchase visible
    # 10-K (FY2025) public 2026-02-27, 10-Q (Q2 2026) accepted 2026-08-07 02:15 UTC
    k_window = [r for r in rows if '2026-03-01' <= r['date'] <= '2026-08-05']
    q_window = [r for r in rows if r['date'] >= '2026-08-07']
    assert k_window and q_window
    # FY2025: scale 60, growth 224.4/180 -> 70, D/E 0.49 -> 90  => 74.0
    assert all(r['fundamentals'] == 74.0 for r in k_window)
    # Q2 2026: scale 60, growth +54% -> 85, D/E 0.48 -> 90      => 79.25
    assert all(r['fundamentals'] == 79.25 for r in q_window)
    assert all(r['combined'] is not None for r in q_window)


def test_failed_form4_in_window_makes_insider_unavailable(monkeypatch):
    from src.walk_forward import WalkForward
    wf = WalkForward.__new__(WalkForward)
    coverage = {'first_full_window': '2025-01-01T00:00:00+00:00',
                'failed_at': ['2026-03-01T00:00:00+00:00']}
    assert wf._insider_at('MP', coverage, '2026-03-15T21:00:00+00:00') is None
    assert wf._insider_at('MP', coverage, '2024-06-01T21:00:00+00:00') is None
    assert wf._insider_at('MP', None, '2026-03-15T21:00:00+00:00') is None


# ---------------------------------------------------------------- outputs

def test_run_writes_results_and_daily_summary_reads_them(monkeypatch, tmp_path):
    from src.walk_forward import latest_summary
    result = walk_forward(monkeypatch, make_price_frame(300)).run(['MP'])
    saved = json.loads((tmp_path / 'reports' / 'walk_forward.json').read_text(encoding='utf-8'))
    assert saved['method'] == result['method'] and saved['protocol']['excluded']['news']
    assert len(saved['samples']) == saved['tickers']['MP']['n_dates']
    summary = latest_summary()
    assert summary['status'] == 'OK' and summary['stale'] is False
    assert set(summary['horizons']) == {'5d', '20d'}


def test_daily_summary_missing_or_stale(tmp_path):
    from src.walk_forward import latest_summary
    path = tmp_path / 'wf.json'
    missing = latest_summary(path)
    assert missing['status'] == 'DATA UNAVAILABLE' and 'main.py walkforward' in missing['reason']
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    path.write_text(json.dumps({'status': 'OK', 'computed_at': old, 'metrics': {}}), encoding='utf-8')
    stale = latest_summary(path)
    assert stale['stale'] is True and 'rerun' in stale['reason']


# ---------------------------------------------------------------- P1.2b: wider universe

def test_cross_sectional_ic_ranks_tickers_within_each_date():
    from src.walk_forward import cross_sectional_ic
    rows = []
    for d, day in enumerate(['2024-01-05', '2024-01-12', '2024-01-19', '2024-01-26']):
        for t in range(12):
            # score ranks tickers perfectly on every date, while the market moves by date
            rows.append({'date': day, 'ticker': f'T{t}', 'combined': t, 'r': 0.001 * t + 0.05 * d})
    x = cross_sectional_ic(rows, 'combined', 'r', horizon=5)
    assert x['n_dates'] == 4 and x['mean_ic'] == 1.0 and x['positive_dates_pct'] == 100.0
    assert cross_sectional_ic(rows[:5], 'combined', 'r', horizon=5)['mean_ic'] is None  # < 10 tickers


def test_failing_ticker_is_reported_and_others_still_evaluated(monkeypatch):
    from src.walk_forward import WalkForward
    wf = walk_forward(monkeypatch, make_price_frame(300))
    original = WalkForward.samples

    def flaky(self, ticker):
        if ticker == 'BAD':
            raise RuntimeError('boom')
        return original(self, ticker)
    monkeypatch.setattr(WalkForward, 'samples', flaky)
    result = wf.run(['BAD', 'MP'])
    assert result['tickers']['BAD']['status'] == 'DATA UNAVAILABLE'
    assert 'boom' in result['tickers']['BAD']['reason']
    assert result['tickers']['MP']['status'] == 'OK' and result['universe'] == ['BAD', 'MP']


def test_validation_universe_comes_from_config():
    from src.common import tickers, validation_universe
    universe = validation_universe()
    assert set(tickers()) <= set(universe) and len(universe) >= 30


def test_sec_prefetch_downloads_in_parallel_under_rate_limit(monkeypatch, sec):  # noqa: F811
    from src import sec_parser
    from src.sec_parser import IMMUTABLE, SECParser
    payloads, calls = sec
    for i in range(6):
        payloads[f'doc{i}.xml'] = f'<x>{i}</x>'
    starts = []
    real_throttle = sec_parser._throttle
    monkeypatch.setattr(sec_parser, '_throttle', lambda: (real_throttle(), starts.append(1)))
    parser = SECParser()
    urls = [f'https://www.sec.gov/doc{i}.xml' for i in range(6)]
    downloads = parser.prefetch(urls, as_json=False, max_age=IMMUTABLE)
    assert set(downloads) == set(urls) and len(starts) == 6       # every request throttled
    for url in urls:
        assert parser._get(url, as_json=False, max_age=IMMUTABLE, prefetched=downloads[url])
    assert parser.prefetch(urls, as_json=False, max_age=IMMUTABLE) == {}   # all reusable now
    assert sum(u.endswith('.xml') for u in calls) == 6
