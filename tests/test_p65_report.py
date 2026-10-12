"""
Master mission P5: report structure (22 parts), critical-section status, and the regime, data-quality, track-record
and synthesis sections. All inputs are SYNTHETIC (logic tests only).
"""

import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from src.weekly.core import TimeModel

SESSIONS = [d.date().isoformat() for d in pd.bdate_range(end='2026-10-09', periods=400)]
CUTOFF = '2026-10-10T12:00:00+00:00'           # s_0 = 2026-10-09, T_c = 2026-10-10T05:00Z


class Ctx:
    def __init__(self, universe=('AAA',)):
        from src.database import Database
        self.tm = TimeModel(SESSIONS, CUTOFF, CUTOFF)
        self.universe, self.weekly, self.config = list(universe), {'benchmark': 'SPY'}, {}
        self.db = Database()
        self.sec = None

    def prices(self, t):
        idx = pd.bdate_range(end='2026-10-09', periods=300)
        close = pd.Series(100 + np.arange(300) * 0.2, index=idx)
        frame = pd.DataFrame({'close': close, 'open': close, 'high': close + 1, 'low': close - 1, 'volume': 1e6})
        return {'status': 'OK', 'frame': frame, 'fetch': {'fetch_id': 1, 'retrieved_at': '2026-10-10T01:00:00+00:00'}}

    def fred(self, sid):
        return {'status': 'OK', 'fetch': {'fetch_id': 2, 'retrieved_at': '2026-10-10T01:00:00+00:00'}}

    def series_at(self, sid, instant):
        days = SESSIONS[-300:]
        base = {'VIXCLS': 15.0, 'BAMLH0A0HYM2': 3.0, 'T10Y2Y': -0.2, 'DFII10': 1.5}[sid]
        return [(d, base + i * (0.02 if sid == 'DFII10' else 0.0)) for i, d in enumerate(days)]

    def value_at(self, sid, instant):
        rows = self.series_at(sid, instant)
        return rows[-1][0], rows[-1][1], f'{rows[-1][0]}T23:00:00+00:00'

    def freshness(self, as_of, cadence, at=None):
        from src.database import freshness
        return freshness(as_of, cadence, now=datetime.fromisoformat(at or self.tm.cutoff))


# ---------------------------------------------------------------- structure and status

def test_parts_mapping():
    from src.weekly.report import PARTS, part_of
    assert len(PARTS) == 22
    assert part_of('valuation', 2, 'AAA: fundamentals (SEC XBRL, point-in-time)') == 9
    assert part_of('valuation', 2, 'AAA: valuation ratios at the close of 2026-10-09 (fundamentals known at T_c)') == 10
    assert part_of('positioning', 8, 'AAA ATM implied volatility 40%') == 16
    assert part_of('positioning', 8, 'FINRA short interest') == 15
    assert part_of('sec_events', 7, 'AAA: 3 Form 4 filing(s)') == 14
    assert part_of('macro', 5, 'unemployment') == 6 and part_of('news', 4, 'topics') == 5
    assert part_of('synthesis', 1, 'AAA: bull / base / bear scenarios') == 19
    assert part_of('synthesis', 13, 'Key uncertainties (part 22)') == 22


def test_failed_critical_section_makes_the_report_incomplete(monkeypatch):
    from src.weekly import report
    from src.weekly.sections import quant

    def boom(ctx, **kw):
        raise RuntimeError('boom')
    monkeypatch.setattr(quant, 'build', boom)
    payload, _ = report.build(ctx=Ctx(), names=('regime', 'quant'))
    assert payload['status'] == 'INCOMPLETE' and payload['failed_sections'] == ['quant']
    assert 'critical section(s) failed: quant' in payload['status_reason']
    assert [r[0] for r in payload['structure']] == list(range(1, 23))
    html = report.render_html(payload)
    assert 'Report status: INCOMPLETE' in html and '<h2>3. Market regime</h2>' in html
    ok, _ = report.build(ctx=Ctx(), names=('regime',))
    assert ok['status'] == 'COMPLETE'


# ---------------------------------------------------------------- sections

def test_regime_rules():
    from src.weekly.sections import regime
    out = regime.build(Ctx()).as_dict()
    rows = {r[0]: r for r in out['tables'][0]['rows']}
    assert rows['trend'][2] == 'up' and rows['yield curve (10y - 2y)'][2] == 'inverted'
    assert rows['real yield (10y TIPS)'][2] == 'rising'                 # 0.02 x 21 = +0.42 pp > 0.25
    assert rows['credit (high-yield spread)'][2] == 'stable'
    assert out['conclusions'][0]['kind'] == 'interpretation'


def test_data_quality_counts_sources_audit_and_failed_sections(tmp_path):
    from src.weekly.sections import data_quality
    ctx = Ctx()
    ok = ctx.db.record_fetch('BLS', 'x', status='OK')
    bad = ctx.db.record_fetch('EIA', 'y', status='DATA UNAVAILABLE', error='HTTP 500')
    with ctx.db.connect() as conn:
        conn.execute("UPDATE source_fetches SET requested_at='2026-10-08T00:00:00+00:00', "
                     "completed_at='2026-10-08T00:00:00+00:00'")
    audit = tmp_path / 'audit.json'
    audit.write_text(json.dumps({'computed_at': '2026-10-09T10:00:00+00:00', 'status': 'WARN',
                                 'summary': {'PASS': 9, 'WARN': 1, 'FAIL': 0},
                                 'global': [{'check': 'x', 'status': 'WARN', 'detail': 'd'}], 'tickers': {}}))
    previous = [{'name': 'quant', 'conclusions': [], 'tables': [],
                 'unavailable': [{'item': 'section quant', 'reason': 'section failed: RuntimeError', 'scope': 'overall'}]}]
    out = data_quality.build(ctx, previous=previous, audit_path=audit).as_dict()
    texts = [c['statement'] for c in out['conclusions']]
    assert any('1 with at least one failure (EIA)' in t and 'no successful download in the window for EIA' in t
               for t in texts)
    assert any(t.startswith('Pipeline audit computed 2026-10-09T10:00:00+00:00: WARN') for t in texts)
    assert any('failed sections: quant' in t for t in texts)


def test_track_record_is_point_in_time(monkeypatch, tmp_path):
    from src.journal import Journal
    from src.weekly.sections import track_record
    preds = Journal('predictions')
    preds.append([{'type': 'prediction', 'id': 'p1', 'ticker': 'AAA', 'timestamp': '2026-10-03T12:00:00+00:00',
                   'signal_instant': '2026-10-02T21:00:00+00:00', 'model_output': {'rank': 1}},
                  {'type': 'prediction', 'id': 'p2', 'ticker': 'BBB', 'timestamp': '2026-10-11T12:00:00+00:00',
                   'signal_instant': '2026-10-09T21:00:00+00:00', 'model_output': {'rank': 9}},
                  {'type': 'outcome', 'id': 'o1', 'prediction_id': 'p1', 'horizon_sessions': 5, 'realised_return': 0.02,
                   'recorded_at': '2026-10-09T22:00:00+00:00'}])
    tx = Journal('transactions')
    tx.append([{'type': 'start', 'capital': 100000.0, 'created_at': '2026-10-03T12:00:00+00:00'},
               {'type': 'fill', 'side': 'buy', 'ticker': 'AAA', 'session': '2026-10-05', 'sector': '35',
                'costs': 8.0, 'price': 150.0, 'shares': 500, 'cash_out': 75008.0, 'stop': 140.0, 'notional': 75000.0},
               {'type': 'mark', 'session': '2026-10-06', 'created_at': '2026-10-06T22:00:00+00:00', 'equity': 101000.0,
                'cash': 1000.0, 'positions_value': 100000.0, 'gross_exposure_pct': 99.0,
                'positions': {'AAA': {'shares': 500, 'close': 158.0, 'stop': 150.0}},
                'bench_state': {'spy_return_pct': 0.5, 'ew_return_pct': 0.7}},
               {'type': 'mark', 'session': '2026-10-12', 'created_at': '2026-10-12T22:00:00+00:00', 'equity': 90000.0,
                'cash': 1000.0, 'positions_value': 89000.0, 'gross_exposure_pct': 99.0, 'positions': {'AAA': {}},
                'bench_state': {}}])
    out = track_record.build(Ctx()).as_dict()
    texts = ' '.join(c['statement'] for c in out['conclusions'])
    assert '1 prediction(s) over 1 week(s)' in texts and '1 realised outcome(s)' in texts     # p2 after the cutoff
    assert 'mark of 2026-10-06: equity 101,000.00 USD (+1.00% since the start' in texts         # later mark excluded
    assert any(u['item'] == 'descriptive backtest of the heuristic' for u in out['unavailable'])
    from src.weekly.report import part_of
    risk = next(t for t in out['tables'] if 'portfolio risk' in t['title'])
    assert part_of('track_record', 11, risk['title']) == 18
    rows = {r[0]: r[1] for r in risk['rows']}
    assert rows['beta vs SPY'] == 0.782       # same series as the benchmark, 78.22% invested (cash has beta 0)
    assert rows['largest position (% of equity)'] == 'AAA 78.22'         # 500 x 158 / 101,000
    assert rows['largest sector, SIC major group (% of equity)'] == '35 78.22'
    assert rows['longest exit (sessions at the participation limit)'] == 'AAA 0.05'   # 500 / (1e6 x 1%)
    assert rows['global risk score'].startswith('NOT IMPLEMENTED')
    trades = next(t for t in out['tables'] if 'positions and trades' in t['title'])
    row = dict(zip(trades['columns'], trades['rows'][0]))
    assert row['exit'] == 'open' and row['P&L kind'] == 'unrealised' and row['sessions held'] == 1   # 10-12 mark: after T_c
    assert row['P&L (USD)'] == round((158.0 - 150.016) * 500, 2) and row['return vs cost basis (%)'] == 5.322
    bvp = next(t for t in out['tables'] if 'backtest beside' in t['title'])
    assert dict((r[0], r[2]) for r in bvp['rows'])['comparable?'] == 'no: fewer than 52 weekly rebalances'


def test_synthesis_pillars_questions_and_scenarios():
    from src.weekly.sections import synthesis
    item = {'source': 'SEC EDGAR', 'fact': 'facts', 'rank': 1, 'published_at': '2026-10-01T00:00:00+00:00'}
    previous = [
        {'name': 'valuation', 'unavailable': [], 'conclusions': [{'scope': 'AAA', 'level': 'STRONGLY SUPPORTED',
                                                                   'evidence': [item], 'statement': 's'}],
         'tables': [{'title': 'AAA: fundamentals (SEC XBRL, point-in-time)', 'columns': ['measure', 'known at T_p',
                                                                                         'known at T_c', 'change'],
                     'rows': [['quarterly revenue YoY (%)', 5, 10.0, 5], ['operating margin change vs 1 year (pts)',
                                                                         0, 1.5, 1.5]]},
                    {'title': 'AAA: valuation versus pre-declared peers (same close date)',
                     'columns': ['company', 'price / sales TTM', 'flags'],
                     'rows': [['AAA', 12.0, None], ['PEER', 5.0, None], ['peer median (n)', '5.0 (1)', None]]},
                    {'title': 'AAA: intrinsic-value scenarios (two-stage FCF model)',
                     'columns': ['scenario', 'growth', 'per share', 'vs close', 'tv'],
                     'rows': [['bear', 5.0, 50.0, -50.0, 60.0], ['base', 10.0, 80.0, -20.0, 62.0],
                              ['bull', 15.0, 95.0, -5.0, 64.0]]}]},
        {'name': 'quant', 'unavailable': [], 'conclusions': [],
         'tables': [{'title': 'Universe — heuristic signal at T_c (ex-news first)',
                     'columns': ['ticker', 'S ex-news (T_c)', 'label ex-news (T_c)'], 'rows': [['AAA', 70.0, 'POSITIVE']]}]},
        {'name': 'regime', 'unavailable': [], 'conclusions': [{'scope': 'overall', 'level': 'UNCERTAIN',
                                                                'statement': 'Market regime: trend up.', 'evidence': []}],
         'tables': [{'title': 'Market regime at T_c', 'columns': ['dimension', 'series', 'state', 'detail'],
                     'rows': [['real yield (10y TIPS)', 'DFII10', 'rising', '']]}]},
    ]
    out = synthesis.build(Ctx(), previous=previous).as_dict()
    pillars = {r[0]: r[1] for r in next(t for t in out['tables'] if 'four pillars' in t['title'])['rows']}
    assert pillars['fundamentals'] == 'improving' and pillars['technical'] == 'up'
    assert pillars['quant'] == 'POSITIVE' and pillars['valuation'] == 'above peers'
    qa = next(t for t in out['tables'] if 'questions' in t['title'])
    assert len(qa['rows']) == 13 and qa['rows'][7][1].startswith('pillars: agree')
    assert qa['rows'][11][1].startswith('No: validation NOT DEMONSTRATED')
    scen = next(t for t in out['tables'] if 'scenarios' in t['title'])
    assert scen['rows'][1][2].startswith('80.0 USD per share (-20.0% vs close')
    company = next(c for c in out['conclusions'] if c['scope'] == 'AAA')
    assert company['kind'] == 'interpretation' and 'not evidence of future returns' in company['statement']
    summary = next(c for c in out['conclusions'] if c['scope'] == 'overall')
    assert summary['statement'].startswith('Executive summary for the week ending 2026-10-09: the analysis sections '
                                           'hold 1 strongly supported')
    assert qa['rows'][7][1] == 'pillars: agree (fundamentals +, technical +, quant +)'
