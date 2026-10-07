#!/usr/bin/env python3
"""
Weekly report section 'sec_events': Q2 (what changed fundamentally?) and Q7 (what important
company-specific events occurred?), from SEC EDGAR only (rank 1).

Inputs (all through the context, point-in-time):
  ctx.filings(t)                        submissions feed: form, items, accession, acceptance_utc
                                        (the feed's 'Z' label read as UTC), published_at (the
                                        same label read as New York time: conservative, >= UTC)
  ctx.sec.fundamentals(t, known_at=T)   XBRL facts replayed by acceptance time, at T_p and T_c
  ctx.db.series / ctx.db.events         publication times of the balance-sheet facts used, and
                                        stored Form 4 transactions with availability in (T_p, T_c]

Rules applied here (docs/DATA_POLICY.md, "Evidence levels for conclusions"):
  - A filing belongs to the week when its conservative published_at is in (T_p, T_c]. A filing
    whose UTC label is before T_c but whose New York reading is after T_c is not admissible at
    T_c: it belongs to next week's report and is not mentioned here.
  - Sessions: the UTC acceptance instant converted to New York time; before 09:30 -> that
    session (pre-open), 09:30-16:00 -> during that session, from 16:00 or on a non-session day
    -> the next session; after the last session of the week -> 'no price reaction observable
    in this report'. TIMESTAMP_AMBIGUOUS only when the conservative reading changes the session.
  - Existence, form, item codes, acceptance time and accession of filings, and as-filed XBRL
    values, are official facts (SEC rank 1). Negative facts ('no 8-K in the window') need a
    submissions fetch made after T_c covering the whole window, else PARTIAL_COVERAGE.
  - Classes come from the pre-declared map below (EVENT_MAP_VERSION); the meaning of a filing
    beyond its form and item codes is not asserted. No judgement ('fundamentals improved') is
    produced by this section; deltas carry no size qualifier (no threshold is pre-declared).
Sections never call the wall clock, never write files and never download outside ctx.
"""

import bisect
import json
import math
from datetime import datetime, time
from zoneinfo import ZoneInfo

from ...common import DATA_UNAVAILABLE, to_utc_iso
from ...database import source_rank
from ...insider_tracker import FORM4_METRIC, form4_xml_url
from ...sec_parser import SEC_SOURCE
from ..core import LookAheadError, SectionResult, conclude, evidence, unavailable

NAME = 'sec_events'
QUESTIONS = [2, 7]

SEC_RANK = source_rank(SEC_SOURCE)
NEW_YORK = ZoneInfo('America/New_York')
SESSION_OPEN, SESSION_CLOSE = time(9, 30), time(16, 0)
AFTER_LAST = 'after the last session of the week: no price reaction observable in this report'

# ---------------------------------------------------------------- pre-declared maps
EVENT_MAP_VERSION = 'sec-events-map-v1-2026-10-07'
STATEMENT_FORMS = ('10-K', '10-Q', '10-K/A', '10-Q/A', '10-KT', '10-QT', '10-KT/A', '10-QT/A')
LATE_NOTICE_FORMS = ('NT 10-K', 'NT 10-Q', 'NT 10-K/A', 'NT 10-Q/A')
EIGHT_K_FORMS = ('8-K', '8-K/A')
FORM4_FORMS = ('4', '4/A')
FORM144_FORMS = ('144', '144/A')
INSIDER_FORMS = FORM4_FORMS + FORM144_FORMS

RESULTS, AGREEMENTS, MNA, FINANCING = 'results', 'agreements', 'M&A', 'financing/dilution'
GOVERNANCE, RED_FLAGS, CYBER, LISTING = 'governance', 'accounting red flags', 'cybersecurity', 'listing'
RESTRUCTURING, DISCLOSURE, OWNERSHIP, INSIDER = ('restructuring/impairment', 'disclosure', 'ownership',
                                                 'insider')
CLASS_ORDER = (RESULTS, AGREEMENTS, MNA, FINANCING, GOVERNANCE, RED_FLAGS, CYBER, LISTING,
               RESTRUCTURING, DISCLOSURE, OWNERSHIP, INSIDER)
PERIODIC_CLASS = 'periodic report (10-K / 10-Q family)'
OTHER_8K_CLASS = '8-K with no mapped item'
OTHER_CLASS = 'other form (not in the map)'
ALL_CLASSES = CLASS_ORDER + (PERIODIC_CLASS, OTHER_8K_CLASS, OTHER_CLASS)

ITEM_CLASSES = {
    '2.02': RESULTS,
    '1.01': AGREEMENTS, '1.02': AGREEMENTS,
    '2.01': MNA,
    '2.03': FINANCING, '3.02': FINANCING,
    '5.02': GOVERNANCE, '5.03': GOVERNANCE, '5.07': GOVERNANCE,
    '4.01': RED_FLAGS, '4.02': RED_FLAGS,
    '1.05': CYBER,
    '3.01': LISTING,
    '2.05': RESTRUCTURING, '2.06': RESTRUCTURING,
    '7.01': DISCLOSURE, '8.01': DISCLOSURE,
}
FORM_CLASSES = {
    'S-4': MNA, 'S-4/A': MNA, '425': MNA, 'DEFM14A': MNA,
    'S-3': FINANCING, 'S-3/A': FINANCING, 'S-3ASR': FINANCING, 'S-8': FINANCING,
    'S-8 POS': FINANCING,
    **{f: RED_FLAGS for f in LATE_NOTICE_FORMS},
    **{f: OWNERSHIP for f in ('SC 13D', 'SC 13D/A', 'SC 13G', 'SC 13G/A', 'SCHEDULE 13D',
                              'SCHEDULE 13D/A', 'SCHEDULE 13G', 'SCHEDULE 13G/A')},
    **{f: INSIDER for f in INSIDER_FORMS},
}
FINANCING_PREFIXES = ('424B',)

# Freshness cadences (database.CADENCE_MAX_AGE_DAYS), evaluated at the cutoff by ctx.freshness.
PERIODIC_CADENCE = 'quarterly_filing'   # 10-K / 10-Q: 120 days (policy)
EVENT_CADENCE = 'weekly'                # event filings: 14 days, covers any 5-session window

# Fundamental fields (SECParser.fundamentals) compared between the views at T_p and T_c.
REVENUE_KEYS = ('revenue', 'revenue_period_end', 'revenue_growth_pct', 'revenue_prior_year',
                'revenue_tag', 'revenue_method')
BALANCE_KEYS = ('debt', 'debt_definition', 'debt_tags', 'equity', 'equity_tag', 'debt_to_equity',
                'balance_sheet_date', 'latest_equity_date', 'debt_includes_finance_leases')
TABLE_FIELDS = (   # (key, label, kind)
    ('revenue', 'revenue TTM (USD m)', 'usd'),
    ('revenue_period_end', 'revenue TTM period end', 'date'),
    ('revenue_growth_pct', 'revenue growth TTM vs one year earlier (%)', 'pct'),
    ('revenue_prior_year', 'revenue TTM one year earlier (USD m)', 'usd'),
    ('revenue_tag', 'revenue XBRL tag', 'text'),
    ('revenue_method', 'revenue TTM method', 'text'),
    ('debt', 'debt (USD m)', 'usd'),
    ('debt_definition', 'debt definition', 'text'),
    ('debt_tags', 'debt XBRL tags', 'text'),
    ('debt_includes_finance_leases', 'debt includes finance leases', 'text'),
    ('equity', 'stockholders equity (USD m)', 'usd'),
    ('equity_tag', 'equity XBRL tag', 'text'),
    ('debt_to_equity', 'debt / equity', 'ratio'),
    ('balance_sheet_date', 'balance sheet date', 'date'),
    ('latest_equity_date', 'latest equity date', 'date'),
)
CORE_FIELDS = (('revenue', 'revenue TTM'), ('revenue_growth_pct', 'revenue growth'),
               ('debt', 'debt'), ('equity', 'stockholders equity'),
               ('debt_to_equity', 'debt-to-equity'))
NCI_EQUITY_TAG = 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'

EVENT_COLUMNS = ('session', 'timing (New York)', 'accepted (UTC label)', 'accepted (New York)',
                 'form', 'items', 'class', 'accession', 'available at (conservative)',
                 'session flag')


# ---------------------------------------------------------------- helpers

def _fresh(ctx, as_of, cadence):
    """True / False / None (unknown) from ctx.freshness at the cutoff."""
    if not as_of:
        return None
    status = (ctx.freshness(str(as_of)[:10], cadence) or {}).get('status')
    return True if status == 'FRESH' else False if status == 'STALE' else None


def _usd(v):
    return 'N/A' if v is None else f'{v / 1e6:,.1f} M USD'


def _millions(v):
    return None if v is None else round(v / 1e6, 2)


def _differs(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
            and not isinstance(a, bool) and not isinstance(b, bool):
        return not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9)
    return a != b


def _ny(instant):
    return datetime.fromisoformat(to_utc_iso(instant)).astimezone(NEW_YORK)


def _next_session(sessions, day):
    i = bisect.bisect_right(sessions, day)
    return sessions[i] if i < len(sessions) else None


def map_session(instant, sessions):
    """
    (session or None, timing label) for an instant; sessions = sorted ISO dates up to s_0.
    None means after the last session of the week (no session of the report is affected).
    """
    local = _ny(instant)
    day, clock = local.date().isoformat(), local.time().replace(tzinfo=None)
    if day in sessions:
        if clock < SESSION_OPEN:
            return day, f'before the open of {day} (pre-open)'
        if clock < SESSION_CLOSE:
            return day, f'during the session of {day}'
        label = f'after the close of {day}'
    else:
        label = f'{day} is not a session day'
    return _next_session(sessions, day), label


def session_of(filing, sessions):
    """Session mapping of one filing (UTC label) with the ambiguity check (New York reading)."""
    accepted, published = filing.get('acceptance_utc'), filing.get('published_at')
    conservative = map_session(published, sessions)[0] if published else None
    if accepted:
        session, timing = map_session(accepted, sessions)
        ambiguous = published is not None and conservative != session
    else:
        session, timing = conservative, ('acceptance time not in the feed: conservative bound = '
                                         'end of the filing date')
        ambiguous = True
    return {'session': session, 'timing': timing, 'conservative_session': conservative,
            'ambiguous': ambiguous}


def classify(form, items):
    """Classes of a filing from the pre-declared map (several for a multi-item 8-K)."""
    form = (form or '').strip().upper()
    if form in EIGHT_K_FORMS:
        classes = [ITEM_CLASSES[i] for i in items or [] if i in ITEM_CLASSES]
        return list(dict.fromkeys(classes)) or [OTHER_8K_CLASS]
    if form in FORM_CLASSES:
        return [FORM_CLASSES[form]]
    if form.startswith(FINANCING_PREFIXES):
        return [FINANCING]
    if form in STATEMENT_FORMS:
        return [PERIODIC_CLASS]
    return [OTHER_CLASS]


def _session_text(m):
    return m['session'] if m['session'] else AFTER_LAST


def _window_filings(ctx, feed):
    """Filings of the feed available in (T_p, T_c], deduplicated by accession, by acceptance."""
    seen, rows = set(), []
    for f in feed.get('filings') or []:
        accession = f.get('accession_number')
        if not accession or accession in seen or not ctx.tm.in_window(f.get('published_at')):
            continue
        seen.add(accession)
        rows.append(f)
    return sorted(rows, key=lambda f: (to_utc_iso(f.get('acceptance_utc') or f['published_at']),
                                       f['accession_number']))


def _coverage(ctx, feed):
    """(complete, problem) of the submissions feed for negative facts over the whole window."""
    if feed.get('status') != 'OK':
        return False, f"SEC submissions feed unavailable: {feed.get('reason')}"
    problems = []
    retrieved = (feed.get('fetch') or {}).get('retrieved_at')
    if feed.get('retrieved_after_cutoff') is not True:
        problems.append(f'submissions feed retrieved at {retrieved}, not after the cutoff '
                        f'{ctx.tm.cutoff}: filings accepted after that retrieval are missing')
    if not any(f.get('published_at') and to_utc_iso(f['published_at']) <= ctx.tm.previous_cutoff
               for f in feed.get('filings') or []):
        problems.append('the feed lists no filing older than the window start: its recent block '
                        'may not cover the whole window')
    return not problems, '; '.join(problems) or None


def _feed(ctx, ticker):
    try:
        return ctx.filings(ticker)
    except LookAheadError:
        raise
    except Exception as e:  # noqa: BLE001 - one company must not stop the section
        return {'status': DATA_UNAVAILABLE, 'filings': [], 'fetch': None,
                'reason': f'{type(e).__name__}: {e}'}


def _filing_evidence(ctx, feed, f):
    fetch = feed.get('fetch') or {}
    cadence = PERIODIC_CADENCE if f['form'] in STATEMENT_FORMS else EVENT_CADENCE
    items = f" items {','.join(f['items'])}" if f.get('items') else ''
    return evidence(ctx.tm, SEC_SOURCE, SEC_RANK,
                    f"{f['form']}{items} accession {f['accession_number']} accepted "
                    f"{f.get('acceptance_utc') or 'time not provided'} (UTC label)",
                    as_of=f.get('report_date') or f.get('filing_date'),
                    published_at=f['published_at'], retrieved_at=fetch.get('retrieved_at'),
                    fetch_id=fetch.get('fetch_id'), fresh=_fresh(ctx, f['published_at'], cadence),
                    basis=f.get('published_at_basis'))


def _feed_evidence(ctx, feed, fact, complete):
    """Evidence for a negative fact over the window: the submissions feed itself."""
    fetch = feed.get('fetch') or {}
    retrieved = to_utc_iso(fetch.get('retrieved_at'))
    end = min(ctx.tm.cutoff, retrieved) if retrieved else ctx.tm.cutoff
    basis = ('negative fact over the window (T_p, T_c]: SEC submissions feed retrieved after the cutoff'
             if complete else f'negative fact covering the window only up to {end} (feed retrieval)')
    return evidence(ctx.tm, SEC_SOURCE, SEC_RANK, fact, as_of=end[:10], published_at=end,
                    retrieved_at=retrieved, fetch_id=fetch.get('fetch_id'),
                    fresh=_fresh(ctx, end, EVENT_CADENCE), basis=basis)


# ---------------------------------------------------------------- Q7

def _q7_company(ctx, res, t, feed, window, complete, problem):
    tm = ctx.tm
    counts = dict.fromkeys(ALL_CLASSES, 0)
    if feed.get('status') != 'OK':
        res.add(unavailable(t, 7, 'SEC filings accepted in the window (events, Form 4, Form 144)',
                            f"SEC submissions feed unavailable: {feed.get('reason')}"))
        return None
    partial = [] if complete else ['PARTIAL_COVERAGE']
    resolve = 'a SEC submissions fetch made after the cutoff covering the whole window'

    rows, mapped = [], []
    for f in window:
        m = session_of(f, tm.sessions)
        classes = classify(f['form'], f.get('items'))
        for c in classes:
            counts[c] += 1
        mapped.append((f, m, classes))
        rows.append([_session_text(m), m['timing'], f.get('acceptance_utc'),
                     _ny(f['acceptance_utc']).strftime('%Y-%m-%d %H:%M:%S %Z')
                     if f.get('acceptance_utc') else None,
                     f['form'], ', '.join(f.get('items') or []) or None, '; '.join(classes),
                     f['accession_number'], f['published_at'],
                     'TIMESTAMP_AMBIGUOUS' if m['ambiguous'] else None])
    res.table(f'{t}: every SEC filing available in the window ({tm.previous_cutoff}, {tm.cutoff}]',
              EVENT_COLUMNS, rows, scope=t, question=7,
              note=(f"Classes: pre-declared map {EVENT_MAP_VERSION}. Session: acceptance label read as "
                    "UTC, converted to New York time. 'available at' is the conservative New York "
                    "reading used for admissibility. "
                    + ('' if complete else f'Coverage incomplete: {problem}.')))

    for f, m, classes in mapped:
        if f['form'] in INSIDER_FORMS:
            continue                       # aggregated below
        items = f"items {', '.join(f['items'])}; " if f.get('items') else ''
        when = (f"accepted {f['acceptance_utc']} (UTC label, "
                f"{_ny(f['acceptance_utc']).strftime('%H:%M %Z')} New York)"
                if f.get('acceptance_utc') else f"filed {f.get('filing_date')} (no acceptance time)")
        if m['ambiguous']:
            where = 'session attribution ambiguous (separate record)'
        elif m['session']:
            where = f"mapped to session {m['session']} ({m['timing']})"
        else:
            where = AFTER_LAST
        ev = _filing_evidence(ctx, feed, f)
        res.add(conclude(t, 7, f"{t}: {f['form']} {when}, {items}class {'; '.join(classes)}, "
                               f"accession {f['accession_number']}; {where}", [ev], 'official_fact'))
        if m['ambiguous']:
            res.add(conclude(
                t, 7, f"{t}: session of {f['form']} accession {f['accession_number']} is ambiguous: "
                      f"{_session_text(m)} with the acceptance label read as UTC, "
                      f"{m['conservative_session'] or AFTER_LAST} with the conservative New York reading",
                [ev], 'official_fact', ['TIMESTAMP_AMBIGUOUS'],
                resolve='an acceptance time with an explicit time zone (EDGAR filing header)'))
        if f['form'] in EIGHT_K_FORMS and '2.02' in (f.get('items') or []):
            res.add(unavailable(t, 2, f"figures of the results 8-K accession {f['accession_number']}",
                                'NOT IMPLEMENTED: exhibit 99.1 is not XBRL-tagged and is not parsed; '
                                'figures quoted by news would be aggregator-level only'))

    if not any(f['form'] in EIGHT_K_FORMS for f in window):
        res.add(conclude(t, 7, f'{t}: no 8-K or 8-K/A accepted in the window '
                               f'({tm.previous_cutoff}, {tm.cutoff}]',
                         [_feed_evidence(ctx, feed, f'{t}: no 8-K in the submissions feed for the window',
                                         complete)], 'official_fact', partial, resolve=resolve))
    zero = [c for c in CLASS_ORDER if counts[c] == 0]
    if not window:
        res.add(conclude(t, 7, f'{t}: no SEC filing of any form accepted in the window',
                         [_feed_evidence(ctx, feed, f'{t}: no filing in the submissions feed for the window',
                                         complete)], 'official_fact', partial, resolve=resolve))
    elif zero:
        res.add(conclude(t, 7, f"{t}: no filing of the pre-declared classes {', '.join(zero)} accepted "
                               'in the window',
                         [_feed_evidence(ctx, feed, f'{t}: classes absent from the window: {zero}',
                                         complete)], 'official_fact', partial, resolve=resolve))
    _insider(ctx, res, t, feed, window, complete, partial, resolve)
    return counts


def _insider(ctx, res, t, feed, window, complete, partial, resolve):
    """Form 4 count and open-market P/S totals from stored transactions; Form 144 notices."""
    tm = ctx.tm
    form4 = [f for f in window if f['form'] == '4']
    form4a = [f for f in window if f['form'] == '4/A']
    form144 = [f for f in window if f['form'] in FORM144_FORMS]
    events = ctx.db.events(t, FORM4_METRIC, published_from=tm.previous_cutoff,
                           published_to=tm.cutoff, source=SEC_SOURCE)
    txns, unreadable = [], 0
    for e in events:
        try:
            row = json.loads(e['value_text'])
        except (TypeError, ValueError):
            unreadable += 1
            continue
        row['_available_at'] = e['available_at']
        txns.append(row)
    with_rows = {x.get('accession') for x in txns}
    try:
        cik = ctx.sec.get_cik(t)
    except Exception:  # noqa: BLE001 - only used to check stored documents
        cik = None
    docs = {}                              # accession -> stored XML fetch (None: not found)
    for f in form4:
        docs[f['accession_number']] = (ctx.db.latest_fetch(SEC_SOURCE, form4_xml_url(
            cik, f['accession_number'], f['primary_document'])) if cik and f.get('primary_document') else None)
    # read = transactions stored, or document stored with no non-derivative transaction in it
    unknown = [a for a, doc in docs.items() if a not in with_rows and not doc]
    fetched = len(docs) - len(unknown)

    def side(code):
        rows = [x for x in txns if x.get('code') == code]
        return {'n': len(rows), 'shares': round(sum(x['shares'] for x in rows if x.get('shares')), 2),
                'usd': round(sum(x['value_usd'] for x in rows if x.get('value_usd')), 2),
                'unknown_value': sum(1 for x in rows if not x.get('value_usd')),
                'owners': len({(x.get('owners') or [x.get('accession')])[0] for x in rows}),
                'rows': rows}
    buys, sells = side('P'), side('S')
    planned = round(sum(x['value_usd'] for x in sells['rows']
                        if x.get('value_usd') and x.get('rule_10b5_1') is True), 2)
    not_planned = round(sum(x['value_usd'] for x in sells['rows']
                            if x.get('value_usd') and x.get('rule_10b5_1') is False), 2)
    plan_unknown = round(sum(x['value_usd'] for x in sells['rows']
                             if x.get('value_usd') and x.get('rule_10b5_1') is None), 2)
    other = {}
    for x in txns:
        if x.get('code') not in ('P', 'S'):
            other[x.get('code') or '?'] = other.get(x.get('code') or '?', 0) + 1
    other_text = ', '.join(f'{k}: {v}' for k, v in sorted(other.items())) or 'none'

    res.table(f'{t}: Form 4 in the window (stored transactions, availability in the window)',
              ('measure', 'value'), [
                  ['Form 4 filings accepted in the window', len(form4)],
                  ['Form 4/A filings accepted in the window (not parsed)', len(form4a)],
                  ['Form 4 documents read (stored XML)', fetched],
                  ['Form 4 documents not read', len(unknown)],
                  ['stored non-derivative transactions', len(txns)],
                  ['open-market purchases (P): transactions', buys['n']],
                  ['open-market purchases (P): shares', buys['shares']],
                  ['open-market purchases (P): USD (known values)', buys['usd']],
                  ['open-market purchases (P): transactions with unknown value', buys['unknown_value']],
                  ['open-market purchases (P): distinct primary reporting owners', buys['owners']],
                  ['open-market sales (S): transactions', sells['n']],
                  ['open-market sales (S): shares', sells['shares']],
                  ['open-market sales (S): USD (known values)', sells['usd']],
                  ['open-market sales (S): transactions with unknown value', sells['unknown_value']],
                  ['open-market sales (S): USD on filings ticking the Rule 10b5-1 box', planned],
                  ['open-market sales (S): USD on filings not ticking it', not_planned],
                  ['open-market sales (S): USD on forms without the checkbox', plan_unknown],
                  ['open-market sales (S): distinct primary reporting owners', sells['owners']],
                  ['other transaction codes (not open-market)', other_text],
                  ['Form 144 notices accepted in the window', len(form144)],
              ], scope=t, question=7,
              note='Transactions are keyed on filing availability (published_at), not on the '
                   'transaction date: Form 4 is due within 2 business days, so reported trades can '
                   'predate the window. Distinct owners: one per filing (primary reporting owner). '
                   'A Form 144 is a notice of a proposed sale, not a sale.')

    codes = list(partial)
    if unknown or form4a or unreadable:
        codes.append('PARTIAL_COVERAGE')
    if form4 or txns:
        items = []
        if form4:
            last = max(form4, key=lambda f: to_utc_iso(f['published_at']))
            items.append(_filing_evidence(ctx, feed, last) | {
                'fact': f"{len(form4)} Form 4 filing(s) in the window, latest {last['accession_number']}"})
        by_accession = {}
        for x in txns:
            by_accession.setdefault(x.get('accession'), []).append(x)
        for accession, rows in by_accession.items():     # one item per Form 4 document read
            doc = docs.get(accession) or {}
            pub = max(to_utc_iso(x['_available_at']) for x in rows)
            codes_seen = ','.join(sorted({str(x.get('code')) for x in rows}))
            items.append(evidence(tm, SEC_SOURCE, SEC_RANK,
                                  f'Form 4 {accession}: {len(rows)} stored non-derivative transaction(s), '
                                  f'codes {codes_seen}', as_of=max(str(x.get('date')) for x in rows),
                                  published_at=pub, retrieved_at=doc.get('retrieved_at'),
                                  fetch_id=doc.get('fetch_id'), fresh=_fresh(ctx, pub, EVENT_CADENCE),
                                  basis='filing acceptance time (New York reading)'))
        gaps = []
        if unknown:
            gaps.append(f"{len(unknown)} Form 4 document(s) not read ({', '.join(unknown[:5])})")
        if form4a:
            gaps.append(f'{len(form4a)} Form 4/A not parsed')
        if unreadable:
            gaps.append(f'{unreadable} stored transaction(s) unreadable')
        statement = (f"{t}: {len(form4)} Form 4 filing(s) accepted in the window; stored open-market "
                     f"purchases (P): {buys['n']} transaction(s), {buys['shares']:,.0f} shares, "
                     f"{buys['usd']:,.0f} USD by {buys['owners']} primary owner(s); open-market sales (S): "
                     f"{sells['n']} transaction(s), {sells['shares']:,.0f} shares, {sells['usd']:,.0f} USD "
                     f"({planned:,.0f} USD on filings ticking the Rule 10b5-1 box, {not_planned:,.0f} not "
                     f"ticking it, {plan_unknown:,.0f} without the checkbox) by {sells['owners']} primary "
                     f"owner(s); other codes: {other_text}")
        if buys['unknown_value'] or sells['unknown_value']:
            statement += (f"; {buys['unknown_value'] + sells['unknown_value']} P/S transaction(s) with "
                          'unknown value (not counted in USD totals)')
        if gaps:
            statement += '; coverage gaps: ' + '; '.join(gaps)
        res.add(conclude(t, 7, statement, items, 'official_fact', codes,
                         resolve='read every Form 4 / 4/A document of the window' if gaps else None))
    else:
        res.add(conclude(t, 7, f'{t}: no Form 4 filing accepted in the window',
                         [_feed_evidence(ctx, feed, f'{t}: no Form 4 in the submissions feed for the window',
                                         complete)], 'official_fact', partial, resolve=resolve))
    if form144:
        res.add(conclude(t, 7, f'{t}: {len(form144)} Form 144 notice(s) of proposed sale accepted in the '
                               f"window ({', '.join(f['accession_number'] for f in form144)}); a notice is "
                               'not a sale',
                         [_filing_evidence(ctx, feed, f) for f in form144], 'official_fact'))


# ---------------------------------------------------------------- Q2

def _fundamentals(ctx, t, known_at):
    try:
        return ctx.sec.fundamentals(t, known_at=known_at)
    except LookAheadError:
        raise
    except Exception as e:  # noqa: BLE001 - one company must not stop the section
        return {'status': DATA_UNAVAILABLE, 'fetch': None, 'reason': f'{type(e).__name__}: {e}'}


def _balance_published(ctx, t, F, known_at):
    """Latest publication time of the balance-sheet facts used by F, or None when unknown."""
    day = F.get('balance_sheet_date')
    tags = list(F.get('debt_tags') or []) + ([F['equity_tag']] if F.get('equity_tag') else [])
    if not day or not tags:
        return None
    pubs = []
    for tag in tags:
        rows = dict(ctx.db.series(t, f'xbrl:{tag}', known_at=known_at, source=SEC_SOURCE,
                                  start=day, end=day))
        row = rows.get(day)
        if not row or not row.get('published_at'):
            return None
        pubs.append(to_utc_iso(row['published_at']))
    return max(pubs)


def _fact_evidence(ctx, F, fact, published, as_of, known_at, label):
    fetch = F.get('fetch') or {}
    if published and published > to_utc_iso(known_at):
        raise LookAheadError(f'{SEC_SOURCE}: {fact!r} published {published}, after the view instant '
                             f'{label} = {known_at}')
    if published:
        pub, fresh = published, _fresh(ctx, published, PERIODIC_CADENCE)
        basis = 'acceptance time of the latest filing among the inputs (New York reading)'
    else:
        pub, fresh = known_at, None
        basis = f'upper bound: point-in-time replay known_at {label} (input publication time not available)'
    return evidence(ctx.tm, SEC_SOURCE, SEC_RANK, fact, as_of=as_of, published_at=pub,
                    retrieved_at=fetch.get('retrieved_at'), fetch_id=fetch.get('fetch_id'), fresh=fresh,
                    basis=basis)


def _describe_revenue(F):
    if F.get('revenue') is None:
        return 'revenue TTM not computable'
    growth = (f"{F['revenue_growth_pct']} % vs one year earlier" if F.get('revenue_growth_pct') is not None
              else 'growth not computable')
    return (f"revenue TTM {_usd(F['revenue'])} (period end {F.get('revenue_period_end')}, "
            f"{F.get('revenue_tag')}, {F.get('revenue_method')}), {growth}")


def _describe_balance(F):
    if not F.get('balance_sheet_date'):
        return 'no balance sheet reported'
    debt = (f"debt {_usd(F['debt'])} ({F.get('debt_definition')}"
            + (', includes finance leases' if F.get('debt_includes_finance_leases') else '') + ')'
            if F.get('debt') is not None else 'debt not reported')
    equity = (f"stockholders equity {_usd(F['equity'])}"
              + (' (includes noncontrolling interests)' if F.get('equity_tag') == NCI_EQUITY_TAG else '')
              if F.get('equity') is not None else 'equity not reported')
    ratio = (f"debt/equity {F['debt_to_equity']}" if F.get('debt_to_equity') is not None
             else 'debt/equity not available')
    return f"{debt}, {equity}, {ratio} at balance-sheet date {F['balance_sheet_date']}"


def _delta(kind, p, c):
    if p is None or c is None:
        return None
    if kind == 'usd':
        return round((c - p) / 1e6, 2)
    if kind in ('pct', 'ratio'):
        return round(c - p, 4)
    if kind == 'date':
        return f'{(datetime.fromisoformat(str(c)[:10]) - datetime.fromisoformat(str(p)[:10])).days:+d} d'
    return None


def _shown(kind, v):
    if v is None:
        return None
    if kind == 'usd':
        return _millions(v)
    if isinstance(v, (list, tuple)):
        return ', '.join(map(str, v))
    return v if not isinstance(v, bool) else str(v)


def _q2_company(ctx, res, t, feed, window, complete, problem):
    tm = ctx.tm
    T_p, T_c = tm.previous_cutoff, tm.cutoff
    resolve = 'a SEC submissions fetch made after the cutoff covering the whole window'
    statements = late = None
    if feed.get('status') == 'OK':
        statements = [f for f in window if f['form'] in STATEMENT_FORMS]
        late = [f for f in window if f['form'] in LATE_NOTICE_FORMS]
        rows = [[f['form'], f.get('acceptance_utc'), f.get('report_date'), f.get('filing_date'),
                 f['accession_number'], f['published_at']] for f in statements + late]
        res.table(f'{t}: new periodic filings available in the window', (
            'form', 'accepted (UTC label)', 'period (report date)', 'filing date', 'accession',
            'available at (conservative)'), rows, scope=t, question=2,
            note=None if rows else 'none (10-K / 10-Q family, amendments and NT notices checked)')
        for f in statements:
            res.add(conclude(t, 2, f"{t}: {f['form']} for period {f.get('report_date')} accepted "
                                   f"{f.get('acceptance_utc')} (UTC label), accession {f['accession_number']}: "
                                   'a new periodic financial statement in the window',
                             [_filing_evidence(ctx, feed, f)], 'official_fact'))
        for f in late:
            res.add(conclude(t, 2, f"{t}: {f['form']} (notification of late filing) accepted "
                                   f"{f.get('acceptance_utc')} (UTC label), accession {f['accession_number']}",
                             [_filing_evidence(ctx, feed, f)], 'official_fact'))
        if not statements:
            res.add(conclude(t, 2, f'{t}: no new periodic financial statements accepted in the window '
                                   f'({T_p}, {T_c}]',
                             [_feed_evidence(ctx, feed, f'{t}: no 10-K / 10-Q (or amendment) in the '
                                                        'submissions feed for the window', complete)],
                             'official_fact', [] if complete else ['PARTIAL_COVERAGE'], resolve=resolve))
    else:
        res.add(unavailable(t, 2, 'periodic filings accepted in the window',
                            f"SEC submissions feed unavailable: {feed.get('reason')}"))

    F_p, F_c = _fundamentals(ctx, t, T_p), _fundamentals(ctx, t, T_c)
    summary = {'statements': None if statements is None else len(statements),
               'late': None if late is None else len(late), 'revenue_changed': None,
               'balance_changed': None, 'revisions': 0,
               'facts_retrieved_at': (F_c.get('fetch') or {}).get('retrieved_at')}
    if not F_c.get('fetch') or not F_p.get('fetch'):
        for label, F in (('T_p', F_p), ('T_c', F_c)):
            if not F.get('fetch'):
                res.add(unavailable(t, 2, f'fundamentals as known at {label}',
                                    F.get('reason') or 'SEC XBRL company facts unavailable'))
        return summary

    facts_after = to_utc_iso(F_c['fetch'].get('retrieved_at') or '') or ''
    facts_complete = facts_after > T_c
    complete_q2 = facts_complete and (complete if statements is not None else False)
    coverage_note = []
    if not facts_complete:
        coverage_note.append(f'XBRL company facts retrieved at {facts_after or "unknown"}, not after the cutoff')
    if not complete:
        coverage_note.append(problem or 'submissions coverage unknown')

    pubs = {
        ('revenue', 'T_p'): to_utc_iso(F_p.get('revenue_published_at')),
        ('revenue', 'T_c'): to_utc_iso(F_c.get('revenue_published_at')),
        ('balance', 'T_p'): _balance_published(ctx, t, F_p, T_p),
        ('balance', 'T_c'): _balance_published(ctx, t, F_c, T_c),
    }
    rows = [[label, _shown(kind, F_p.get(key)), _shown(kind, F_c.get(key)),
             _delta(kind, F_p.get(key), F_c.get(key)),
             'yes' if _differs(F_p.get(key), F_c.get(key)) else 'no']
            for key, label, kind in TABLE_FIELDS]
    rows += [['revenue inputs: latest publication', pubs[('revenue', 'T_p')], pubs[('revenue', 'T_c')],
              None, None],
             ['balance-sheet inputs: latest publication', pubs[('balance', 'T_p')],
              pubs[('balance', 'T_c')], None, None]]
    res.table(f'{t}: SEC XBRL fundamentals as known at T_p and at T_c', (
        'field', f'as known at T_p ({T_p})', f'as known at T_c ({T_c})', 'delta (T_c - T_p)', 'changed'),
        rows, scope=t, question=2,
        note=(f"Thresholds {(ctx.weekly or {}).get('thresholds_version')}: no fundamental-change threshold "
              'is pre-declared, so deltas carry no size qualifier. TTM revenue may be derived (FY + YTD - '
              'prior-year YTD, single tag). Company facts fetch '
              f"{F_c['fetch'].get('fetch_id')} retrieved {facts_after}."
              + (' Coverage: ' + '; '.join(coverage_note) + '.' if coverage_note else '')))

    revision_rows = []
    for group, keys, comparability, describe, has in (
            ('revenue', REVENUE_KEYS, ('revenue_tag',), _describe_revenue,
             lambda F: F.get('revenue') is not None),
            ('balance sheet', BALANCE_KEYS, ('debt_definition', 'equity_tag'), _describe_balance,
             lambda F: bool(F.get('balance_sheet_date')))):
        short = 'revenue' if group == 'revenue' else 'balance'
        p_has, c_has = has(F_p), has(F_c)
        changed = any(_differs(F_p.get(k), F_c.get(k)) for k in keys)
        summary[f'{short}_changed'] = changed
        if not p_has and not c_has:
            continue                        # reported below as DATA UNAVAILABLE
        as_of = (lambda F: F.get('revenue_period_end')) if short == 'revenue' else \
            (lambda F: F.get('balance_sheet_date'))
        ev_p = _fact_evidence(ctx, F_p, f'{t} {describe(F_p)} (as known at T_p)', pubs[(short, 'T_p')],
                              as_of(F_p), T_p, 'T_p') if p_has else None
        ev_c = _fact_evidence(ctx, F_c, f'{t} {describe(F_c)} (as known at T_c)', pubs[(short, 'T_c')],
                              as_of(F_c), T_c, 'T_c') if c_has else None
        codes = [] if complete_q2 else ['PARTIAL_COVERAGE']
        resolve_q2 = None
        statement_pubs = {to_utc_iso(f['published_at']) for f in statements or []}
        if not changed:
            statement = f'{t}: {group} as known at T_c: {describe(F_c)}; unchanged from the view at T_p'
            items = [ev_c]
            if statements and pubs[(short, 'T_c')] not in statement_pubs:
                codes.append('PARTIAL_COVERAGE')
                statement += (f"; {', '.join(f['form'] + ' ' + f['accession_number'] for f in statements)} "
                              f'accepted in the window but no {group} input carries its acceptance time')
                resolve_q2 = 'company facts that include the XBRL facts of the new periodic filing'
        elif statements is None:
            statement = (f'{t}: {group}: {describe(F_p)} as known at T_p -> {describe(F_c)} as known at T_c; '
                         'whether a periodic statement was accepted in the window is unknown '
                         '(submissions feed unavailable)')
            items = [e for e in (ev_p, ev_c) if e]
            codes.append('PARTIAL_COVERAGE')
        elif statements:
            matched = [f for f in statements if to_utc_iso(f['published_at']) == pubs[(short, 'T_c')]]
            link = (f"the T_c inputs carry the acceptance time of {matched[0]['form']} "
                    f"{matched[0]['accession_number']}" if matched else
                    'periodic statement(s) accepted in the window: '
                    + ', '.join(f['form'] + ' ' + f['accession_number'] for f in statements))
            statement = f'{t}: {group}: {describe(F_p)} as known at T_p -> {describe(F_c)} as known at T_c; {link}'
            items = [e for e in (ev_p, ev_c) if e]
            if p_has and c_has and any(_differs(F_p.get(k), F_c.get(k)) for k in comparability):
                codes.append('COMPARABILITY_BREAK')
        else:
            statement = (f'{t}: {group} view changed with no periodic financial statement accepted in the '
                         f'window (revised fact version or ingestion change): {describe(F_p)} as known at '
                         f'T_p -> {describe(F_c)} as known at T_c')
            items = [e for e in (ev_p, ev_c) if e]
            codes.append('CONFLICTING_SOURCES')
            resolve_q2 = 'identify the filing (accession) that carries the revised fact version'
            for key, label, kind in TABLE_FIELDS:
                if key in keys and _differs(F_p.get(key), F_c.get(key)):
                    revision_rows.append([label, _shown(kind, F_p.get(key)), _shown(kind, F_c.get(key)),
                                          pubs[(short, 'T_p')], pubs[(short, 'T_c')],
                                          'no periodic statement accepted in the window'])
        res.add(conclude(t, 2, statement, items, 'official_fact', codes, resolve=resolve_q2))

    summary['revisions'] = len(revision_rows)
    res.table(f'{t}: revisions / restatements (fundamentals changed without a periodic filing)', (
        'field', 'as known at T_p', 'as known at T_c', 'T_p inputs published', 'T_c inputs published',
        'note'), revision_rows, scope=t, question=2,
        note=None if revision_rows else (
            'not determinable: submissions feed unavailable' if statements is None
            else 'none: no field changed without a periodic statement accepted in the window'))

    missing = {}
    for label, F in (('T_p', F_p), ('T_c', F_c)):
        fields = tuple(name for key, name in CORE_FIELDS if F.get(key) is None)
        if fields:
            reason = F.get('reason') or 'not reported in the stored XBRL company facts'
            missing.setdefault((fields, reason), []).append(label)
    for (fields, reason), labels in missing.items():
        res.add(unavailable(t, 2, f"{', '.join(fields)} as known at {' and '.join(labels)}", reason))
    return summary


# ---------------------------------------------------------------- build

def build(ctx):
    tm = ctx.tm
    res = SectionResult(NAME, QUESTIONS)
    version = (ctx.weekly or {}).get('thresholds_version')
    res.notes += [
        f'Window ({tm.previous_cutoff}, {tm.cutoff}] (T_p, T_c]; thresholds {version}; event classes: '
        f'pre-declared map {EVENT_MAP_VERSION}.',
        'Admissibility uses the SEC acceptance label read as New York time (conservative). Session '
        'mapping uses the label read as UTC; TIMESTAMP_AMBIGUOUS marks filings whose session changes '
        'under the New York reading. Early closes (13:00 ET) are not modelled: no source in the system.',
        'Filings accepted before T_c under the UTC reading but admissible only after T_c under the '
        "conservative reading belong to next week's report.",
        "Freshness: 10-K / 10-Q family 'quarterly_filing' (120 d); event filings and negative facts "
        "'weekly' (14 d), evaluated at the cutoff.",
        'Item 5.02 covers both departures and appointments; the code alone does not say which. An 8-K/A '
        'repeats an earlier event (link to the original not parsed). Rule 10b5-1 sales are planned.',
        'No interpretation of filing content is made: classes are item-code lookups only; timing is '
        'described with session mapping, no causal link to any price move is asserted.',
    ]

    q2_rows, class_counts, filing_counts = [], {}, {}
    for t in ctx.universe:
        feed = _feed(ctx, t)
        ok = feed.get('status') == 'OK'
        window = _window_filings(ctx, feed) if ok else []
        complete, problem = _coverage(ctx, feed)
        s2 = _q2_company(ctx, res, t, feed, window, complete, problem)
        class_counts[t] = _q7_company(ctx, res, t, feed, window, complete, problem)
        filing_counts[t] = len(window) if ok else None
        fetch = feed.get('fetch') or {}
        q2_rows.append([t, s2['statements'], s2['late'],
                        None if s2['revenue_changed'] is None else ('yes' if s2['revenue_changed'] else 'no'),
                        None if s2['balance_changed'] is None else ('yes' if s2['balance_changed'] else 'no'),
                        s2['revisions'], fetch.get('retrieved_at'),
                        feed.get('retrieved_after_cutoff') if ok else None,
                        s2['facts_retrieved_at']])

    tickers = list(ctx.universe)
    class_rows = []
    for c in ALL_CLASSES:
        values = [class_counts[t][c] if class_counts[t] is not None else None for t in tickers]
        class_rows.append([c] + values + [sum(v for v in values if v is not None)
                                          if all(v is not None for v in values) else None])
    totals = [filing_counts[t] for t in tickers]
    class_rows.append(['filings (distinct accessions)'] + totals
                      + [sum(totals) if all(v is not None for v in totals) else None])
    overall = []
    res.table('SEC filings in the window by class, all companies', ['class'] + tickers + ['total'],
              class_rows, scope='overall', question=7,
              note=f'Pre-declared map {EVENT_MAP_VERSION}; an 8-K with several mapped items counts once '
                   'in each class. N/A: submissions feed unavailable.')
    overall.append(res.tables.pop())
    res.table('Fundamental changes per company (SEC XBRL, views at T_p and T_c)', (
        'company', 'periodic statements in window', 'NT late notices in window', 'revenue view changed',
        'balance-sheet view changed', 'revision rows', 'submissions retrieved', 'retrieved after cutoff',
        'company facts retrieved'), q2_rows, scope='overall', question=2)
    overall.append(res.tables.pop())
    res.tables = overall + res.tables

    res.add(unavailable('overall', 2, 'margins, cash flow, EPS, shares outstanding (dilution), guidance, '
                                      'analyst estimates',
                        'NOT IMPLEMENTED: not ingested from XBRL company facts (only revenue, debt and '
                        'equity are stored); analyst estimates have no free point-in-time source'))
    res.add(unavailable('overall', 7, 'content of filings beyond form and item codes (exhibit text), '
                                      'earnings-call transcripts, analyst rating changes',
                        'NOT IMPLEMENTED: exhibits and transcripts are not parsed; analyst actions have '
                        'no free point-in-time source'))
    return res
