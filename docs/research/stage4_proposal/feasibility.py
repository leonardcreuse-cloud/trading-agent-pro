#!/usr/bin/env python3
"""
Stage 4 proposal: feasibility count (NOT the experiment).

Counts candidate earnings announcements (Form 8-K, not 8-K/A, with item 2.02, first in 45 calendar days, after the
company joined the index) for a seeded random sample of the current S&P 500 list, over 2016-2025, and reads the
true acceptance time of a few of them on their EDGAR index pages to see how they split between pre-open, intraday
and after-close. It reads SEC filing lists and index pages only: no price, no return, no outcome is downloaded or
computed, so it cannot reveal anything about the hypothesis.

Usage: python docs/research/stage4_proposal/feasibility.py  -> docs/research/stage4_proposal/feasibility.json
"""

import json
import random
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.common import utc_now_iso  # noqa: E402
from src.research.universe import Universe  # noqa: E402
from src.sec_parser import EDGAR_INDEX_URL, NEW_YORK, SECParser, index_accepted  # noqa: E402

SAMPLE, SEED, START, END, GAP_DAYS, TIMING_SAMPLE = 60, 4, '2016-01-01', '2025-12-31', 45, 60
OUT = Path(__file__).with_name('feasibility.json')


def filings_8k(sec, cik):
    """All 8-K / 8-K/A rows (form, filing date, items, accession, feed label) since 2015, or None."""
    feed = sec._get_json(f'{sec.SEC_API}/submissions/CIK{cik}.json', max_age=timedelta(days=7))
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
               ('form', 'filingDate', 'items', 'accessionNumber', 'acceptanceDateTime')}
        for i in range(n):
            if col['form'][i] in ('8-K', '8-K/A'):
                rows.append({'form': col['form'][i], 'date': col['filingDate'][i], 'items': col['items'][i] or '',
                             'accession': col['accessionNumber'][i], 'label': col['acceptanceDateTime'][i]})
    return sorted(rows, key=lambda r: r['date'])


def events(rows, date_added):
    out, last = [], None
    for r in rows:
        if r['form'] != '8-K' or '2.02' not in r['items'].split(','):
            continue
        d = date.fromisoformat(r['date'])
        gap_ok = last is None or (d - last).days > GAP_DAYS
        last = d
        if gap_ok and START <= r['date'] <= END and (date_added is None or r['date'] >= date_added):
            out.append(r)
    return out


def timing(sec, cik, r):
    acc = r['accession']
    html = sec._get(EDGAR_INDEX_URL.format(cik=int(cik), nodash=acc.replace('-', ''), accession=acc), as_json=False,
                    max_age=timedelta(days=3650))
    accepted = index_accepted(html) if html else None
    if not accepted:
        return 'unknown'
    t = datetime.fromisoformat(accepted).astimezone(NEW_YORK)
    if t.weekday() >= 5:
        return 'weekend'
    minutes = t.hour * 60 + t.minute
    return 'pre-open' if minutes < 9 * 60 + 30 else 'intraday' if minutes < 16 * 60 else 'after-close'


MONTHS = 'January|February|March|April|May|June|July|August|September|October|November|December'
DATELINE = (r'\b(' + MONTHS + r')\.? (\d{1,2}), (\d{4})\s*(?:\(|/|--|-|\u2013|\u2014|\u2015)')


def dateline_lag(sec, cik, r):
    """Calendar days between the press release dateline (EX-99) and the SEC acceptance date, or a reason."""
    import re
    from src.guidance import exhibit_from_index, text_lines
    acc = r['accession']
    html = sec._get(EDGAR_INDEX_URL.format(cik=int(cik), nodash=acc.replace('-', ''), accession=acc), as_json=False,
                    max_age=timedelta(days=3650))
    accepted = index_accepted(html) if html else None
    path = exhibit_from_index(html) if html else None
    doc = sec._get('https://www.sec.gov' + path, as_json=False, max_age=timedelta(days=3650)) if path else None
    if not accepted or not doc:
        return 'no acceptance or exhibit'
    accepted_day = datetime.fromisoformat(accepted).astimezone(NEW_YORK).date()
    # a press release is dated at most a few days before its 8-K; an earlier match is a period-end or balance-sheet
    # date ('quarter ended September 30, 2020 (...'), not the dateline: the next match is tried
    for m in re.finditer(DATELINE, ' '.join(text_lines(doc)[:40])):
        release = datetime.strptime(f'{m.group(1)} {m.group(2)} {m.group(3)}', '%B %d %Y').date()
        lag = (accepted_day - release).days
        if 0 <= lag <= 7:
            return lag
    return 'no dateline found'


def main():
    sec = SECParser()
    universe = Universe()
    rows = sorted({r['cik']: r for r in universe.load() if r['cik']}.values(), key=lambda r: r['ticker'])
    sample = random.Random(SEED).sample(rows, SAMPLE)
    per_firm, per_year, missing, all_events = {}, Counter(), [], []
    for r in sample:
        got = filings_8k(sec, r['cik'])
        if got is None:
            missing.append(r['ticker'])
            continue
        ev = events(got, r['date_added'])
        per_firm[r['ticker']] = len(ev)
        per_year.update(e['date'][:4] for e in ev)
        all_events += [(r['cik'], e) for e in ev]
    picks = random.Random(SEED).sample(all_events, min(TIMING_SAMPLE, len(all_events)))
    timings = Counter(timing(sec, cik, e) for cik, e in picks)
    lags = Counter(str(dateline_lag(sec, cik, e)) for cik, e in picks)
    n_firms = len(per_firm)
    total = sum(per_firm.values())
    result = {
        'computed_at': utc_now_iso(), 'nature': 'feasibility count only: SEC filing lists and index pages; no price',
        'list_fetch': universe.fetch, 'list_members_with_cik': len(rows), 'sample_size': SAMPLE, 'seed': SEED,
        'period': [START, END], 'gap_rule_days': GAP_DAYS, 'firms_counted': n_firms, 'feeds_unavailable': missing,
        'events_in_sample': total, 'events_per_firm_mean': round(total / n_firms, 1) if n_firms else None,
        'events_per_year': dict(sorted(per_year.items())),
        'extrapolated_events_full_list': round(total / n_firms * len(rows)) if n_firms else None,
        'firms_with_fewer_than_20_events': sorted(t for t, n in per_firm.items() if n < 20),
        'acceptance_timing_sample': dict(timings), 'timing_sample_size': len(picks),
        'acceptance_minus_dateline_days_sample': dict(sorted(lags.items())),
    }
    OUT.write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'list_fetch'}, indent=1, default=str))


if __name__ == '__main__':
    main()
