"""
Gap round G5: dashboard built only from the system's outputs (synthetic outputs in the test reports folder).
"""

import json


def test_without_outputs_every_block_says_unavailable():
    from src.dashboard import Dashboard
    html = Dashboard().create_live_dashboard_html([])
    assert 'no weekly report found' in html and 'no reports/source_check.json' in html
    assert 'no reports/pipeline_audit.json' in html and 'NOT DEMONSTRATED' in html
    assert 'Records</td><td>0 (chain OK)' in html and 'NOT STARTED (python main.py paper' in html
    for word in ('BUY', 'SELL', 'probability of'):
        assert word not in html


def test_values_come_from_the_outputs():
    from src.common import reports_dir
    from src.dashboard import Dashboard, latest_weekly
    base = reports_dir()
    week = base / 'weekly' / '2026-10-09'
    week.mkdir(parents=True)
    weekly = {'time_model': {'s0': '2026-10-09', 'cutoff': '2026-10-10T05:00:00+00:00', 'generated_at': 'G'},
              'universe': ['AAA'], 'status': 'COMPLETE', 'status_reason': None,
              'counts': {'strongly_supported': 3, 'uncertain': 4, 'data_unavailable': 1},
              'sections': [
                  {'name': 'market', 'conclusions': [], 'unavailable': [], 'tables': [
                      {'title': 'AAA — week in figures', 'columns': ['ticker', 'weekly return %', 'excess vs SPY pp'],
                       'rows': [['AAA', '1.5', '0.4']]}]},
                  {'name': 'valuation', 'conclusions': [], 'tables': [
                      {'title': 'AAA: valuation ratios at the close of 2026-10-09', 'columns': ['ratio', 'formula',
                                                                                              'value', 'not computed because'],
                       'rows': [['price / sales TTM', 'x', 12.5, None],
                                ['price / diluted EPS TTM', 'x', None, 'P/E: not meaningful (denominator <= 0)']]}],
                   'unavailable': [{'scope': 'AAA', 'item': 'company guidance', 'reason': 'NOT REPORTED'}]},
                  {'name': 'regime', 'conclusions': [], 'unavailable': [], 'tables': [
                      {'title': 'Market regime at T_c', 'columns': ['dimension', 'series', 'state', 'detail'],
                       'rows': [['trend', 'SPY', 'up', 'SMA200 rising']]}]}]}
    (week / 'weekly_v2.json').write_text(json.dumps(weekly))
    (week / 'weekly_v10.json').write_text(json.dumps(dict(weekly, status='INCOMPLETE', status_reason='quant failed')))
    assert latest_weekly()[1].name == 'weekly_v10.json'                       # numeric version order, not text
    (base / 'pipeline_audit.json').write_text(json.dumps({'computed_at': 'A', 'status': 'WARN',
                                                          'summary': {'PASS': 9, 'WARN': 1, 'FAIL': 0}, 'tickers': {}}))
    html = Dashboard().create_live_dashboard_html([{'ticker': 'AAA', 'modules': {}, 'data_availability': {}}])
    assert 'INCOMPLETE — quant failed' in html and 'WARN: 9 PASS, 1 WARN, 0 FAIL' in html
    assert '12.5' in html and 'n/m (P/E: not meaningful (denominator &lt;= 0))' in html
    assert '1.5' in html and 'up (SMA200 rising)' in html
    assert '1 DATA UNAVAILABLE item(s) in the weekly report' in html
