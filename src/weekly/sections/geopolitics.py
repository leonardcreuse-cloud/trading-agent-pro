#!/usr/bin/env python3
"""
Weekly report section 'geopolitics' - Q4 "What changed geopolitically?" (phase P4.0)

Data: observations and raw payloads stored by `python main.py collect` (src/external_sources.py); this section
downloads nothing. Values are read as known at the cutoff: COALESCE(published_at, retrieved_at) <= T_c.

  Federal Register (rank 1): documents of the Office of Foreign Assets Control (sanctions), the Bureau of
    Industry and Security (export controls), the Office of the U.S. Trade Representative and presidential
    documents whose publication (06:00 New York on the publication date; documents seen before that date are
    dated by their retrieval) falls in the window (T_p, T_c]. A count or "no document" is complete only when a
    Federal Register search RETRIEVED AFTER the cutoff covers the window (publication_date >= the window start,
    a single page of results); otherwise the documents listed are a lower bound (PARTIAL_COVERAGE) and no "no
    document" statement is made. Documents are official facts about what was published, never about effects.
  GPR index (Caldara-Iacoviello, rank 2): daily geopolitical risk index built from newspaper text (academic);
    mean of the days dated in the week (s_-5, s_0] vs the previous week (s_-10, s_-5], both from the file
    version known at T_c (the file is revised; the version known at T_p is used when one is stored).
  GDELT (rank 3): automated coding of news reports, not a record of events: mean daily counts of root events
    coded as material or verbal conflict and mean Goldstein score, globally and for pre-declared country pairs
    (external_sources.GDELT_DYADS), week known at T_c vs previous week known at T_p.

Kinds: Federal Register statements are official_fact; GPR and GDELT statements are 'aggregator' (UNCERTAIN by
rule). No event is linked to any price move (timing only) and no direction of markets is implied.
"""

import json
import re
from statistics import mean
from urllib.parse import urlencode

from ...common import to_utc_iso
from ...external_sources import FR_PRESIDENTIAL, FR_URL, GDELT_DYADS
from ..core import SectionResult, conclude, evidence, unavailable
from .market import fresh_flag

NAME = 'geopolitics'
QUESTIONS = [4]
Q = 4
FR_SOURCE, GPR_SOURCE, GDELT_SOURCE = 'Federal Register', 'GPR index (Caldara-Iacoviello)', 'GDELT'
FR_LABELS = {'industry-and-security-bureau': 'Bureau of Industry and Security (export controls)',
             'foreign-assets-control-office': 'Office of Foreign Assets Control (sanctions)',
             'trade-representative-office-of-united-states': 'Office of the U.S. Trade Representative (trade)',
             FR_PRESIDENTIAL: 'Presidential documents'}
MAX_TITLES = 8
COLLECT_HINT = '`python main.py collect` stores these data; run it daily'
GDELT_METRICS = (('material_conflict_root', 'material-conflict root events / day'),
                 ('verbal_conflict_root', 'verbal-conflict root events / day'),
                 ('goldstein_mean_root', 'mean Goldstein score (root events)'))


def _weeks(tm):
    """(s_-5, s_0] and (s_-10, s_-5] as calendar-date bounds (observations dated d with lo < d <= hi)."""
    return (tm.sessions[-6], tm.s0), (tm.sessions[-11], tm.sessions[-6])


# ---------------------------------------------------------------- Federal Register

def _fr_condition(slug):
    key = ('conditions[type][]', 'PRESDOCU') if slug == FR_PRESIDENTIAL else ('conditions[agencies][]', slug)
    return urlencode([key])


def fr_coverage(db, slug, window_start, cutoff):
    """
    The newest Federal Register search for `slug` retrieved after the cutoff that covers publication dates from
    `window_start` on, in a single page of results: {'fetch_id', 'retrieved_at', 'since'} or None.
    """
    if not hasattr(db, 'connect'):
        return None
    cond = _fr_condition(slug)
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT fetch_id, completed_at, endpoint FROM source_fetches WHERE source=? AND status='OK' "
            "AND raw_path IS NOT NULL AND endpoint LIKE ? AND completed_at > ? "
            "ORDER BY completed_at DESC, fetch_id DESC", (FR_SOURCE, FR_URL + '%', to_utc_iso(cutoff)))]
    for r in rows:
        m = re.search(r'conditions%5Bpublication_date%5D%5Bgte%5D=(\d{4}-\d{2}-\d{2})', r['endpoint'])
        if cond not in r['endpoint'] or not m or m.group(1) > window_start:
            continue
        try:
            pages = json.loads(db.read_raw(r['fetch_id'])).get('total_pages', 1)
        except (RuntimeError, ValueError, TypeError, OSError, AttributeError):
            continue
        if pages and pages > 1:
            continue
        return {'fetch_id': r['fetch_id'], 'retrieved_at': r['completed_at'], 'since': m.group(1)}
    return None


def fr_documents(db, entity, start, end):
    """Documents of `entity` available in (start, end], one row per document (earliest availability)."""
    if not hasattr(db, 'connect'):
        return []
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT as_of_date, value_text, published_at, published_at_basis, retrieved_at, fetch_id, "
            "COALESCE(published_at, retrieved_at) AS available_at FROM observations WHERE source=? AND entity=? "
            "AND metric='document' ORDER BY available_at, fetch_id", (FR_SOURCE, entity))]
    first = {}
    for r in rows:
        first.setdefault(r['value_text'], r)
    lo, hi = to_utc_iso(start), to_utc_iso(end)
    return [r for r in first.values() if lo < r['available_at'] <= hi]


def _federal_register(ctx, res):
    tm = ctx.tm
    window_start = tm.previous_cutoff[:10]
    rows = []
    for slug, label in FR_LABELS.items():
        docs = fr_documents(ctx.db, f'FR:{slug}', tm.previous_cutoff, tm.cutoff)
        cover = fr_coverage(ctx.db, slug, window_start, tm.cutoff)
        parsed = [(r, json.loads(r['value_text'])) for r in docs]
        for r, d in parsed:
            rows.append([label, r['as_of_date'], d.get('type'), d.get('title'), d.get('document_number'),
                         d.get('html_url')])
        coverage = (f"search retrieved {cover['retrieved_at']} (after the cutoff) covering publication dates from "
                    f"{cover['since']}" if cover else 'no search retrieved after the cutoff covers the window')
        if not parsed and not cover:
            res.add(unavailable('overall', Q, f'Federal Register: {label} documents published in the window',
                                f'no document stored for the window and {coverage}: absence is not established; '
                                f'{COLLECT_HINT}'))
            continue
        if not parsed:
            end = min(tm.cutoff, to_utc_iso(cover['retrieved_at']))
            item = evidence(tm, FR_SOURCE, 1, f'Federal Register search for {label}: no document published in the '
                                              'window', as_of=end[:10], published_at=end,
                            retrieved_at=cover['retrieved_at'], fetch_id=cover['fetch_id'],
                            fresh=fresh_flag(ctx, end, 'event'),
                            basis='negative fact over the window (T_p, T_c]: Federal Register search retrieved after '
                                  'the cutoff')
            res.add(conclude('overall', Q, f'Federal Register, {label}: no document published in the window '
                                           f'({tm.previous_cutoff}, {tm.cutoff}] ({coverage}).', [item],
                             'official_fact'))
            continue
        items = [evidence(tm, FR_SOURCE, 1, f"{d.get('type')} {d.get('document_number')}: {d.get('title')}",
                          as_of=r['as_of_date'], published_at=r['published_at'], retrieved_at=r['retrieved_at'],
                          fetch_id=r['fetch_id'], fresh=fresh_flag(ctx, r['as_of_date'], 'event'),
                          basis=r['published_at_basis']) for r, d in parsed[:MAX_TITLES]]
        listed = '; '.join(f"{r['as_of_date']} {d.get('type')}: {d.get('title')}" for r, d in parsed[:MAX_TITLES])
        more = f'; and {len(parsed) - MAX_TITLES} more (see the table)' if len(parsed) > MAX_TITLES else ''
        count = f'{len(parsed)} document{"s" if len(parsed) > 1 else ""}' + ('' if cover else ' (at least)')
        res.add(conclude('overall', Q, f'Federal Register, {label}: {count} published in the window: {listed}{more}. '
                                       'These are official publications; their economic effect is not assessed here.',
                         items, 'official_fact', reason_codes=[] if cover else ['PARTIAL_COVERAGE'],
                         resolve=None if cover else f'a Federal Register search retrieved after the cutoff covering '
                                                    f'the window ({COLLECT_HINT})'))
    res.table('Federal Register documents published in the window', [
        'agency / type', 'publication date', 'document type', 'title', 'document number', 'link'], rows, question=Q,
        note=f'Federal Register (rank 1), documents.json searches stored by collect; window ({tm.previous_cutoff}, '
             f'{tm.cutoff}]; publication at 06:00 New York on the publication date (documents seen earlier are dated '
             'by their retrieval). Official publications only: the economic or market effect of a document is not '
             'assessed.')


# ---------------------------------------------------------------- GPR and GDELT (aggregators)

def _daily(db, entity, metric, source, known_at, lo, hi):
    """[(day, row)] dated lo < day <= hi known at `known_at`."""
    return [(d, r) for d, r in db.series(entity, metric, known_at=known_at, source=source)
            if lo < d <= hi and r['value'] is not None]


def _gpr(ctx, res):
    tm = ctx.tm
    (w_lo, w_hi), (p_lo, p_hi) = _weeks(tm)
    cur = _daily(ctx.db, 'GPR', 'gpr_daily', GPR_SOURCE, tm.cutoff, w_lo, w_hi)
    prev_c = _daily(ctx.db, 'GPR', 'gpr_daily', GPR_SOURCE, tm.cutoff, p_lo, p_hi)
    prev_p = _daily(ctx.db, 'GPR', 'gpr_daily', GPR_SOURCE, tm.previous_cutoff, p_lo, p_hi)
    if not cur:
        res.add(unavailable('overall', Q, 'GPR index (Caldara-Iacoviello) for the week',
                            f'no daily value dated in ({w_lo}, {w_hi}] in a file version known at the cutoff; '
                            f'{COLLECT_HINT}'))
        return None
    m_c = mean(r['value'] for _, r in cur)
    prev = prev_p or prev_c
    m_p = mean(r['value'] for _, r in prev) if prev else None
    which = 'as known at T_p' if prev_p else 'as known at T_c (no file version known at T_p is stored)'
    day, row = cur[-1]
    item = evidence(tm, GPR_SOURCE, 2, f'GPR daily index {day} = {row["value"]:.1f}', as_of=day,
                    published_at=row['published_at'], retrieved_at=row['retrieved_at'], fetch_id=row['fetch_id'],
                    fresh=fresh_flag(ctx, day, 'daily'), basis=row['published_at_basis'])
    partial = len(cur) < 7
    statement = (f'GPR daily index (Caldara-Iacoviello, newspaper-based, revisable): mean {m_c:.1f} over the '
                 f'{len(cur)} day(s) dated in ({w_lo}, {w_hi}] known at T_c (latest {day})'
                 + (f' vs {m_p:.1f} over {len(prev)} day(s) of the previous week {which}, change {m_c - m_p:+.1f}'
                    if m_p is not None else '; no value for the previous week')
                 + '. The index counts newspaper articles about geopolitical tensions; it is not a record of events.')
    res.add(conclude('overall', Q, statement, [item], 'aggregator',
                     reason_codes=['PARTIAL_COVERAGE'] if partial else [],
                     resolve='official primary documents (e.g. the Federal Register) for any specific event'))
    return ['GPR daily index (all articles)', round(m_p, 2) if m_p is not None else None, len(prev),
            round(m_c, 2), len(cur), None if m_p is None else round(m_c - m_p, 2), which]


def _gdelt(ctx, res, rows):
    tm = ctx.tm
    (w_lo, w_hi), (p_lo, p_hi) = _weeks(tm)
    parts, item, partial = [], None, False
    for key in ['global'] + list(GDELT_DYADS):
        entity = f'GDELT:{key}'
        for metric, label in GDELT_METRICS:
            cur = _daily(ctx.db, entity, metric, GDELT_SOURCE, tm.cutoff, w_lo, w_hi)
            prev = _daily(ctx.db, entity, metric, GDELT_SOURCE, tm.previous_cutoff, p_lo, p_hi)
            if not cur:
                continue
            m_c = mean(r['value'] for _, r in cur)
            m_p = mean(r['value'] for _, r in prev) if prev else None
            partial = partial or len(cur) < 7 or (prev and len(prev) < 7)
            rows.append([f'GDELT {key}: {label}', None if m_p is None else round(m_p, 2), len(prev), round(m_c, 2),
                         len(cur), None if m_p is None else round(m_c - m_p, 2), 'as known at T_p'])
            if metric == 'material_conflict_root':
                parts.append(f'{key} {m_p:.1f} -> {m_c:.1f}' if m_p is not None else f'{key} {m_c:.1f}')
                if item is None:
                    day, row = cur[-1]
                    item = evidence(tm, GDELT_SOURCE, 3, f'GDELT daily export {day}', as_of=day,
                                    published_at=row['published_at'], retrieved_at=row['retrieved_at'],
                                    fetch_id=row['fetch_id'], fresh=fresh_flag(ctx, day, 'daily'),
                                    basis=row['published_at_basis'])
    if item is None:
        res.add(unavailable('overall', Q, 'GDELT event counts for the week',
                            f'no GDELT daily export dated in ({w_lo}, {w_hi}] known at the cutoff; {COLLECT_HINT}'))
        return
    res.add(conclude('overall', Q, 'GDELT (automated coding of news reports, not a record of events): mean daily root '
                                   'events coded as material conflict, previous week (known at T_p) -> week (known at '
                                   f'T_c): {"; ".join(parts)}. Counts follow news volume and coding errors; no '
                                   'specific event is established by them.', [item], 'aggregator',
                     reason_codes=['PARTIAL_COVERAGE'] if partial else [],
                     resolve='official primary documents (e.g. the Federal Register) for any specific event'))


# ---------------------------------------------------------------- section

def build(ctx):
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    _federal_register(ctx, res)
    rows = []
    gpr = _gpr(ctx, res)
    if gpr:
        rows.append(gpr)
    _gdelt(ctx, res, rows)
    (w_lo, w_hi), (p_lo, p_hi) = _weeks(tm)
    res.table('Geopolitical indices from news (aggregators: GPR rank 2, GDELT rank 3)', [
        'measure', 'previous week mean', 'days (previous week)', 'week mean (known at T_c)', 'days (week)', 'change',
        'previous week values'], rows, question=Q,
        note=f'Week = days dated in ({w_lo}, {w_hi}], previous week ({p_lo}, {p_hi}] (calendar days, both series are '
             'daily including weekends). GPR (Caldara-Iacoviello daily index, 1985-2019 = 100) and GDELT (automated '
             'event coding, 12:00 UTC the day after) are built from news text: they measure coverage, not events, and '
             'are UNCERTAIN by rule. No pre-declared threshold: changes are not judged material.')
    res.add(unavailable('overall', Q, 'conflict event datasets curated by researchers (e.g. ACLED)',
                        'not ingested (no account or licence configured)'))
    res.notes.append(f'Window ({tm.previous_cutoff}, {tm.cutoff}]. Data from `python main.py collect`; nothing is '
                     'downloaded by this section. Timing only: no geopolitical event is linked to any price move.')
    return res
