#!/usr/bin/env python3
"""
Stage 4 proposal v3: timing-class feasibility count (NOT the experiment).

The 1,911 candidate events of the v1 feasibility sample (same 60 companies, seed 4) are rebuilt from the SEC
submissions feeds, keeping the cover-page reportDate. A seeded random subset is then timed with its EDGAR index
page ("Accepted"), and timing_rule.classify assigns each event a class.

Only SEC filing lists and index pages are read. No price, return or outcome is downloaded or computed, so the
script cannot reveal anything about the hypothesis. The exhibit 99 dateline is not read here: the announcement
day is the reportDate only.

Usage: python docs/research/stage4_proposal/feasibility_v3.py -> docs/research/stage4_proposal/feasibility_v3.json
Needs exchange_calendars (4.11.1, the version proposed for pinning).
"""

import json
import random
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT), str(HERE)]

from feasibility import SAMPLE, SEED, START, END, GAP_DAYS  # noqa: E402
from timing_rule import Schedule, classify  # noqa: E402
from src.common import utc_now_iso  # noqa: E402
from src.research.universe import Universe  # noqa: E402
from src.sec_parser import EDGAR_INDEX_URL, NEW_YORK, SECParser, index_accepted  # noqa: E402

TIMED, TIMED_SEED = 300, 20261014
OUT = HERE / 'feasibility_v3.json'


def candidate_events(sec, cik, date_added):
    """Same event rule as feasibility.py (8-K item 2.02, 45-day gap, period, date added), with reportDate."""
    feed = sec._get_json(f'{sec.SEC_API}/submissions/CIK{cik}.json', max_age=timedelta(days=30))
    if not feed:
        return None
    blocks = [feed['filings']['recent']]
    for older in feed['filings'].get('files') or []:
        if (older.get('filingTo') or '') >= '2015-01-01':
            data = sec._get_json(f"{sec.SEC_API}/submissions/{older['name']}", max_age=timedelta(days=3650))
            if data is None:
                return None
            blocks.append(data)
    rows = []
    for b in blocks:
        n = len(b.get('form') or [])
        col = {k: list(b.get(k) or []) + [None] * (n - len(b.get(k) or [])) for k in
               ('form', 'filingDate', 'items', 'accessionNumber', 'reportDate')}
        rows += [{'date': col['filingDate'][i], 'items': col['items'][i] or '', 'accession': col['accessionNumber'][i],
                  'report_date': col['reportDate'][i] or None}
                 for i in range(n) if col['form'][i] == '8-K']
    out, last = [], None
    for r in sorted(rows, key=lambda r: r['date']):
        if '2.02' not in r['items'].split(','):
            continue
        d = date.fromisoformat(r['date'])
        gap_ok = last is None or (d - last).days > GAP_DAYS
        last = d
        if gap_ok and START <= r['date'] <= END and (date_added is None or r['date'] >= date_added):
            out.append(r)
    return out


def main():
    sec, schedule = SECParser(), Schedule.xnys()
    rows = sorted({r['cik']: r for r in Universe().load() if r['cik']}.values(), key=lambda r: r['ticker'])
    sample = random.Random(SEED).sample(rows, SAMPLE)
    events, missing = [], []
    for r in sample:
        got = candidate_events(sec, r['cik'], r['date_added'])
        if got is None:
            missing.append(r['ticker'])
            continue
        events += [(r['cik'], e) for e in got]
    picks = random.Random(TIMED_SEED).sample(events, min(TIMED, len(events)))
    classes, lag, no_time = Counter(), Counter(), 0
    for cik, e in picks:
        acc = e['accession']
        html = sec._get(EDGAR_INDEX_URL.format(cik=int(cik), nodash=acc.replace('-', ''), accession=acc),
                        as_json=False, max_age=timedelta(days=3650))
        accepted = index_accepted(html) if html else None
        if not accepted:
            no_time += 1
            continue
        t_a = datetime.fromisoformat(accepted).astimezone(NEW_YORK)
        d_r = date.fromisoformat(e['report_date']) if e['report_date'] else None
        classes[classify(t_a, d_r, schedule)['class']] += 1
        lag['missing' if d_r is None else str(min((t_a.date() - d_r).days, 9))] += 1
    timed = sum(classes.values())
    primary = classes['V-PRE'] + classes['V-NONSESSION']
    result = {
        'computed_at': utc_now_iso(), 'nature': 'feasibility count only: SEC filing lists and index pages; no price',
        'firms_counted': SAMPLE - len(missing), 'feeds_unavailable': missing, 'candidate_events': len(events),
        'timed_sample_size': len(picks), 'timed_seed': TIMED_SEED, 'index_pages_without_time': no_time,
        'classes': dict(classes.most_common()),
        'acceptance_day_minus_report_date_days': dict(sorted(lag.items())),
        'primary_share': round(primary / timed, 3) if timed else None,
        'extrapolated_candidate_events_full_list': round(len(events) / (SAMPLE - len(missing)) * len(rows)),
        'extrapolated_primary_events_full_list':
            round(len(events) / (SAMPLE - len(missing)) * len(rows) * primary / timed) if timed else None,
        'list_members_with_cik': len(rows),
    }
    OUT.write_text(json.dumps(result, indent=1), encoding='utf-8')
    print(json.dumps(result, indent=1))


if __name__ == '__main__':
    main()
