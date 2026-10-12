#!/usr/bin/env python3
"""
Weekly analyst report (phase P3.0) - `python main.py weekly [--cutoff ISO-INSTANT]`

Runs every section of src/weekly/sections (each answers some of the 14 questions), then builds
Q12 (what the system does not know), Q13 (strongly supported conclusions) and Q14 (uncertain
conclusions and DATA UNAVAILABLE items) from the sections' records, renders HTML + JSON and
archives them under reports/weekly/<s_0>/ (never overwritten).

A section that fails is reported as DATA UNAVAILABLE for its questions; the report still
renders. Nothing in this file decides an evidence level: levels come from core.conclude().
"""

import importlib
import inspect
import traceback
from html import escape

from ..common import NA_DISPLAY, redact
from .context import Context
from .core import STRONG, UNAVAILABLE, UNCERTAIN, SectionResult, code_version, unavailable, write_archive

QUESTIONS = {
    1: 'What happened this week?',
    2: 'What changed fundamentally?',
    3: 'What changed in the macro environment?',
    4: 'What changed geopolitically?',
    5: 'What changed socio-economically?',
    6: "What happened in the company's sector?",
    7: 'What important company-specific events occurred?',
    8: 'What risks increased?',
    9: 'What catalysts are approaching?',
    10: 'What does the quantitative model currently say?',
    11: 'How reliable is that quantitative signal?',
    12: 'What does the model NOT know?',
    13: 'Which conclusions are strongly supported by data?',
    14: 'Which conclusions remain uncertain?',
}
SECTIONS = ('market', 'regime', 'technicals', 'sec_events', 'valuation', 'macro', 'commodities', 'agencies',
            'geopolitics', 'news', 'sector', 'catalysts', 'risks', 'positioning', 'quant', 'track_record',
            'data_quality', 'synthesis')
# a report whose critical section failed is INCOMPLETE (manifest status, exit code 3 of `python main.py weekly`)
CRITICAL_SECTIONS = ('market', 'sec_events', 'valuation', 'macro', 'risks', 'quant', 'synthesis')
# master mission P5: the 22-part structure of the weekly analysis
PARTS = {1: 'Executive summary', 2: 'Overall market conditions', 3: 'Market regime', 4: 'Macroeconomic analysis',
         5: 'Geopolitical analysis', 6: 'Socioeconomic analysis', 7: 'Commodities', 8: 'Sector analysis',
         9: 'Company fundamentals', 10: 'Valuation', 11: 'Technical analysis', 12: 'Recent news and events',
         13: 'Earnings and upcoming catalysts', 14: 'Insider activity', 15: 'Market sentiment and positioning',
         16: 'Options and implied volatility', 17: 'Quantitative analysis', 18: 'Risk analysis',
         19: 'Bull, base and bear scenarios', 20: 'Data quality', 21: 'Prediction history and performance',
         22: 'Conclusions and key uncertainties'}
SIMPLE_PARTS = {'market': 2, 'regime': 3, 'commodities': 7, 'sector': 8, 'technicals': 11, 'geopolitics': 5,
                'catalysts': 13, 'quant': 17, 'data_quality': 20, 'track_record': 21}


def part_of(section, question, text, kind=None):
    """Report part (1-22) of a table / conclusion / unavailable item (rules above; first match)."""
    low = (text or '').lower()
    if section == 'track_record' and 'portfolio risk' in low:
        return 18
    if section in SIMPLE_PARTS:
        return SIMPLE_PARTS[section]
    if section == 'synthesis':
        return 19 if 'scenario' in low else 22 if 'uncertaint' in low and question == 13 else 1
    if section in ('sec_events', 'risks') and ('form 4' in low or 'insider' in low):
        return 14
    if section == 'risks':
        return 18
    if section == 'positioning':
        return 16 if any(w in low for w in ('option', 'implied volatility', 'skew', 'term slope')) else 15
    if section == 'news':
        return 5 if question == 4 else 12
    if section == 'macro':
        return {3: 4, 4: 5, 5: 6}.get(question, 4)
    if section == 'agencies':
        return 6 if question == 5 else 4
    if section == 'sec_events':
        return 9 if question == 2 else 12
    if section == 'valuation':
        return 9 if (': fundamentals (sec xbrl' in low or kind == 'official_fact' or low.startswith('company guidance')
                     or low.startswith('extended fundamentals')) else 10
    return 22

# Structural blind spots of the quantitative signal (kept in sync with the code by a test).
BLIND_SPOTS = [
    'technical component: daily closes only (no intraday, high / low, order flow)',
    'fundamental component: TTM revenue, revenue growth, debt / equity only (no margins, cash flow, '
    'EPS, dilution, guidance, analyst estimates or revisions)',
    'insider component: open-market Form 4 purchases / sales over 90 days only (no Form 4/A, '
    'no derivative transactions)',
    'news: the word-count lexicon on titles and descriptions (aggregator source, no history) could not be '
    'validated and is not part of the signal since 2026-10-12 (descriptive only)',
    'not used by the signal at all: macro, geopolitics, socio-economic data, sector, options / implied '
    'volatility, short interest, earnings dates, analyst revisions, events',
    'the combined weights (0.25 / 0.40 / 0.20 / 0.15) and thresholds (65 / 40) are heuristic and '
    'were never fitted or validated',
]


def run_sections(ctx, names=SECTIONS):
    results = []
    for name in names:
        try:
            module = importlib.import_module(f'.sections.{name}', __package__)
        except ImportError as e:
            r = SectionResult(name, [])
            r.add(unavailable('overall', None, f'section {name}', f'NOT IMPLEMENTED ({e})'))
            results.append(r.as_dict())
            continue
        try:
            if 'previous' in inspect.signature(module.build).parameters:
                results.append(module.build(ctx, previous=list(results)).as_dict())
            else:
                results.append(module.build(ctx).as_dict())
        except Exception as e:  # noqa: BLE001 - one section must not stop the report
            r = SectionResult(name, getattr(module, 'QUESTIONS', []))
            for q in r.questions or [None]:
                r.add(unavailable('overall', q, f'section {name}',
                                  f'section failed: {type(e).__name__}: {e}'))
            r.notes.append(redact(traceback.format_exc(limit=3)))
            results.append(r.as_dict())
    return results


def collect(sections, level):
    return [c for s in sections for c in s['conclusions'] if c['level'] == level]


def build(requested_cutoff=None, generated_at=None, ctx=None, names=SECTIONS):
    ctx = ctx or Context(requested_cutoff=requested_cutoff, generated_at=generated_at)
    sections = run_sections(ctx, names)
    unavailable_items = [u for s in sections for u in s['unavailable']]
    payload = {
        'report': 'weekly analyst report',
        'time_model': ctx.tm.as_dict(),
        'universe': ctx.universe,
        'questions': QUESTIONS,
        'code_version': code_version(),
        'thresholds_version': ctx.weekly.get('thresholds_version'),
        'sections': sections,
        'q12_model_does_not_know': {'structural': BLIND_SPOTS,
                                    'missing_this_week': unavailable_items},
        'q13_strongly_supported': collect(sections, STRONG),
        'q14_uncertain': collect(sections, UNCERTAIN),
        'q14_data_unavailable': unavailable_items,
        'banner': banner(sections),
    }
    payload['counts'] = {'strongly_supported': len(payload['q13_strongly_supported']),
                         'uncertain': len(payload['q14_uncertain']),
                         'data_unavailable': len(unavailable_items)}
    failed = [s['name'] for s in sections if any('section failed' in u['reason'] or 'NOT IMPLEMENTED (' in u['reason']
                                                 for u in s['unavailable'] if u['item'] == f"section {s['name']}")]
    critical = [n for n in failed if n in CRITICAL_SECTIONS]
    payload['failed_sections'] = failed
    payload['status'] = 'INCOMPLETE' if critical else 'COMPLETE'
    payload['status_reason'] = (f"critical section(s) failed: {', '.join(critical)}" if critical else
                                (f"non-critical section(s) failed: {', '.join(failed)}" if failed else None))
    assign_parts(payload)
    return payload, ctx


def assign_parts(payload):
    """Tag every table / conclusion / unavailable item with its report part and build the structure table."""
    counts = {n: [0, 0, 0] for n in PARTS}
    for s in payload['sections']:
        for t in s['tables']:
            t['part'] = part_of(s['name'], t.get('question'), t['title'])
            counts[t['part']][0] += 1
        for c in s['conclusions']:
            c['part'] = part_of(s['name'], c.get('question'), c['statement'], c.get('kind'))
            counts[c['part']][1] += 1
        for u in s['unavailable']:
            u['part'] = part_of(s['name'], u.get('question'), f"{u['item']} {u['reason']}")
            counts[u['part']][2] += 1
    payload['parts'] = PARTS
    payload['structure'] = [[n, PARTS[n], *counts[n], 'covered' if counts[n][0] or counts[n][1] else
                             'DATA UNAVAILABLE' if counts[n][2] else 'empty'] for n in PARTS]


def banner(sections):
    lines = ['Quantitative signals are heuristic 0-100 scores: not trade recommendations, not '
             'probabilities.',
             '"Coincided with" describes timing only: no causal link between any event and any price '
             'move is asserted.']
    for s in sections:
        for c in s['conclusions']:
            if c.get('banner'):
                lines.insert(1, c['statement'])
    return lines


# ---------------------------------------------------------------- HTML

STYLE = """
body{font-family:Arial,sans-serif;margin:20px;background:#f5f5f5;color:#222}
.container{max-width:1200px;margin:0 auto;background:#fff;padding:20px;border-radius:8px}
h1{border-bottom:3px solid #0066cc;padding-bottom:8px} h2{color:#0066cc;margin-top:28px}
.banner{background:#fff4e5;border-left:4px solid #e69500;padding:10px;margin:10px 0}
table{width:100%;border-collapse:collapse;margin:10px 0;font-size:.92em}
th,td{padding:6px 8px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}
th{background:#0066cc;color:#fff} .small{color:#666;font-size:.85em}
.STRONG{color:#1a7f37;font-weight:bold} .UNCERTAIN{color:#b26b00;font-weight:bold}
.UNAVAILABLE{color:#999;font-style:italic}
"""


def _cell(v):
    if v is None:
        return f'<span class="UNAVAILABLE">{escape(NA_DISPLAY)}</span>'
    if isinstance(v, float):
        return escape(f'{v:,.4g}')
    return escape(str(v))


def _level(level):
    css = {STRONG: 'STRONG', UNCERTAIN: 'UNCERTAIN', UNAVAILABLE: 'UNAVAILABLE'}[level]
    return f'<span class="{css}">{escape(level)}</span>'


def _evidence(c):
    out = []
    for e in c['evidence']:
        out.append(f"{escape(str(e['source']))} (rank {e['rank']}; published {escape(str(e['published_at']))}; "
                   f"retrieved {escape(str(e['retrieved_at']))}; fetch {escape(str(e['fetch_id']))})")
    return '<br>'.join(out)


def _conclusions_table(items):
    if not items:
        return '<p class="small">None.</p>'
    rows = ['<table><tr><th>Scope</th><th>Q</th><th>Statement</th><th>Level</th><th>Reasons / resolution</th>'
            '<th>Evidence</th></tr>']
    for c in items:
        reasons = ', '.join(c['reason_codes'])
        if c.get('what_would_resolve_it'):
            reasons += f" — would resolve: {c['what_would_resolve_it']}"
        rows.append(f"<tr><td>{escape(c['scope'])}</td><td>{c['question']}</td><td>{escape(c['statement'])}</td>"
                    f"<td>{_level(c['level'])}</td><td class='small'>{escape(reasons)}</td>"
                    f"<td class='small'>{_evidence(c)}</td></tr>")
    rows.append('</table>')
    return ''.join(rows)


def _table(t):
    head = ''.join(f'<th>{escape(str(c))}</th>' for c in t['columns'])
    body = ''.join('<tr>' + ''.join(f'<td>{_cell(v)}</td>' for v in r) + '</tr>' for r in t['rows'])
    note = f"<p class='small'>{escape(t['note'])}</p>" if t.get('note') else ''
    return f"<h4>{escape(t['title'])}</h4><table><tr>{head}</tr>{body}</table>{note}"


def render_html(payload):
    tm = payload['time_model']
    parts = ['<!DOCTYPE html><html><head><meta charset="UTF-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
             f'<title>Weekly Analyst Report</title><style>{STYLE}</style></head><body><div class="container">',
             f"<h1>Weekly analyst report — week ending {escape(tm['s0'])}</h1>",
             f"<p class='small'>Cutoff {escape(tm['cutoff'])} (UTC); previous cutoff {escape(tm['previous_cutoff'])}; "
             f"sessions {escape(', '.join(tm['week_sessions']))}; generated {escape(tm['generated_at'])}; "
             f"news complete for the window: {tm['news_complete_for_window']}; code {escape(str(payload['code_version']))}; "
             f"thresholds {escape(str(payload['thresholds_version']))}.</p>"]
    parts += [f"<div class='banner'>{escape(line)}</div>" for line in payload['banner']]
    parts.append(f"<p>Conclusions: {payload['counts']['strongly_supported']} strongly supported, "
                 f"{payload['counts']['uncertain']} uncertain, {payload['counts']['data_unavailable']} "
                 "data unavailable.</p>")
    status = payload.get('status', 'COMPLETE')
    parts.append(f"<p><b>Report status: {escape(status)}</b>" + (f" — {escape(payload['status_reason'])}"
                                                               if payload.get('status_reason') else '') + '</p>')
    if payload.get('structure'):
        parts.append('<h2>Report structure</h2>' + _table({
            'title': 'Parts of the weekly analysis (tables / conclusions / DATA UNAVAILABLE items)',
            'columns': ['part', 'title', 'tables', 'conclusions', 'unavailable', 'status'],
            'rows': payload['structure'], 'note': None}))
    for n, title in (payload.get('parts') or {}).items():
        n = int(n)
        parts.append(f"<h2>{n}. {escape(title)}</h2>")
        for s in payload['sections']:
            for t in s['tables']:
                if t.get('part') == n:
                    parts.append(_table(t))
        items = [c for s in payload['sections'] for c in s['conclusions'] if c.get('part') == n]
        if items:
            parts.append(_conclusions_table(items))
        un = [u for s in payload['sections'] for u in s['unavailable'] if u.get('part') == n]
        if un:
            parts.append('<ul>' + ''.join(f"<li class='UNAVAILABLE'>{escape(u['scope'])}: {escape(u['item'])} — "
                                          f"{escape(u['reason'])}</li>" for u in un) + '</ul>')
        if not (items or un or any(t.get('part') == n for s in payload['sections'] for t in s['tables'])):
            parts.append("<p class='small'>Nothing in this part this week.</p>")
    parts.append('<h2>Appendix — method notes per section</h2>')
    for s in payload['sections']:
        if s['notes']:
            parts.append(f"<details><summary class='small'>{escape(s['name'])}</summary>"
                         + ''.join(f"<p class='small'>{escape(str(x))}</p>" for x in s['notes']) + '</details>')
    parts.append(f"<h2>Appendix — Q12. {escape(payload['questions'][12])}</h2><ul>"
                 + ''.join(f'<li>{escape(b)}</li>' for b in payload['q12_model_does_not_know']['structural'])
                 + '</ul><p>Missing or degraded this week:</p><ul>'
                 + ''.join(f"<li>{escape(u['scope'])} — {escape(u['item'])}: {escape(u['reason'])}</li>"
                           for u in payload['q12_model_does_not_know']['missing_this_week'])
                 + '</ul><p class="small">These lists are not exhaustive.</p>')
    parts.append(f"<h2>Appendix — Q13. {escape(payload['questions'][13])}</h2>" + _conclusions_table(payload['q13_strongly_supported']))
    parts.append(f"<h2>Appendix — Q14. {escape(payload['questions'][14])}</h2>" + _conclusions_table(payload['q14_uncertain']))
    parts.append('</div></body></html>')
    return '\n'.join(parts)


def run(requested_cutoff=None):
    payload, ctx = build(requested_cutoff)
    html = render_html(payload)
    html_path, json_path = write_archive(ctx.tm, payload, html)
    print(f"[WEEKLY REPORT] week ending {ctx.tm.s0} (cutoff {ctx.tm.cutoff})")
    print(f"  {payload['counts']}; status {payload['status']}" + (f" ({payload['status_reason']})"
                                                                   if payload.get('status_reason') else ''))
    print(f"  HTML: {html_path}\n  JSON: {json_path}")
    return payload
