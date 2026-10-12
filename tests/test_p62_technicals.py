"""
Master mission P2: reference technical indicators and price-action rules (src/technicals.py).

Price series below are textbook examples or SYNTHETIC series built for one property (logic tests only).
"""

import math

import numpy as np
import pandas as pd
import pytest

from src import technicals as ta

# Classic RSI example closes (Wilder's method as illustrated in StockCharts' ChartSchool)
RSI_CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
              46.28, 46.00, 46.03, 46.41, 46.22, 45.64]


def series(values, start='2026-01-01'):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_rsi_wilder_first_value_by_hand_and_recursion():
    s = series(RSI_CLOSES)
    r = ta.rsi(s)
    assert r.iloc[:14].isna().all()                            # warm-up: undefined, never a default
    # first 14 changes: gains sum 3.34 -> 0.238571, losses sum 1.40 -> 0.1
    assert r.iloc[14] == pytest.approx(100 - 100 / (1 + 3.34 / 1.40), abs=1e-9)
    g, l = 3.34 / 14, 1.40 / 14
    for i in range(15, len(RSI_CLOSES)):
        d = RSI_CLOSES[i] - RSI_CLOSES[i - 1]
        g, l = (g * 13 + max(d, 0)) / 14, (l * 13 + max(-d, 0)) / 14
        assert r.iloc[i] == pytest.approx(100 - 100 / (1 + g / l), abs=1e-9)
    assert ta.rsi(series(range(1, 30))).iloc[-1] == 100.0      # gains only: 100 (Wilder), not 50
    assert math.isnan(ta.rsi(series([10.0] * 30)).iloc[-1])   # flat: undefined


def test_ema_seeded_and_sma_windows():
    s = series([1, 2, 3, 4, 5, 6.0])
    e = ta.ema(s, 3)
    assert e.iloc[:2].isna().all() and e.iloc[2] == 2.0       # seed = SMA of the first 3
    assert e.iloc[3] == pytest.approx(0.5 * 4 + 0.5 * 2.0) and e.iloc[5] == pytest.approx(0.5 * 6 + 0.5 * e.iloc[4])
    assert ta.sma(s, 3).iloc[2] == 2.0 and math.isnan(ta.sma(s, 3).iloc[1])


def test_bollinger_population_sd_and_hist_vol():
    s = series(np.linspace(10, 20, 40) + np.sin(np.arange(40)))
    b = ta.bollinger(s)
    window = s.iloc[-20:].to_numpy()
    assert b['upper'].iloc[-1] == pytest.approx(window.mean() + 2 * window.std(ddof=0))
    assert b['pct_b'].iloc[-1] == pytest.approx((s.iloc[-1] - b['lower'].iloc[-1]) / (b['upper'].iloc[-1] - b['lower'].iloc[-1]))
    logs = np.diff(np.log(s.to_numpy()))[-20:]
    assert ta.hist_vol(s, 20).iloc[-1] == pytest.approx(logs.std(ddof=1) * math.sqrt(252))


def test_atr_by_hand():
    high, low, close = series([10, 11, 12, 11.5, 13.0]), series([9, 10, 10.5, 10, 11.0]), series([9.5, 10.5, 11.5, 10.5, 12.5])
    a = ta.atr(high, low, close, n=3)
    # TR of bars 1-4: max(1, |11-9.5|, |10-9.5|) = 1.5; max(1.5, |12-10.5|, 0) = 1.5; max(1.5, 0, |10-11.5|) = 1.5;
    # max(2, |13-10.5|, |11-10.5|) = 2.5
    assert a.iloc[3] == pytest.approx((1.5 + 1.5 + 1.5) / 3)
    assert a.iloc[4] == pytest.approx((a.iloc[3] * 2 + 2.5) / 3)


def test_adx_bounded_and_strong_on_a_steady_trend():
    n = 120
    close = series(100 + np.arange(n) * 1.0)
    d = ta.adx(close + 0.5, close - 0.5, close)
    assert d['adx'].dropna().between(0, 100).all() and d['adx'].iloc[-1] > 25
    assert d['plus_di'].iloc[-1] > d['minus_di'].iloc[-1]


def test_momentum_drawdown_relative_volume_and_strength():
    s = series([100, 110, 99, 120.0])
    assert ta.momentum(s, 2).iloc[-1] == pytest.approx(120 / 110 - 1)
    assert ta.drawdown(s).iloc[2] == pytest.approx(99 / 110 - 1)
    v = series([10.0] * 20 + [30.0])
    assert ta.relative_volume(v).iloc[-1] == 3.0
    b = series([50, 50, 50, 55.0])
    assert ta.relative_strength(s, b, 3) == pytest.approx(1.2 / 1.1 - 1)


def test_pivots_are_only_known_k_bars_later_and_levels_cluster():
    highs = [1, 2, 3, 4, 5, 9, 5, 4, 3, 2, 1, 2, 3]
    high = series(highs)
    low = high - 0.5
    assert any(p[1] == 'high' and p[2] == 9 for p in ta.pivots(high, low, k=3))
    assert not any(p[2] == 9 for p in ta.pivots(high, low, k=3, known_upto=7))   # i = 5 needs bar 8
    ls = ta.levels([('d1', 'high', 100.0), ('d2', 'high', 100.4), ('d3', 'low', 90.0)], tolerance=0.5)
    assert [(round(x['level'], 2), x['touches']) for x in ls] == [(90.0, 1), (100.2, 2)]


def test_candles():
    assert ta.candle(10, 11, 9, 10.05) == ['doji']
    assert 'bullish engulfing' in ta.candle(9.5, 11.2, 9.4, 11.0, prev=(10.5, 9.8))
    assert 'hammer' in ta.candle(10.0, 10.25, 8.0, 10.2)
    assert ta.candle(10, 10, 10, 10) == []                       # no range: nothing


def test_analyze_reports_what_it_cannot_compute():
    idx = pd.bdate_range('2024-01-01', periods=300)
    close = pd.Series(100 + np.sin(np.arange(300) / 10) * 5 + np.arange(300) * 0.05, index=idx)
    frame = pd.DataFrame({'close': close, 'volume': 1e6})
    out = ta.analyze(frame, bench=close * 0.5)
    assert out['values']['sma200'] is not None and out['values']['rs_3m'] == pytest.approx(0.0, abs=1e-9)
    assert out['values'].get('atr14') is None and any('open / high / low' in m for m in out['missing'])
    full = frame.assign(open=close.shift(1).fillna(close), high=close + 1, low=close - 1)
    res = ta.analyze(full, bench=close)
    assert res['values']['atr14'] is not None and 'trend' in res['price_action']
    assert res['price_action']['volatility_regime']['n'] >= 252 or 'volatility_regime' not in res['price_action']
    assert set(res['not_implemented']) == {'Dow theory', 'Elliott waves', 'Smart Money Concepts / ICT'}


# ---------------------------------------------------------------- market data validation (audit)

def test_bar_checks_and_split_cross_check(monkeypatch):
    import yfinance
    from src.database import Database
    from src.pipeline_audit import PipelineAudit
    db = Database()
    rows = [{'entity': 'AAA', 'metric': 'dei:SharesOutstanding', 'as_of_date': d, 'value': v, 'unit': 'shares',
             'published_at': f'{d}T21:00:00+00:00', 'published_at_basis': 'test'}
            for d, v in (('2025-05-01', 100.0), ('2025-08-01', 101.0), ('2025-11-01', 404.0), ('2026-02-01', 800.0))]
    db.upsert_observations(db.record_fetch('SEC EDGAR', 'test:dei', status='OK'), rows)

    class Ticker:
        def __init__(self, t):
            self.splits = pd.Series([4.0], index=pd.to_datetime(['2025-10-01']))
    monkeypatch.setattr(yfinance, 'Ticker', Ticker)
    audit = PipelineAudit(db=db)
    c = audit.split_check('AAA')
    assert c['status'] == 'WARN' and len(c['evidence']) == 1                  # 2025-11 -> 2026-02 x1.98 unexplained
    assert c['evidence'][0].startswith('2025-11-01 -> 2026-02-01')

    idx = pd.bdate_range('2026-01-01', periods=6)
    frame = pd.DataFrame({'close': [10, 10, 10, 10, 10, 10.0], 'open': [10, 10, 10, 10, 10, 10.0],
                          'high': [11, 11, 9.0, 11, 11, 11], 'low': [9, 9, 9, 9, 9, 9.0],
                          'volume': [1, 1, 0, 1, 1, 1.0], 'close_raw': [10, 10, 10, 10, 10.5, 10.5]}, index=idx)
    spy = pd.Series([1.0] * 7, index=pd.bdate_range('2026-01-01', periods=7))
    monkeypatch.setattr(audit.prices, 'get', lambda t: {'status': 'OK', 'close': spy} if t == 'SPY' else None)
    checks = {x['check'].split(' (')[0]: x for x in audit.bar_checks('AAA', {'frame': frame})}
    assert checks['OHLC consistency']['detail'].startswith('1 of 6')            # high 9 < close 10
    assert checks['sessions missing against the SPY calendar']['detail'] == '1 sessions'
    assert checks['zero or missing volume']['detail'] == '1 sessions'
    assert checks['adjusted / unadjusted ratio jumps > 2%']['status'] == 'WARN'


def test_split_check_classifies_restated_counts_outliers_and_small_adjustments(monkeypatch):
    import yfinance
    from src.database import Database
    from src.pipeline_audit import PipelineAudit
    db = Database()
    # cover dates / filing dates: 2:1 split on 2025-07-10 reported in a filing made after it (cover date 07-01);
    # one filing in thousands (2025-11-01); a 1.03 spin-off adjustment in yfinance (no share-count change)
    counts = (('2025-01-01', 100.0, '2025-01-20'), ('2025-04-01', 101.0, '2025-04-20'),
              ('2025-07-01', 202.0, '2025-07-25'), ('2025-11-01', 202000.0, '2025-11-20'),
              ('2026-02-01', 203.0, '2026-02-20'), ('2026-05-01', 204.0, '2026-05-20'))
    rows = [{'entity': 'AAA', 'metric': 'dei:SharesOutstanding', 'as_of_date': d, 'value': v, 'unit': 'shares',
             'published_at': f'{p}T21:00:00+00:00', 'published_at_basis': 'test'} for d, v, p in counts]
    db.upsert_observations(db.record_fetch('SEC EDGAR', 'test:dei', status='OK'), rows)

    class Ticker:
        def __init__(self, t):
            self.splits = pd.Series([2.0, 1.03], index=pd.to_datetime(['2025-07-10', '2026-03-02']))
    monkeypatch.setattr(yfinance, 'Ticker', Ticker)
    c = PipelineAudit(db=db).split_check('AAA')
    assert c['status'] == 'WARN' and c['evidence'] == [
        '2025-11-01: x1000.00, then x0.00 at the next filing (one-filing outlier in the SEC data, not a split)']
    assert c['detail'].startswith('1 share-count jump(s), 1 yfinance split(s) of 40% or more (1 smaller')
    assert '0 not matched; 1 one-filing outlier(s)' in c['detail']


def test_audit_runs_the_split_check_after_the_sec_checks(monkeypatch):
    # the SEC checks refresh the company facts (cover-page share counts) that the split cross-check reads
    from src.pipeline_audit import PipelineAudit, check
    audit = PipelineAudit()
    calls = []
    singles = ('split_check', 'second_source_check', 'identifier_check')
    for name in ('price_checks', 'sec_checks', 'label_checks', 'insider_checks') + singles:
        def record(ticker, name=name):
            calls.append(name)
            return check(name, 'PASS', '') if name in singles else []
        monkeypatch.setattr(audit, name, record)
    monkeypatch.setattr(audit, 'storage_checks', lambda: [])
    monkeypatch.setattr(audit, 'walk_forward_checks', lambda: [])
    audit.run(['AAA'])
    assert calls == ['price_checks', 'sec_checks', 'split_check', 'second_source_check', 'identifier_check',
                     'label_checks', 'insider_checks']


def test_option_skew_and_term_structure():
    from src import external_sources as ex

    def chain(call_iv, put_iv):
        strikes = [90.0, 100.0, 110.0]
        calls = pd.DataFrame({'strike': strikes, 'bid': [1.0] * 3, 'ask': [1.2] * 3, 'impliedVolatility': call_iv,
                              'openInterest': [10] * 3, 'volume': [1] * 3})
        puts = calls.assign(impliedVolatility=put_iv)
        return calls, puts
    c1, p1 = chain([0.30, 0.25, 0.22], [0.40, 0.27, 0.24])          # 30 days
    c2, p2 = chain([0.32, 0.29, 0.27], [0.42, 0.31, 0.29])          # 58 days
    snap = ex.option_snapshot([('e30', c1, p1), ('e58', c2, p2)], 100.0, {'e30': 30, 'e58': 58})
    assert snap['skew_90_110'] == pytest.approx(0.40 - 0.22)
    assert [t[0] for t in snap['term_structure']] == [30, 58]
    assert snap['term_slope'] == pytest.approx((0.29 + 0.31) / 2 - (0.25 + 0.27) / 2)
    far = ex.option_snapshot([('e30', c1, p1)], 150.0, {'e30': 30})     # nearest strike 110 is > 5% from 150
    assert far['atm_iv'] is None and far['skew_90_110'] is None and far['term_slope'] is None


# ---------------------------------------------------------------- news events and the de-weighted lexicon

def test_news_event_classes_and_materiality():
    from src.weekly.sections.news import classify, materiality
    c = classify('CrowdStrike reports quarterly results, raises full-year outlook')
    assert [k for k, _ in c] == ['earnings / results', 'guidance'] and materiality(c) == 'high'
    assert materiality(classify('Analyst upgrades Cloudflare, sets new price target')) == 'medium'
    assert materiality(classify('Why Rocket Lab stock soars today')) == 'low'
    assert classify('A quiet day') == [] and materiality([]) == 'unclassified'
    assert classify('Sharesight launches') == [('product / contract', ['launches'])]     # word boundary on 'shares'


def test_lexicon_is_descriptive_only_in_the_combined_signal():
    from src.scoring_signal_fixed import ScoringSignalFixed
    a = ScoringSignalFixed().analyze('X', {'technical_score': 60}, {'fundamental_score': 70}, {'news_score': 100},
                                     {'insider_score': 40})
    b = ScoringSignalFixed().analyze('X', {'technical_score': 60}, {'fundamental_score': 70}, {'news_score': 0},
                                     {'insider_score': 40})
    assert a['signal_strength'] == b['signal_strength'] and 'news' not in a['component_scores']


def test_retracement_of_the_last_swing():
    from src.technicals import retracement
    pts = [(pd.Timestamp('2026-01-05'), 'low', 100.0), (pd.Timestamp('2026-02-02'), 'high', 150.0)]
    up = retracement(pts, 125.0)
    assert up['leg'] == 'up' and up['retraced_pct'] == 50.0 and up['from'][1] == 100.0 and up['to'][1] == 150.0
    down = retracement(pts + [(pd.Timestamp('2026-03-02'), 'low', 110.0)], 120.0)
    assert down['leg'] == 'down' and down['retraced_pct'] == 25.0                      # (120 - 110) / (150 - 110)
    assert retracement(pts, 90.0)['retraced_pct'] == 120.0                             # beyond the leg's start
    assert retracement(pts[:1], 100.0) is None and retracement([], 1.0) is None
