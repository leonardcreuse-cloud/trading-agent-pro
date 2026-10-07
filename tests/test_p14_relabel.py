"""
Phase P1.4 - signals relabelled: quantitative signals, never trade recommendations (offline).
"""

import re
from datetime import datetime, timedelta, timezone

import pytest
import yfinance

from tests.conftest import make_price_frame

TRADE_WORDS = re.compile(r'\b(BUY|SELL|HOLD|STRONG BUY|recommendation to)\b')


def wf_summary(t_by_h, ic_by_h=None, stale=False):
    ic_by_h = ic_by_h or {h: 0.02 for h in t_by_h}
    return {'status': 'OK', 'computed_at': '2026-10-07T09:00:00+00:00', 'stale': stale,
            'n_tickers': 40, 'excluded': {'news': 'no history'},
            'horizons': {h: {'ic_cross_sectional': {'combined': ic_by_h[h]},
                             'ic_cross_sectional_t': {'combined': t}} for h, t in t_by_h.items()}}


def test_two_sided_p_value():
    from src.scoring_signal_fixed import two_sided_p
    assert two_sided_p(1.96) == pytest.approx(0.05, abs=1e-3)
    assert two_sided_p(0) == 1.0


def test_validation_not_demonstrated_for_insignificant_ic():
    from src.scoring_signal_fixed import validation_status
    v = validation_status(wf_summary({'5d': 0.79, '20d': 0.80}))
    assert v['status'] == 'NOT DEMONSTRATED' and v['demonstrated'] is False
    assert 'NOT demonstrated statistically significant predictive power' in v['statement']
    assert 'Bonferroni' in v['statement']


def test_validation_uses_bonferroni_over_horizons():
    from src.scoring_signal_fixed import validation_status
    # t = 2.1 -> p ~ 0.036: significant alone, not after correction for 2 horizons (p < 0.025)
    assert validation_status(wf_summary({'5d': 2.1}))['demonstrated'] is True
    assert validation_status(wf_summary({'5d': 2.1, '20d': 0.5}))['demonstrated'] is False
    assert validation_status(wf_summary({'5d': 3.5, '20d': 0.5}))['demonstrated'] is True


def test_validation_rejects_negative_ic_and_stale_runs():
    from src.scoring_signal_fixed import validation_status
    assert validation_status(wf_summary({'5d': -4.0}, {'5d': -0.05}))['demonstrated'] is False
    stale = validation_status(wf_summary({'5d': 4.0}, stale=True))
    assert stale['demonstrated'] is False and 'stale' in stale['statement']


def test_validation_without_walk_forward():
    from src.scoring_signal_fixed import validation_status
    v = validation_status({'status': 'DATA UNAVAILABLE', 'reason': "run 'python main.py walkforward'"})
    assert v['status'] == 'NOT VALIDATED' and 'NOT demonstrated' in v['statement']


def test_signal_labels_are_directions_not_actions():
    from src.scoring_signal_fixed import ScoringSignalFixed
    s = ScoringSignalFixed()
    assert {s.generate_final_signal(x) for x in (80, 50, 20)} == {'POSITIVE', 'NEUTRAL', 'NEGATIVE'}
    out = s.analyze('MP', {'technical_score': 80}, {'fundamental_score': 80}, {}, {})
    assert out['quantitative_signal'] == 'POSITIVE' and out['signal_strength'] == 80.0
    assert 'not a trade recommendation' in out['disclaimer']
    assert 'recommendation' not in out and 'signal' not in out


def test_reports_contain_no_trade_words_and_state_validation(monkeypatch, tmp_path):
    from src.integration import Integration
    monkeypatch.setattr(yfinance, 'download', lambda *a, **k: make_price_frame(500))
    results = Integration().run_daily_batch()
    sig = results[0]['modules']['signal']
    for key in ('model_prediction', 'prediction_confidence', 'risk_score'):
        assert sig[key]['status'] == 'NOT IMPLEMENTED' and sig[key]['reason']
    assert sig['data_reliability']['coverage'] == sig['coverage']
    html = (tmp_path / 'reports' / 'analysis.html').read_text(encoding='utf-8')
    dashboard = (tmp_path / 'reports' / 'dashboard.html').read_text(encoding='utf-8')
    for text in (html, dashboard):
        assert not TRADE_WORDS.search(text), TRADE_WORDS.search(text)
        assert 'P(up)' not in text
    assert 'Predictive power NOT demonstrated' in html
    assert 'Quantitative assessment (not a trade recommendation)' in html
    assert 'Prediction confidence' in html and 'Risk score' in html
