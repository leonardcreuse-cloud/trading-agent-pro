"""Phase P2.2 - stage 2 holdout, insider history and confirmatory tests (offline)."""

import pytest


def history(**kw):
    base = {'transactions': [], 'failed_at': [], 'coverage_start': '2016-06-01', 'n_filings': 0, 'n_parsed': 0}
    base.update(kw)
    return base


def txn(when, code, value, owner='A', planned=False):
    return {'published_at': when, 'code': code, 'value_usd': value, 'insider': owner, 'planned': planned}


def test_insider_features_window_and_planned_sales():
    from src.research.insider_history import insider_features_at
    h = history(transactions=[
        txn('2026-01-10T21:00:00+00:00', 'P', 1_000_000.0, 'A'),
        txn('2026-02-01T21:00:00+00:00', 'S', 300_000.0, 'B'),
        txn('2026-02-02T21:00:00+00:00', 'S', 5_000_000.0, 'C', planned=True),   # planned: ignored
        txn('2025-09-01T21:00:00+00:00', 'P', 9_000_000.0, 'D')])                 # outside window
    f = insider_features_at(h, '2026-03-01T21:00:00+00:00', 1e9)
    assert f == {'insider_buyers_90d': 1.0, 'insider_net_buy_to_mcap': pytest.approx(700_000 / 1e9),
                 'insider_disc_sellers_90d': 1.0}
    assert insider_features_at(h, '2026-03-01T21:00:00+00:00', None)['insider_net_buy_to_mcap'] is None


def test_insider_features_unavailable_when_window_not_covered_or_failed():
    from src.research.insider_history import insider_features_at
    early = insider_features_at(history(coverage_start='2021-03-01'), '2021-04-01T21:00:00+00:00', 1e9)
    assert all(v is None for v in early.values())
    failed = insider_features_at(history(failed_at=['2026-02-15T21:00:00+00:00']), '2026-03-01T21:00:00+00:00', 1e9)
    assert all(v is None for v in failed.values())
    ok = insider_features_at(history(), '2026-03-01T21:00:00+00:00', 1e9)
    assert ok['insider_buyers_90d'] == 0.0                       # covered window, no purchase observed
    assert all(v is None for v in insider_features_at({'error': 'x'}, '2026-03-01T21:00:00+00:00', 1e9).values())


def test_holm_known_values():
    from src.research.experiment import holm
    tests = holm([{'p_value': 0.01}, {'p_value': 0.04}, {'p_value': 0.03}, {'p_value': 0.005}], 0.05)
    assert [t['p_holm'] for t in tests] == [0.03, 0.06, 0.06, 0.02]
    assert [t['rejected'] for t in tests] == [True, False, False, True]


def test_holdout_never_overlaps_stage_1():
    from src.research.experiment import STAGES, Study
    from src.research.universe import Universe
    rows = [{'ticker': f'T{i:03d}', 'yahoo_ticker': f'T{i:03d}', 'name': '', 'sector': 'Industrials',
             'sub_industry': '', 'date_added': None, 'cik': str(i).zfill(10)} for i in range(400)]
    u = Universe.__new__(Universe)
    u.rows = rows
    stage1 = {m['ticker'] for m in u.stage(STAGES[1])}
    holdout = {m['ticker'] for m in Study.__new__(Study).members.__func__(type('S', (), {'stage': 2})(), u)}
    assert len(stage1) == 150 and len(holdout) == 250 and not stage1 & holdout


def test_confirmatory_family_is_preregistered():
    from src.research.factors import CONFIRMATORY, INSIDER_FEATURES, features_for
    assert [c[0] for c in CONFIRMATORY] == ['C1', 'C2', 'C3', 'C4']
    assert set(INSIDER_FEATURES) <= set(features_for(2)) and not set(INSIDER_FEATURES) & set(features_for(1))


def test_joint_filers_count_as_one_insider(monkeypatch):
    from src.research import insider_history
    from src.research.insider_history import InsiderHistory, insider_features_at
    doc = {'owners': [{'name': 'Fund GP', 'cik': '1'}, {'name': 'Fund LP', 'cik': '2'}, {'name': 'Partner', 'cik': '3'}],
           'rule_10b5_1': False,
           'transactions': [{'code': 'P', 'value_usd': 100.0}, {'code': 'P', 'value_usd': 50.0}]}
    h = InsiderHistory.__new__(InsiderHistory)
    filing = {'form': '4', 'accession_number': 'a-1', 'primary_document': 'x/f.xml',
              'published_at': '2026-02-01T21:00:00+00:00', 'published_at_basis': 'acceptance'}
    monkeypatch.setattr(InsiderHistory, 'filings', lambda self, cik: ([filing], '2016-06-01'))
    class FakeSec:
        def prefetch(self, *a, **k): return {}
        def _get(self, *a, **k): return '<xml/>'
    h.sec = FakeSec()
    monkeypatch.setattr(insider_history, 'parse_form4', lambda text: doc)
    loaded = h.load('0000000009')
    f = insider_features_at(loaded, '2026-03-01T21:00:00+00:00', 1e4)
    assert f['insider_buyers_90d'] == 1.0 and f['insider_net_buy_to_mcap'] == pytest.approx(0.015)
