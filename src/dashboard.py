#!/usr/bin/env python3
"""
Dashboard (master mission section 12, gap round G5) - a static HTML overview built ONLY from the system's outputs

Every block names the output it reads and that output's own timestamp; a missing output is shown as
DATA UNAVAILABLE with the reason, never a default value. Inputs (all under reports/):
  analysis.json                      daily batch (python main.py analyze): last close, heuristic signal, validation,
                                     data availability per ticker
  weekly/<s0>/weekly_v<N>.json       the latest weekly report: weekly return, fundamentals, valuation ratios,
                                     technical indicators, regime, events, risks, unavailable items, report status
  pipeline_audit.json                data audit summary (python main.py audit)
  source_check.json                  source probe (python main.py sources)
  heuristic_evaluation.json          descriptive evaluation of the heuristic (python main.py evaluate-heuristic)
  paper/*.jsonl                      prediction and transaction journals (paper strategy PT1)
  prospective/ledger.jsonl           stage 3 records
Nothing here computes a new signal, a probability or a risk score: those are NOT IMPLEMENTED / NOT CALIBRATED and
the dashboard says so.
"""

import json
from html import escape
from pathlib import Path

from .common import DATA_UNAVAILABLE, NA_DISPLAY, display, reports_dir, utc_now_iso

NOT_CALIBRATED = 'NOT CALIBRATED'
NOT_IMPLEMENTED = 'NOT IMPLEMENTED'


def _cell(value, fmt=None, suffix=''):
    text = display(value, fmt, suffix)
    css = ' class="na"' if text == NA_DISPLAY else ''
    return f'<span{css}>{escape(text)}</span>'


def _na(reason):
    return f'<span class="na">{escape(DATA_UNAVAILABLE)}: {escape(reason)}</span>'


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def latest_weekly(base=None):
    """(payload, path) of the highest version of the most recent weekly report, or (None, None)."""
    root = Path(base or reports_dir()) / 'weekly'
    best = None
    for path in root.glob('*/weekly_v*.json'):
        try:
            key = (path.parent.name, int(path.stem.split('_v')[-1]))
        except ValueError:
            continue
        if best is None or key > best[0]:
            best = (key, path)
    if best is None:
        return None, None
    return _read_json(best[1]), best[1]


def _table(weekly, section, title_prefix):
    for s in (weekly or {}).get('sections', []):
        if s['name'] == section:
            for t in s['tables']:
                if t['title'].startswith(title_prefix):
                    return t
    return None


def _row(table, label_prefix, col=None):
    """Value of the first row whose first cell starts with label_prefix (column `col`, default the last)."""
    if not table:
        return None
    i = table['columns'].index(col) if col in (table or {}).get('columns', []) else -1
    for r in table['rows']:
        if r and str(r[0]).startswith(label_prefix):
            return r[i]
    return None


def _ratio(table, label_prefix):
    """A valuation ratio, or 'n/m' with the weekly report's reason when it was not computed."""
    for r in (table or {}).get('rows', []):
        if r and str(r[0]).startswith(label_prefix):
            return _cell(r[2]) if r[2] is not None else f'<span class="na">n/m ({escape(str(r[3] or "no reason"))})</span>'
    return _cell(None)


def load_inputs(analysis_results=None, base=None):
    base = Path(base or reports_dir())
    weekly, weekly_path = latest_weekly(base)
    out = {'analysis': analysis_results if analysis_results is not None else _read_json(base / 'analysis.json'),
           'weekly': weekly, 'weekly_path': weekly_path, 'audit': _read_json(base / 'pipeline_audit.json'),
           'sources': _read_json(base / 'source_check.json'),
           'evaluation': _read_json(base / 'heuristic_evaluation.json'), 'paper': None, 'stage3': None}
    try:
        from .journal import Journal
        from .paper_report import outcomes_by_horizon, performance, trades
        tx, pred = Journal('transactions', base / 'paper').entries(), Journal('predictions', base / 'paper').entries()
        start = next((e for e in tx if e['type'] == 'start'), None)
        marks = [e for e in tx if e['type'] == 'mark']
        out['paper'] = {'started': start['created_at'] if start else None,
                        'performance': performance(marks, start['capital']) if start else {'status': 'NOT STARTED'},
                        'bench': (marks[-1].get('bench_state') or {}) if marks else {},
                        'trades': trades(tx), 'pending': sum(1 for e in tx if e['type'] == 'order')
                        - sum(1 for e in tx if e['type'] in ('fill', 'order_rejected', 'order_cancelled')),
                        'predictions': sum(1 for e in pred if e['type'] == 'prediction'),
                        'weeks': len({e['signal_instant'][:10] for e in pred if e['type'] == 'prediction'}),
                        'outcomes': outcomes_by_horizon(pred)}
    except Exception as e:  # noqa: BLE001 - shown as unavailable with its reason
        out['paper_error'] = f'{type(e).__name__}: {e}'
    try:
        from .prospective import verify_ledger
        out['stage3'] = verify_ledger(base / 'prospective')
    except Exception as e:  # noqa: BLE001
        out['stage3_error'] = f'{type(e).__name__}: {e}'
    return out


# ---------------------------------------------------------------- per-ticker card

def ticker_card(t, result, weekly):
    m = (result or {}).get('modules', {})
    sig, tech = m.get('signal', {}), m.get('technical', {})
    price = tech.get('components', {}).get('bollinger', {}).get('price')
    avail = (result or {}).get('data_availability', {})
    missing = [n for n, s in avail.items() if s not in ('OK', 'PROVISIONAL')]
    week = _table(weekly, 'market', f'{t} — week in figures')
    fund = _table(weekly, 'valuation', f'{t}: fundamentals (SEC XBRL')
    ratios = _table(weekly, 'valuation', f'{t}: valuation ratios')
    techw = _table(weekly, 'technicals', f'{t}: technical indicators')
    pillars = _table(weekly, 'synthesis', f'{t}: four pillars')
    risks = _table(weekly, 'risks', f'{t} — risk indicators')
    guidance = _table(weekly, 'valuation', f'{t}: company guidance')
    news = _table(weekly, 'news', f'{t} — news events')
    filings = _table(weekly, 'sec_events', f'{t}: every SEC filing available in the window')
    unavailable = [u for s in (weekly or {}).get('sections', []) for u in s['unavailable'] if u['scope'] == t]
    increased = [r[0] for r in (risks or {}).get('rows', []) if r and r[-1] == 'yes']
    high_news = sum(1 for r in (news or {}).get('rows', []) if len(r) > 5 and r[5] == 'high')
    lines = [
        ('Last close (analysis)', f"{_cell(price, '.2f')} ({_cell(tech.get('last_price_date'))})"),
        ('Weekly return / vs SPY', f"{_cell(_row(week, t, 'weekly return %'))}% / "
                                   f"{_cell(_row(week, t, 'excess vs SPY pp'))} pp" if week else _na('no weekly table')),
        ('Revenue TTM (USD)', _cell(_row(fund, 'revenue TTM', 'known at T_c'), ',.0f') if fund else _na('no weekly table')),
        ('Quarterly revenue YoY', _cell(_row(fund, 'quarterly revenue YoY', 'known at T_c'), suffix='%') if fund else ''),
        ('Operating margin TTM', _cell(_row(fund, 'operating margin', 'known at T_c'), suffix='%') if fund else ''),
        ('P/S · EV/sales · P/E', ' · '.join(_ratio(ratios, k) for k in
                                            ('price / sales', 'EV / sales', 'price / diluted EPS')) if ratios
         else _na('no weekly valuation table')),
        ('FCF yield · ROE', ' · '.join(_ratio(ratios, k) for k in ('free cash flow yield', 'return on equity'))
         + ' (%)' if ratios else ''),
        ('Trend (rule)', _cell(_row(pillars, 'technical', 'reading')) if pillars else _na('no synthesis')),
        ('RSI 14 · momentum 3 months (%)', ' · '.join(_cell(_row(techw, k)) for k in ('RSI 14', 'momentum 3'))
         if techw else _na('no weekly technicals')),
        ('20-day volatility (%, annualised) · from 52-week high (%)',
         ' · '.join(_cell(_row(techw, k)) for k in ('historical volatility 20d', 'drawdown from the 52-week high'))
         if techw else ''),
        ('SEC filings in the report week', _cell(len(filings['rows'])) + escape(
            f" (forms: {', '.join(sorted({str(r[4]) for r in filings['rows']}))})" if filings['rows'] else '')
         if filings else _na('no SEC events table')),
        ('Fundamentals pillar', _cell(_row(pillars, 'fundamentals', 'reading')) if pillars else ''),
        ('Company guidance', 'quoted in the weekly report' if guidance else 'not available (see weekly part 9)'),
        ('High-materiality news clusters', _cell(high_news) if news else _na('no news table')),
        ('Risk indicators that increased', escape(', '.join(increased) or 'none') if risks else _na('no risk table')),
        ('Quantitative signal', f"{_cell(sig.get('quantitative_signal'))} · strength {_cell(sig.get('signal_strength'))}"
                                f"/100 (coverage {_cell(sig.get('coverage'))}) · heuristic, not a recommendation"),
        ('Validation', _cell((sig.get('validation') or {}).get('status'))),
        ('Predicted probability', f'{NOT_CALIBRATED} <span class="small">(the score is not a probability)</span>'),
        ('Risk score', f'{NOT_IMPLEMENTED} <span class="small">(separate metrics only)</span>'),
        ('Missing data', escape(f"{len(unavailable)} DATA UNAVAILABLE item(s) in the weekly report; daily: "
                                f"{', '.join(missing) or 'none'}")),
    ]
    body = ''.join(f'<tr><td>{escape(k)}</td><td>{v}</td></tr>' for k, v in lines if v != '')
    return f'<div class="card"><div class="ticker">{escape(t)}</div><table>{body}</table></div>'


# ---------------------------------------------------------------- system panels

def _panel(title, rows, note=None):
    body = ''.join(f'<tr><td>{escape(str(k))}</td><td>{v}</td></tr>' for k, v in rows)
    return (f'<div class="card wide"><h2>{escape(title)}</h2><table>{body}</table>'
            + (f'<p class="small">{escape(note)}</p>' if note else '') + '</div>')


def system_panels(inp):
    w = inp['weekly']
    out = []
    if w:
        tm = w.get('time_model') or {}
        regime = _table(w, 'regime', 'Market regime')
        out.append(_panel(f"Weekly report (week ending {tm.get('s0')})", [
            ('Status', escape(f"{w.get('status')}" + (f" — {w['status_reason']}" if w.get('status_reason') else ''))),
            ('Cutoff / generated', escape(f"{tm.get('cutoff')} / {tm.get('generated_at')}")),
            ('Conclusions', escape(f"{w['counts']['strongly_supported']} strongly supported, {w['counts']['uncertain']} "
                                   f"uncertain, {w['counts']['data_unavailable']} DATA UNAVAILABLE")),
            ('File', escape(str(inp['weekly_path'].name) if inp.get('weekly_path') else '')),
        ] + [(f'Regime: {r[0]}', escape(f'{r[2]} ({r[3]})')) for r in (regime or {}).get('rows', [])],
            'Regime labels follow pre-declared rules (not validated); a description, not a forecast.'))
    else:
        out.append(_panel('Weekly report', [('Status', _na('no weekly report found (python main.py weekly)'))]))
    s = inp['sources']
    if s:
        failing = [x['name'] for x in s['sources'] if x['integrated'] and not x['reachable']]
        out.append(_panel(f"Source quality (probe {s['computed_at']})", [
            ('Integrated sources reachable', escape(f"{s['summary']['integrated_reachable']} / {s['summary']['integrated_total']}")),
            ('Failing', escape(', '.join(failing) or 'none')),
            ('Official alternatives reachable here', escape(', '.join(s['summary']['alternatives_reachable']) or 'none')),
        ], 'Ranks: 1 official, 2 secondary, 3 aggregator (src/source_registry.py).'))
    else:
        out.append(_panel('Source quality', [('Probe', _na('no reports/source_check.json (python main.py sources)'))]))
    a = inp['audit']
    out.append(_panel(f"Data audit ({a['computed_at']})", [
        ('Status', escape(f"{a['status']}: {a['summary'].get('PASS')} PASS, {a['summary'].get('WARN')} WARN, "
                          f"{a['summary'].get('FAIL')} FAIL")),
        ('Checks not passing', escape('; '.join(sorted({c['check'] for cs in (a.get('tickers') or {}).values()
                                                         for c in cs if c['status'] != 'PASS'}))[:400] or 'none'))])
               if a else _panel('Data audit', [('Status', _na('no reports/pipeline_audit.json (python main.py audit)'))]))
    ev = inp['evaluation']
    if ev:
        rows = []
        for h, m in ev.get('horizons', {}).items():
            p = m['portfolios']
            rows.append((f'{h}: top quintile net vs equal weight (Sharpe)',
                         escape(f"{p['long_only_top_quintile_net'].get('sharpe')} vs "
                                f"{p['benchmark_equal_weight_universe'].get('sharpe')}; AUC "
                                f"{m['classification']['beats_cross_sectional_median']['auc_combined_score']}")))
        out.append(_panel(f"Model validation (descriptive evaluation {ev['computed_at']})",
                          [('Predictive ability', 'NOT DEMONSTRATED')] + rows,
                          'Stage 1 / 2 pre-registered tests: 0 of 4 hypotheses confirmed. Stage 3 runs prospectively.'))
    else:
        out.append(_panel('Model validation', [('Predictive ability', 'NOT DEMONSTRATED'),
                                               ('Evaluation', _na('no reports/heuristic_evaluation.json'))]))
    st3 = inp.get('stage3')
    out.append(_panel('Stage 3 prospective record', [
        ('Records', escape(f"{st3['n_entries']} (chain {'OK' if st3['chain_ok'] else 'BROKEN'})")),
        ('Latest', escape(max(st3['verified']) if st3['verified'] else 'none')),
    ], 'The pre-registered test runs once, after 52 valid weekly records.') if st3 else
        _panel('Stage 3 prospective record', [('Ledger', _na(inp.get('stage3_error', 'not readable')))]))
    p = inp.get('paper')
    if p:
        perf, b = p['performance'], p['bench']
        rows = [('Started', escape(str(p['started']))), ('Pending orders', escape(str(p['pending'])))]
        if perf.get('status') == 'OK':
            rows += [('Equity (USD)', _cell(perf['equity'], ',.2f')),
                     ('Return since start / max drawdown', escape(f"{perf['total_return_pct']}% / {perf['max_drawdown_pct']}%")),
                     ('SPY / equal-weight universe since start', escape(f"{b.get('spy_return_pct')}% / {b.get('ew_return_pct')}%")),
                     ('Sharpe / Sortino', escape(f"{perf['sharpe']} / {perf['sortino']}" if perf['sharpe'] is not None
                                                 else f"need 20 daily returns ({perf['sessions']} marks)"))]
        elif perf.get('status') == 'NOT STARTED':
            rows.append(('Performance', 'NOT STARTED (python main.py paper starts PT1 from a stage 3 record)'))
        else:
            rows.append(('Performance', _na('no portfolio mark yet')))
        rows += [(f"{x['ticker']} ({x['exit_type'] or 'open'})",
                  escape(f"in {x['entry_session']} @ {x['entry_price']:.2f}; P&L {x['pnl']} ({x['pnl_kind']}); worst "
                         f"{x['worst_drawdown_pct']}%")) for x in p['trades']]
        out.append(_panel('Paper trading PT1 (paper only, no real order)', rows,
                          'Interim and descriptive: the pre-registered evaluation needs 52 weekly rebalances.'))
        hrows = [('Predictions recorded', escape(f"{p['predictions']} over {p['weeks']} week(s)"))]
        hrows += [(f'{h} sessions', escape(f"{r['outcomes']} outcomes; top 8 {r['mean_top_pct']}% vs others "
                                           f"{r['mean_others_pct']}%; weekly rank correlation {r['mean_weekly_ic']}"))
                  for h, r in p['outcomes'].items()] or [('Outcomes', _na('no realised outcome yet'))]
        hrows.append(('Calibration', NOT_CALIBRATED))
        out.append(_panel('Prediction history', hrows))
    else:
        out.append(_panel('Paper trading and predictions', [('Journals', _na(inp.get('paper_error', 'not readable')))]))
    return out


def render(inp):
    analysis = inp['analysis'] or []
    by = {r.get('ticker'): r for r in analysis}
    tickers = list(by) or list((inp['weekly'] or {}).get('universe') or [])
    cards = [ticker_card(t, by.get(t), inp['weekly']) for t in tickers] or [f'<div class="card">{escape(NA_DISPLAY)}</div>']
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trading Agent Pro - Dashboard</title>
<style>
body {{ font-family: Arial, sans-serif; background: #0f1228; color: #e6e6e6; margin: 0; padding: 16px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }}
.card {{ background: #1a1f3a; padding: 14px; border-radius: 8px; line-height: 1.5; }}
.wide {{ grid-column: span 1; }}
.ticker {{ font-size: 20px; font-weight: bold; color: #7cc4ff; margin-bottom: 6px; }}
h2 {{ font-size: 16px; margin: 0 0 8px; color: #7cc4ff; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
td {{ padding: 3px 4px; border-bottom: 1px solid #2a3058; vertical-align: top; }}
td:first-child {{ color: #a9b3d6; width: 46%; }}
.na {{ color: #8a8a8a; font-style: italic; }}
.small {{ color: #9a9a9a; font-size: 12px; }}
</style></head><body>
<h1>Trading Agent Pro - Dashboard</h1>
<p class="small">Generated {escape(utc_now_iso())} (UTC) from the system's own outputs only; each block names its
source and timestamp. Missing values: "{escape(NA_DISPLAY)}" or {escape(DATA_UNAVAILABLE)} with the reason.
Quantitative signals are heuristic scores: not trade recommendations, not probabilities; no predictive ability
has been demonstrated. Educational purposes only. Not financial advice.</p>
<h2>System</h2><div class="grid">{''.join(system_panels(inp))}</div>
<h2 style="margin-top:16px">Companies</h2><div class="grid">{''.join(cards)}</div>
</body></html>"""


class Dashboard:
    """Overview dashboard (kept API: create_live_dashboard_html(analysis_results), save_dashboard_html(html))."""

    def __init__(self):
        self.last_update = None

    def create_live_dashboard_html(self, analysis_results=None):
        self.last_update = utc_now_iso()
        return render(load_inputs(analysis_results))

    def save_dashboard_html(self, html_content, filename='dashboard.html'):
        path = Path(reports_dir()) / filename
        path.write_text(html_content, encoding='utf-8')
        return str(path)
