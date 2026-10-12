#!/usr/bin/env python3
"""
Weekly report section 'data_quality' - report part 20 (master mission P5)

  sources       per source, the downloads logged in the window (T_p, T_c] (source_fetches): OK and failed counts,
                the last successful retrieval at or before the cutoff and the last error; a source with no
                successful download in the window is listed
  audit         the pipeline audit (reports/pipeline_audit.json): status and the non-PASS checks. The file is
                overwritten by each audit run; when it was computed after the cutoff it is shown for information
                and is not used as evidence at T_c
  sections      DATA UNAVAILABLE items per section of this report and failed sections (from the results computed
                before this section: build(ctx, previous))
These are statements about the system and its inputs (system_output). Sections never write files.
"""

import json

from ...common import reports_dir, to_utc_iso
from ..core import SectionResult, conclude, evidence, unavailable

NAME = 'data_quality'
QUESTIONS = [12]


def _sources(ctx):
    tm = ctx.tm
    if not hasattr(ctx.db, 'connect'):
        return []
    with ctx.db.connect() as conn:
        rows = conn.execute(
            "SELECT source, status, completed_at, error FROM source_fetches WHERE completed_at > ? AND completed_at <= ? "
            "ORDER BY completed_at", (tm.previous_cutoff, tm.cutoff)).fetchall()
        last_ok = dict(conn.execute("SELECT source, MAX(completed_at) FROM source_fetches WHERE status='OK' AND "
                                    "completed_at <= ? GROUP BY source", (tm.cutoff,)).fetchall())
    out = {}
    for r in rows:
        s = out.setdefault(r['source'], {'ok': 0, 'failed': 0, 'last_error': None})
        if r['status'] == 'OK':
            s['ok'] += 1
        else:
            s['failed'] += 1
            s['last_error'] = r['error']
    for source, last in last_ok.items():
        out.setdefault(source, {'ok': 0, 'failed': 0, 'last_error': None})['last_ok'] = last
    return sorted(out.items())


def build(ctx, previous=None, audit_path=None):
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    srcs = _sources(ctx)
    rows = [[s, v['ok'], v['failed'], v.get('last_ok'), (v['last_error'] or '')[:160] or None] for s, v in srcs]
    res.table('Data quality — downloads logged in the window (T_p, T_c]', ['source', 'OK', 'failed',
                                                                         'last successful retrieval <= T_c', 'last error'],
              rows, question=12, note='From the fetch log (source_fetches). A source absent from the window was not '
                                      'downloaded in it: its values in this report are older or unavailable.')
    silent = [s for s, v in srcs if v['ok'] == 0]
    failing = [s for s, v in srcs if v['failed']]
    res.add(conclude('overall', 12, f'Data sources in the window ({tm.previous_cutoff}, {tm.cutoff}]: {len(srcs)} with '
                                    f'logged downloads; {len(failing)} with at least one failure'
                                    + (f" ({', '.join(failing)})" if failing else '')
                                    + (f"; no successful download in the window for {', '.join(silent)}" if silent else '')
                                    + ('' if srcs else ': the stored data used in this report was retrieved outside '
                                                       'this window (each value carries its own publication and '
                                                       'retrieval times)')
                                    + '.', [], 'system_output'))
    path = audit_path or reports_dir() / 'pipeline_audit.json'
    try:
        audit = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        audit = None
    if audit is None:
        res.add(unavailable('overall', 12, 'pipeline audit', 'no reports/pipeline_audit.json (run python main.py audit)'))
    else:
        checks = audit.get('global', []) + [c for cs in (audit.get('tickers') or {}).values() for c in cs]
        bad = [c for c in checks if c.get('status') != 'PASS']
        computed = to_utc_iso(audit.get('computed_at'))
        res.table(f"Pipeline audit computed {computed} — checks not passing", ['status', 'check', 'detail'],
                  [[c['status'], c['check'], str(c.get('detail'))[:200]] for c in bad], question=12,
                  note='python main.py audit: storage, timestamps, prices, SEC facts and labels, Form 4, market data '
                       'and format-change checks.' + (' Computed after the cutoff: information only.'
                                                      if computed and computed > tm.cutoff else ''))
        if computed and computed <= tm.cutoff:
            item = evidence(tm, 'this system', None, f"pipeline audit {audit.get('status')} {audit.get('summary')}",
                            as_of=computed[:10], published_at=computed, basis='computed_at of the audit')
            res.add(conclude('overall', 12, f"Pipeline audit computed {computed}: {audit.get('status')} "
                                            f"{audit.get('summary')}.", [item], 'system_output'))
        else:
            res.add(unavailable('overall', 12, 'pipeline audit at the cutoff',
                                f'the latest audit was computed {computed}, after the cutoff (shown for information)'))
    previous = previous or []
    per_section = [[s['name'], len(s['unavailable']), len(s['conclusions']),
                    'FAILED' if any(u['item'] == f"section {s['name']}" and ('section failed' in u['reason']
                                                                          or 'NOT IMPLEMENTED (' in u['reason'])
                                    for u in s['unavailable']) else 'ran']
                   for s in previous]
    res.table('Data quality — DATA UNAVAILABLE items per section of this report',
              ['section', 'DATA UNAVAILABLE items', 'conclusions', 'status'], per_section, question=12)
    failed = [r[0] for r in per_section if r[3] == 'FAILED']
    res.add(conclude('overall', 12, f'This report: {sum(r[1] for r in per_section)} DATA UNAVAILABLE item(s) over '
                                    f'{len(per_section)} sections' + (f"; failed sections: {', '.join(failed)}"
                                                                       if failed else '; no section failed') + '.',
                     [], 'system_output'))
    return res
