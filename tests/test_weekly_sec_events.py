"""Weekly report section 'sec_events' (Q2, Q7) - offline tests on a fake context.

All filings, facts and transactions below are synthetic and exist only to check the logic.
"""

import copy
import json
import re
from datetime import datetime

import pandas as pd
import pytest

from src.database import freshness
from src.sec_parser import ACCEPTANCE_BASIS, acceptance_to_utc
from src.weekly.core import STRONG, UNAVAILABLE, UNCERTAIN, LookAheadError, TimeModel
from src.weekly.sections import sec_events
from src.weekly.sections.sec_events import (AFTER_LAST, FINANCING, INSIDER, MNA, OTHER_8K_CLASS,
                                            OTHER_CLASS, OWNERSHIP, PERIODIC_CLASS, RED_FLAGS,
                                            RESULTS, build, classify, map_session, session_of)

SESSIONS = [d.date().isoformat() for d in pd.bdate_range('2026-09-01', '2026-10-09')]
T_P, T_C = '2026-09-30T05:00:00+00:00', '2026-10-07T05:00:00+00:00'
FEED_FETCH = {'fetch_id': 11, 'retrieved_at': '2026-10-07T08:00:00+00:00'}
FACTS_FETCH = {'fetch_id': 21, 'retrieved_at': '2026-10-07T08:15:00+00:00'}
CIK = '0000000123'
CAUSAL = re.compile(r'\b(because|due to|drove|driven|caused|triggered|sparked|fueled|on the back of|'
                    r'thanks to|in response to|as a result|sent shares)\b', re.IGNORECASE)


def tm():
    return TimeModel(SESSIONS, '2026-10-07T12:00:00+00:00', '2026-10-07T12:00:00+00:00')


def filing(form, label, accession, items=(), report_date=None, doc='doc.xml'):
    """A submissions-feed row as Context.filings returns it (label = SEC 'Z' acceptance label)."""
    return {'form': form, 'filing_date': label[:10], 'report_date': report_date,
            'accession_number': accession, 'primary_document': doc,
            'published_at': acceptance_to_utc(label), 'published_at_basis': ACCEPTANCE_BASIS,
            'items': list(items), 'acceptance_utc': label.replace('Z', '+00:00')}


OLD = filing('10-Q', '2026-08-05T16:00:00Z', 'old-10q', report_date='2026-06-30')


def feed(rows, after=True, retrieved=None, old=True):
    fetch = dict(FEED_FETCH, retrieved_at=retrieved or FEED_FETCH['retrieved_at'])
    return {'status': 'OK', 'filings': list(rows) + ([OLD] if old else []), 'fetch': fetch, 'reason': None,
            'retrieved_after_cutoff': after}


def xml_url(accession, doc):
    return f"https://www.sec.gov/Archives/edgar/data/123/{accession.replace('-', '')}/{doc.split('/')[-1]}"


def form4_xml(rows=()):
    """Minimal Form 4 XML with the elements parse_form4 reads; rows = (date or None, code, shares, price)."""
    tx = ''.join(
        '<nonDerivativeTransaction><securityTitle><value>Common</value></securityTitle>'
        + (f'<transactionDate><value>{d}</value></transactionDate>' if d else '')
        + f'<transactionCoding><transactionCode>{c}</transactionCode></transactionCoding>'
        f'<transactionAmounts><transactionShares><value>{n}</value></transactionShares>'
        f'<transactionPricePerShare><value>{p}</value></transactionPricePerShare>'
        '<transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>'
        '</transactionAmounts></nonDerivativeTransaction>' for d, c, n, p in rows)
    return ('<?xml version="1.0"?><ownershipDocument><reportingOwner><reportingOwnerId>'
            '<rptOwnerName>Owner A</rptOwnerName></reportingOwnerId></reportingOwner>'
            f'<nonDerivativeTable>{tx}</nonDerivativeTable></ownershipDocument>')


def view(**over):
    base = {'status': 'OK', 'revenue': 1.0e9, 'revenue_tag': 'Revenues', 'revenue_period_end': '2026-06-30',
            'revenue_method': 'annual (12M) fact', 'revenue_prior_year': 8.0e8, 'revenue_growth_pct': 25.0,
            'balance_sheet_date': '2026-06-30', 'latest_equity_date': '2026-06-30', 'equity': 1.0e9,
            'equity_tag': 'StockholdersEquity', 'debt': 5.0e8, 'debt_tags': ['LongTermDebt'],
            'debt_definition': 'long_term_debt_total', 'debt_includes_finance_leases': False,
            'debt_to_equity': 0.5, 'revenue_published_at': '2026-08-05T20:00:00+00:00',
            'fetch': dict(FACTS_FETCH), 'reason': None}
    base.update(over)
    return base


class FakeDB:
    def __init__(self, txns=(), facts=None, xml=None):
        self.txns = list(txns)          # (entity, available_at, dict)
        self.facts = facts or {}        # (entity, metric) -> [(as_of, published_at, value)]
        self.xml = dict(xml or {})      # stored Form 4 XML: url -> text (None: payload unreadable)
        self.ids = []

    def events(self, entity, metric, published_from=None, published_to=None, source=None):
        assert metric == 'form4:transaction' and source == 'SEC EDGAR'
        out = [{'as_of_date': v['date'], 'value_text': json.dumps(v, sort_keys=True), 'available_at': a}
               for e, a, v in self.txns if e == entity and published_from < a <= published_to]
        return sorted(out, key=lambda r: r['available_at'])

    def series(self, entity, metric, known_at=None, source=None, start=None, end=None):
        chosen = {}
        for as_of, pub, value in sorted(self.facts.get((entity, metric), []), key=lambda r: r[1]):
            if (known_at is None or pub <= known_at) and (not start or as_of >= start) \
                    and (not end or as_of <= end):
                chosen[as_of] = {'value': value, 'published_at': pub}
        return sorted(chosen.items())

    def latest_fetch(self, source, endpoint, since=None):
        if endpoint not in self.xml:
            return None
        if endpoint not in self.ids:
            self.ids.append(endpoint)
        return {'fetch_id': 100 + self.ids.index(endpoint), 'retrieved_at': '2026-10-07T08:30:00+00:00'}

    def read_raw(self, fetch_id):
        text = self.xml[self.ids[fetch_id - 100]]
        if text is None:
            raise RuntimeError(f'raw payload of fetch {fetch_id} does not match its SHA-256')
        return text


class FakeSEC:
    def __init__(self, views):
        self.views, self.calls = views, []

    def fundamentals(self, ticker, known_at=None):
        self.calls.append((ticker, known_at))
        return copy.deepcopy(self.views[ticker](known_at))

    def get_cik(self, ticker):
        return CIK


class FakeCtx:
    def __init__(self, feeds, views, db=None):
        self.tm = tm()
        self.universe = list(feeds)
        self.weekly = {'thresholds_version': 'test-v1', 'thresholds': {'abs_excess_return_z': 2.0}}
        self._feeds = feeds
        self.sec = FakeSEC(views)
        self.db = db or FakeDB(facts=balance_facts('AAA'))

    def filings(self, ticker):
        return self._feeds[ticker]

    def freshness(self, as_of, cadence):
        return freshness(as_of, cadence, now=datetime.fromisoformat(self.tm.cutoff))

    def company(self, ticker):
        return ticker


def balance_facts(t, pub='2026-08-05T20:00:00+00:00', day='2026-06-30', extra=()):
    facts = {(t, 'xbrl:LongTermDebt'): [(day, pub, 5.0e8)], (t, 'xbrl:StockholdersEquity'): [(day, pub, 1.0e9)]}
    for key, row in extra:
        facts.setdefault(key, []).append(row)
    return facts


def same(_known_at):
    return view()


def txn(accession, code, shares, price, plan, owner='Owner A', date='2026-09-30'):
    value = round(shares * price, 2) if shares is not None and price else None
    return {'accession': accession, 'index': 0, 'date': date, 'code': code, 'shares': shares,
            'price': price, 'value_usd': value, 'acquired_disposed': 'D', 'security': 'Common',
            'owners': [owner], 'roles': ['officer'], 'rule_10b5_1': plan}


def find(result, scope, question, pattern):
    hits = [c for c in result['conclusions'] if c['scope'] == scope and c['question'] == question
            and re.search(pattern, c['statement'])]
    assert len(hits) == 1, [c['statement'] for c in result['conclusions'] if c['scope'] == scope]
    return hits[0]


def table(result, prefix):
    hits = [t for t in result['tables'] if t['title'].startswith(prefix)]
    assert len(hits) == 1, [t['title'] for t in result['tables']]
    return hits[0]


# ---------------------------------------------------------------- unit: map and sessions

def test_classification_uses_the_pre_declared_map():
    assert classify('8-K', ['2.02', '9.01']) == [RESULTS]
    assert classify('8-K', ['1.01', '2.03', '3.02', '8.01', '9.01']) == ['agreements', FINANCING, 'disclosure']
    assert classify('8-K/A', ['9.01']) == [OTHER_8K_CLASS]
    assert classify('8-K', ['1.05']) == ['cybersecurity'] and classify('8-K', ['4.02']) == [RED_FLAGS]
    assert classify('S-4/A', []) == [MNA] and classify('425', []) == [MNA] and classify('DEFM14A', []) == [MNA]
    assert classify('424B5', []) == [FINANCING] and classify('S-3ASR', []) == [FINANCING]
    assert classify('S-8', []) == [FINANCING]
    assert classify('SC 13G/A', []) == [OWNERSHIP] and classify('SCHEDULE 13D', []) == [OWNERSHIP]
    assert classify('4', []) == [INSIDER] and classify('144', []) == [INSIDER]
    assert classify('NT 10-Q', []) == [RED_FLAGS] and classify('10-Q', []) == [PERIODIC_CLASS]
    assert classify('DEF 14A', []) == [OTHER_CLASS]


def test_session_mapping_new_york_time_and_ambiguity():
    s = tm().sessions
    assert map_session('2026-10-01T12:00:00+00:00', s) == ('2026-10-01', 'before the open of 2026-10-01 (pre-open)')
    assert map_session('2026-10-01T13:30:00+00:00', s)[0] == '2026-10-01'            # 09:30 EDT: in session
    assert map_session('2026-10-01T20:00:00+00:00', s) == ('2026-10-02', 'after the close of 2026-10-01')
    assert map_session('2026-10-03T15:00:00+00:00', s) == ('2026-10-05', '2026-10-03 is not a session day')
    assert map_session('2026-10-06T21:30:00+00:00', s)[0] is None                   # after s_0's close
    # 14:00 EDT label: same session as UTC, next session under the New York reading -> ambiguous
    m = session_of(filing('8-K', '2026-10-05T18:00:00Z', 'x'), s)
    assert m['session'] == '2026-10-05' and m['conservative_session'] == '2026-10-06' and m['ambiguous']
    m = session_of(filing('8-K', '2026-10-01T20:05:12Z', 'y'), s)                  # 16:05 EDT
    assert m['session'] == m['conservative_session'] == '2026-10-02' and not m['ambiguous']
    m = session_of(dict(filing('8-K', '2026-10-01T20:05:12Z', 'z'), acceptance_utc=None), s)
    assert m['ambiguous']                                                          # no acceptance time


# ---------------------------------------------------------------- quiet week

def quiet_ctx(after=True):
    rows = [filing('4', '2026-10-01T04:00:06Z', 'f4-1', doc='xsl/f4-1.xml'),
            filing('144', '2026-10-01T20:23:38Z', 'n144-1'),
            filing('4', '2026-09-30T01:00:00Z', 'f4-boundary'),        # published exactly T_p: last week
            filing('4', '2026-10-07T04:00:06Z', 'f4-late')]           # UTC before T_c, NY after: next week
    txns = [('AAA', acceptance_to_utc('2026-10-01T04:00:06Z'), txn('f4-1', 'S', 100.0, 10.0, True)),
            ('AAA', acceptance_to_utc('2026-10-01T04:00:06Z'), txn('f4-1', 'S', 50.0, 20.0, False)),
            ('AAA', acceptance_to_utc('2026-10-01T04:00:06Z'), txn('f4-1', 'P', 10.0, 5.0, None, owner='Owner B')),
            ('AAA', acceptance_to_utc('2026-10-01T04:00:06Z'), txn('f4-1', 'S', 7.0, None, True)),
            ('AAA', acceptance_to_utc('2026-10-01T04:00:06Z'), txn('f4-1', 'M', 30.0, 1.0, True)),
            ('AAA', acceptance_to_utc('2026-10-07T04:00:06Z'), txn('f4-late', 'P', 1e6, 10.0, None))]
    db = FakeDB(txns=txns, facts=balance_facts('AAA'))
    return FakeCtx({'AAA': feed(rows, after=after)}, {'AAA': same}, db)


def test_quiet_week_negative_facts_are_strong_with_post_cutoff_feed():
    ctx = quiet_ctx()
    r = build(ctx).as_dict()
    assert r['name'] == 'sec_events' and r['questions'] == [2, 7]
    assert ctx.sec.calls == [('AAA', T_P), ('AAA', T_C)]                 # both views, point-in-time
    no_stmt = find(r, 'AAA', 2, r'no new periodic financial statements accepted in the window')
    assert no_stmt['level'] == STRONG and no_stmt['kind'] == 'official_fact'
    assert find(r, 'AAA', 7, r'no 8-K or 8-K/A')['level'] == STRONG
    rev = find(r, 'AAA', 2, r'^AAA: revenue as known at T_c')
    assert rev['level'] == STRONG and 'unchanged' in rev['statement'] and '1,000.0 M USD' in rev['statement']
    assert rev['evidence'][0]['published_at'] == '2026-08-05T20:00:00+00:00'
    bal = find(r, 'AAA', 2, r'^AAA: balance sheet as known at T_c')
    assert bal['level'] == STRONG and 'debt/equity 0.5' in bal['statement']
    # window: boundary (published == T_p) and late (NY reading after T_c) filings are excluded
    events = table(r, 'AAA: every SEC filing')
    assert [row[7] for row in events['rows']] == ['f4-1', 'n144-1']
    assert events['rows'][0][0] == '2026-10-01' and events['rows'][1][0] == '2026-10-02'
    # published exactly at T_p (previous window) but its session (2026-09-30) is in this week
    carried = table(r, 'AAA: filings of the previous window')
    assert [(row[0], row[7]) for row in carried['rows']] == [('2026-09-30', 'f4-boundary')]
    # fundamentals table: full pre-declared rows, values in USD m, deltas
    fund = table(r, 'AAA: SEC XBRL fundamentals')
    by_field = {row[0]: row for row in fund['rows']}
    assert by_field['revenue TTM (USD m)'][1:] == [1000.0, 1000.0, 0.0, 'no']
    assert by_field['debt / equity'][1:] == [0.5, 0.5, 0.0, 'no']
    assert {'revenue TTM period end', 'balance sheet date', 'stockholders equity (USD m)', 'debt (USD m)',
            'revenue growth TTM vs one year earlier (%)'} <= set(by_field)
    assert 'test-v1' in fund['note'] and any('test-v1' in n for n in r['notes'])
    assert table(r, 'AAA: revisions')['rows'] == []


F41_XML = form4_xml([('2026-09-30', 'S', 100, 10), ('2026-09-30', 'S', 50, 20), ('2026-09-30', 'P', 10, 5),
                     ('2026-09-30', 'S', 7, ''), ('2026-09-30', 'M', 30, 1)])


def test_form4_totals_from_stored_transactions():
    ctx = quiet_ctx()
    ctx.db.xml[xml_url('f4-1', 'xsl/f4-1.xml')] = F41_XML        # 5 dated rows, all 5 stored
    r = build(ctx).as_dict()
    rows = dict(table(r, 'AAA: Form 4 in the window')['rows'])
    assert rows['Form 4 filings accepted in the window'] == 1
    assert rows['stored non-derivative transactions'] == 5                # the post-cutoff one is excluded
    assert rows['open-market purchases (P): transactions'] == 1
    assert rows['open-market purchases (P): USD (known values)'] == 50.0
    assert rows['open-market sales (S): transactions'] == 3
    assert rows['open-market sales (S): shares'] == 157.0
    assert rows['open-market sales (S): USD (known values)'] == 2000.0
    assert rows['open-market sales (S): transactions with unknown value'] == 1   # never counted as 0 USD
    assert rows['open-market sales (S): USD on filings ticking the Rule 10b5-1 box'] == 1000.0
    assert rows['open-market sales (S): USD on filings not ticking it'] == 1000.0
    assert rows['other transaction codes (not open-market)'] == 'M: 1'
    assert rows['Form 144 notices accepted in the window'] == 1
    c = find(r, 'AAA', 7, r'Form 4 filing\(s\) accepted in the window')
    assert c['level'] == STRONG and '1 P/S transaction(s) with unknown value' in c['statement']
    doc = [e for e in c['evidence'] if e['fact'].startswith('Form 4 f4-1')]
    assert len(doc) == 1 and doc[0]['fetch_id'] == 100 and doc[0]['retrieved_at']  # XML provenance
    assert dict(table(r, 'AAA: Form 4 in the window')['rows'])[
        'Form 4 documents read (all dated transactions stored, or stored XML with none)'] == 1
    assert find(r, 'AAA', 7, r'Form 144 notice')['level'] == STRONG


def test_form4_document_not_read_is_partial_coverage():
    rows = [filing('4', '2026-10-01T04:00:06Z', 'f4-unread', doc='xsl/unread.xml')]
    ctx = FakeCtx({'AAA': feed(rows)}, {'AAA': same})
    r = build(ctx).as_dict()
    c = find(r, 'AAA', 7, r'Form 4 filing\(s\) accepted in the window')
    assert c['level'] == UNCERTAIN and 'PARTIAL_COVERAGE' in c['reason_codes']
    assert 'not read' in c['statement']
    ctx.db.xml[xml_url('f4-unread', 'xsl/unread.xml')] = form4_xml([])   # no non-derivative transaction
    c = find(build(ctx).as_dict(), 'AAA', 7, r'Form 4 filing\(s\) accepted in the window')
    assert c['level'] == STRONG                                            # read, no non-derivative rows
    assert any('stored XML lists 0 dated' in e['fact'] and e['fetch_id'] == 100 for e in c['evidence'])


def test_negative_facts_need_a_feed_retrieved_after_the_cutoff():
    r = build(quiet_ctx(after=False)).as_dict()
    for q, pattern in ((2, r'no new periodic financial statements'), (7, r'no 8-K or 8-K/A'),
                       (7, r'Form 144 notice'), (7, r'Form 4 filing\(s\) accepted')):
        c = find(r, 'AAA', q, pattern)                       # counts over the window are completeness claims
        assert c['level'] == UNCERTAIN and 'PARTIAL_COVERAGE' in c['reason_codes']
        assert 'submissions fetch made after the cutoff' in c['what_would_resolve_it']
    assert 'PARTIAL_COVERAGE' in find(r, 'AAA', 2, r'^AAA: revenue as known')['reason_codes']


def test_feed_without_a_filing_older_than_the_window_is_partial_coverage():
    ctx = FakeCtx({'AAA': feed([], old=False)}, {'AAA': same})       # recent block may not reach T_p
    r = build(ctx).as_dict()
    for q, pattern in ((2, r'no new periodic financial statements'), (7, r'no 8-K or 8-K/A'),
                       (7, r'no SEC filing of any form'), (7, r'no Form 4 filing')):
        c = find(r, 'AAA', q, pattern)
        assert c['level'] == UNCERTAIN and c['reason_codes'] == ['PARTIAL_COVERAGE']
    assert 'no filing older than the window start' in table(r, 'AAA: every SEC filing')['note']


def test_form4a_only_window_is_not_a_strong_negative():
    ctx = FakeCtx({'AAA': feed([filing('4/A', '2026-10-01T20:00:00Z', 'f4a-1')])}, {'AAA': same})
    r = build(ctx).as_dict()
    assert not any(re.search(r'no Form 4 filing', c['statement']) for c in r['conclusions'])
    c = find(r, 'AAA', 7, r'no original Form 4 accepted in the window; 1 Form 4/A')
    assert c['level'] == UNCERTAIN and c['reason_codes'] == ['PARTIAL_COVERAGE']
    assert 'f4a-1' in c['statement'] and any('f4a-1' in e['fact'] for e in c['evidence'])
    assert 'Form 4 / 4/A' in c['what_would_resolve_it']
    # with an original Form 4 as well, the 4/A is cited and keeps the claim partial
    rows = [filing('4/A', '2026-10-01T20:00:00Z', 'f4a-1'), filing('4', '2026-10-02T20:00:00Z', 'f4-2')]
    ctx = FakeCtx({'AAA': feed(rows)}, {'AAA': same},
                  FakeDB(facts=balance_facts('AAA'), xml={xml_url('f4-2', 'doc.xml'): form4_xml([])}))
    c = find(build(ctx).as_dict(), 'AAA', 7, r'Form 4 filing\(s\) accepted in the window')
    assert c['level'] == UNCERTAIN and 'PARTIAL_COVERAGE' in c['reason_codes']
    assert '1 Form 4/A not parsed (f4a-1)' in c['statement'] and any('f4a-1' in e['fact'] for e in c['evidence'])


def test_stored_xml_without_stored_transactions_is_not_read():
    rows = [filing('4', '2026-10-01T04:00:06Z', 'f4-x', doc='xsl/x.xml')]
    db = FakeDB(facts=balance_facts('AAA'), xml={xml_url('f4-x', 'x.xml'): form4_xml([('2026-09-29', 'P', 1000, 30)])})
    r = build(FakeCtx({'AAA': feed(rows)}, {'AAA': same}, db)).as_dict()
    c = find(r, 'AAA', 7, r'Form 4 filing\(s\) accepted in the window')
    assert c['level'] == UNCERTAIN and c['reason_codes'] == ['PARTIAL_COVERAGE']
    assert 'f4-x: stored XML lists 1 dated non-derivative transaction(s), 0 stored (transactions not ingested)' \
        in c['statement']
    t = dict(table(r, 'AAA: Form 4 in the window')['rows'])
    assert t['Form 4 documents read (all dated transactions stored, or stored XML with none)'] == 0
    assert t['Form 4 documents not read (XML not stored or unreadable, or transactions not ingested)'] == 1
    # a stored row only for part of the document: still not read
    db.txns.append(('AAA', acceptance_to_utc('2026-10-01T04:00:06Z'), txn('f4-x', 'P', 1000.0, 30.0, None)))
    db.xml[xml_url('f4-x', 'x.xml')] = form4_xml([('2026-09-29', 'P', 1000, 30), ('2026-09-29', 'S', 5, 30)])
    c = find(build(FakeCtx({'AAA': feed(rows)}, {'AAA': same}, db)).as_dict(), 'AAA', 7, r'Form 4 filing')
    assert c['level'] == UNCERTAIN and '2 dated non-derivative transaction(s), 1 stored' in c['statement']
    # undated rows are not ingested: a document whose only row is undated is read
    db.txns.clear()
    db.xml[xml_url('f4-x', 'x.xml')] = form4_xml([(None, 'G', 10, 0)])
    assert find(build(FakeCtx({'AAA': feed(rows)}, {'AAA': same}, db)).as_dict(), 'AAA', 7,
                r'Form 4 filing')['level'] == STRONG
    # an unreadable stored payload is not read
    db.xml[xml_url('f4-x', 'x.xml')] = None
    c = find(build(FakeCtx({'AAA': feed(rows)}, {'AAA': same}, db)).as_dict(), 'AAA', 7, r'Form 4 filing')
    assert c['level'] == UNCERTAIN and 'not readable: RuntimeError' in c['statement']


def test_carried_over_filing_is_linked_to_its_session_in_this_week():
    # 16:05 EDT on s_-5 (2026-09-29): admissible at T_p (previous window), session s_-4 = 2026-09-30
    late = filing('8-K', '2026-09-29T20:05:00Z', '8k-carried', items=['2.02', '9.01'])
    assert late['published_at'] <= T_P
    ctx = FakeCtx({'AAA': feed([late])}, {'AAA': same})
    r = build(ctx).as_dict()
    assert table(r, 'AAA: every SEC filing')['rows'] == []
    carried = table(r, 'AAA: filings of the previous window')
    assert [(row[0], row[7], row[6]) for row in carried['rows']] == [('2026-09-30', '8k-carried', RESULTS)]
    c = find(r, 'AAA', 7, r'accession 8k-carried: available in the previous window')
    assert c['level'] == STRONG and 'mapped to session 2026-09-30 of this week' in c['statement']
    no8k = find(r, 'AAA', 7, r'no 8-K or 8-K/A')
    assert no8k['level'] == STRONG and '8k-carried' in no8k['statement']
    counts = {row[0]: row[1] for row in table(r, 'SEC filings in the window by class')['rows']}
    assert counts[RESULTS] == 0 and counts['filings (distinct accessions)'] == 0   # last week's filing
    # the previous week's report saw it after its last session and points to this report
    prev = FakeCtx({'AAA': feed([late])}, {'AAA': same})
    prev.tm = TimeModel(SESSIONS, '2026-09-30T12:00:00+00:00', '2026-09-30T12:00:00+00:00')
    assert AFTER_LAST in find(build(prev).as_dict(), 'AAA', 7, r'accession 8k-carried')['statement']
    assert "next week's report" in AFTER_LAST


def test_unclassified_filings_qualify_the_class_absence_statement():
    rows = [filing('SC TO-T', '2026-10-01T12:00:00Z', 'tender'), filing('25-NSE', '2026-10-01T13:00:00Z', 'delist'),
            filing('POSASR', '2026-10-01T14:00:00Z', 'shelf'), filing('3', '2026-10-01T15:00:00Z', 'form3'),
            filing('8-K12B', '2026-10-01T16:00:00Z', 'succ', items=['2.02'])]
    r = build(FakeCtx({'AAA': feed(rows)}, {'AAA': same})).as_dict()
    assert not any('no 8-K' in c['statement'] for c in r['conclusions'])          # 8-K12B is an 8-K
    zero = find(r, 'AAA', 7, r'no filing of the pre-declared classes')
    for cls in (MNA, FINANCING, 'listing', INSIDER, RESULTS):
        assert cls not in zero['statement'].split(' (map')[0]
    assert zero['level'] == STRONG and 'v2' in zero['statement']
    assert find(r, 'AAA', 7, r'^AAA: 3 accepted')['statement'].count(INSIDER) == 1
    rows = [filing('DEF 14A', '2026-10-01T12:00:00Z', 'proxy'),
            filing('8-K', '2026-10-01T13:00:00Z', 'blackout', items=['5.04', '9.01']),
            filing('8-K', '2026-10-01T20:30:00Z', 'ctrl', items=['2.02', '5.01', '9.01'])]
    r = build(FakeCtx({'AAA': feed(rows)}, {'AAA': same})).as_dict()
    zero = find(r, 'AAA', 7, r'no filing of the pre-declared classes')
    assert zero['level'] == UNCERTAIN and zero['reason_codes'] == ['PARTIAL_COVERAGE']
    assert '3 filing(s) of the window not fully classified' in zero['statement']
    assert 'DEF 14A proxy (form not in the map)' in zero['statement']
    assert '8-K blackout (items 5.04, 9.01: no mapped item)' in zero['statement']
    assert '8-K ctrl (items 5.01 not in the map)' in zero['statement']
    assert '(items 5.01 not in the map)' in find(r, 'AAA', 7, r'accession ctrl')['statement']


# ---------------------------------------------------------------- busy week

def busy_ctx():
    rows = [filing('8-K', '2026-10-01T20:05:12Z', '8k-results', items=['2.02', '9.01']),
            filing('10-Q', '2026-10-02T14:30:00Z', '10q-new', report_date='2026-09-30'),
            filing('SC 13G/A', '2026-10-03T15:00:00Z', '13g'),
            filing('8-K', '2026-10-05T18:00:00Z', '8k-gov', items=['5.02']),
            filing('8-K', '2026-10-06T21:30:00Z', '8k-late', items=['8.01'])]
    pub_10q = acceptance_to_utc('2026-10-02T14:30:00Z')

    def views(known_at):
        if known_at >= pub_10q:
            return view(revenue=1.2e9, revenue_period_end='2026-09-30', revenue_growth_pct=30.0,
                        revenue_prior_year=9.2e8, balance_sheet_date='2026-09-30', latest_equity_date='2026-09-30',
                        equity=1.1e9, debt=4.4e8, debt_to_equity=0.4, revenue_published_at=pub_10q)
        return view()
    facts = balance_facts('AAA', extra=[(('AAA', 'xbrl:LongTermDebt'), ('2026-09-30', pub_10q, 4.4e8)),
                                        (('AAA', 'xbrl:StockholdersEquity'), ('2026-09-30', pub_10q, 1.1e9))])
    return FakeCtx({'AAA': feed(rows)}, {'AAA': views}, FakeDB(facts=facts))


def test_new_periodic_filing_changes_fundamentals_and_events_are_mapped():
    r = build(busy_ctx()).as_dict()
    assert find(r, 'AAA', 2, r'10-Q for period 2026-09-30 accepted')['level'] == STRONG
    rev = find(r, 'AAA', 2, r'^AAA: revenue: ')
    assert rev['level'] == STRONG and 'acceptance time of 10-Q 10q-new' in rev['statement']
    assert '1,000.0 M USD' in rev['statement'] and '1,200.0 M USD' in rev['statement']
    assert len(rev['evidence']) == 2
    bal = find(r, 'AAA', 2, r'^AAA: balance sheet: ')
    assert bal['level'] == STRONG and 'debt/equity 0.4' in bal['statement']
    fund = {row[0]: row for row in table(r, 'AAA: SEC XBRL fundamentals')['rows']}
    assert fund['revenue TTM (USD m)'][1:] == [1000.0, 1200.0, 200.0, 'yes']
    assert fund['revenue TTM period end'][3] == '+92 d'
    assert fund['debt / equity'][3] == pytest.approx(-0.1)
    assert table(r, 'AAA: revisions')['rows'] == []
    assert not any('no new periodic' in c['statement'] for c in r['conclusions'])
    # results 8-K: filing facts strong, figures not parsed
    res8k = find(r, 'AAA', 7, r'8-K accepted .* accession 8k-results')
    assert res8k['level'] == STRONG and 'class results' in res8k['statement']
    assert 'mapped to session 2026-10-02 (after the close of 2026-10-01)' in res8k['statement']
    assert any(u['question'] == 2 and '8k-results' in u['item'] and 'NOT IMPLEMENTED' in u['reason']
               for u in r['unavailable'])
    # 14:00 EDT 8-K: session changes under the New York reading -> separate uncertain record
    gov = find(r, 'AAA', 7, r'^AAA: 8-K accepted .* accession 8k-gov')
    assert gov['level'] == STRONG and 'ambiguous' in gov['statement']
    amb = find(r, 'AAA', 7, r'session of 8-K accession 8k-gov is ambiguous')
    assert amb['level'] == UNCERTAIN and amb['reason_codes'] == ['TIMESTAMP_AMBIGUOUS']
    assert AFTER_LAST in find(r, 'AAA', 7, r'accession 8k-late')['statement']
    assert '2026-10-05' in find(r, 'AAA', 7, r'SC 13G/A')['statement']             # weekend -> Monday
    events = table(r, 'AAA: every SEC filing')
    assert [row[9] for row in events['rows']] == [None, None, None, 'TIMESTAMP_AMBIGUOUS', None]
    assert not any('no 8-K' in c['statement'] for c in r['conclusions'])
    zero = find(r, 'AAA', 7, r'no filing of the pre-declared classes')
    assert 'results' not in zero['statement'] and 'governance' not in zero['statement']
    assert 'cybersecurity' in zero['statement'] and zero['level'] == STRONG
    overall = table(r, 'SEC filings in the window by class')
    counts = {row[0]: row[1] for row in overall['rows']}
    assert counts[RESULTS] == 1 and counts['governance'] == 1 and counts['disclosure'] == 1
    assert counts[OWNERSHIP] == 1 and counts[PERIODIC_CLASS] == 1 and counts['filings (distinct accessions)'] == 5


def test_change_without_periodic_filing_is_a_revision_row():
    def views(known_at):
        return view(revenue=1.05e9) if known_at == T_C else view()
    r = build(FakeCtx({'AAA': feed([])}, {'AAA': views})).as_dict()
    c = find(r, 'AAA', 2, r'revenue view changed with no periodic financial statement')
    assert c['level'] == UNCERTAIN and 'CONFLICTING_SOURCES' in c['reason_codes']
    rows = table(r, 'AAA: revisions')['rows']
    assert rows == [['revenue TTM (USD m)', 1000.0, 1050.0, '2026-08-05T20:00:00+00:00',
                     '2026-08-05T20:00:00+00:00', 'no periodic statement accepted in the window']]
    assert find(r, 'AAA', 2, r'^AAA: balance sheet as known at T_c')['level'] == STRONG


def test_definition_change_is_a_comparability_break():
    pub = acceptance_to_utc('2026-10-02T14:30:00Z')

    def views(known_at):
        if known_at == T_C:
            return view(debt=6e8, debt_definition='combined_total', debt_tags=['DebtLongtermAndShorttermCombinedAmount'],
                        debt_to_equity=0.6, balance_sheet_date='2026-09-30', latest_equity_date='2026-09-30')
        return view()
    facts = balance_facts('AAA', extra=[(('AAA', 'xbrl:DebtLongtermAndShorttermCombinedAmount'), ('2026-09-30', pub, 6e8)),
                                        (('AAA', 'xbrl:StockholdersEquity'), ('2026-09-30', pub, 1e9))])
    ctx = FakeCtx({'AAA': feed([filing('10-Q', '2026-10-02T14:30:00Z', 'q', report_date='2026-09-30')])},
                  {'AAA': views}, FakeDB(facts=facts))
    c = find(build(ctx).as_dict(), 'AAA', 2, r'^AAA: balance sheet: ')
    assert c['level'] == UNCERTAIN and c['reason_codes'] == ['COMPARABILITY_BREAK']


def test_late_filing_notice_is_reported_but_is_not_a_statement():
    rows = [filing('NT 10-Q', '2026-10-02T14:30:00Z', 'nt', report_date='2026-06-30')]
    r = build(FakeCtx({'AAA': feed(rows)}, {'AAA': same})).as_dict()
    assert find(r, 'AAA', 2, r'NT 10-Q \(notification of late filing\)')['level'] == STRONG
    assert find(r, 'AAA', 2, r'no new periodic financial statements')['level'] == STRONG
    assert RED_FLAGS in find(r, 'AAA', 7, r'NT 10-Q accepted')['statement']
    assert [row[0] for row in table(r, 'AAA: new periodic filings')['rows']] == ['NT 10-Q']


def test_new_10q_without_its_facts_is_partial_coverage():
    ctx = FakeCtx({'AAA': feed([filing('10-Q', '2026-10-02T14:30:00Z', 'q', report_date='2026-09-30')])},
                  {'AAA': same})
    c = find(build(ctx).as_dict(), 'AAA', 2, r'^AAA: revenue as known at T_c')
    assert c['level'] == UNCERTAIN and 'PARTIAL_COVERAGE' in c['reason_codes']
    assert 'no revenue input carries its acceptance time' in c['statement']


def test_change_claim_baseline_freshness_is_evaluated_at_tp():
    # T_p inputs published 2026-06-02: 120 days before T_p (fresh then), 127 days before T_c
    old_pub, new_pub = '2026-06-02T20:00:00+00:00', acceptance_to_utc('2026-10-02T14:30:00Z')
    assert freshness(old_pub[:10], 'quarterly_filing', now=datetime.fromisoformat(T_C))['status'] == 'STALE'

    def views(known_at):
        if known_at == T_C:
            return view(revenue=1.3e9, revenue_period_end='2026-09-30', revenue_published_at=new_pub)
        return view(revenue_published_at=old_pub)
    k = filing('10-K', '2026-10-02T14:30:00Z', 'k', report_date='2026-09-30')
    c = find(build(FakeCtx({'AAA': feed([k])}, {'AAA': views})).as_dict(), 'AAA', 2, r'^AAA: revenue: ')
    assert c['level'] == STRONG and [e['fresh_at_cutoff'] for e in c['evidence']] == [True, True]
    assert 'freshness evaluated at T_p' in c['evidence'][0]['published_at_basis']

    def stale_then(known_at):          # baseline already older than 120 days at T_p
        return views(known_at) if known_at == T_C else view(revenue_published_at='2026-05-01T20:00:00+00:00')
    c = find(build(FakeCtx({'AAA': feed([k])}, {'AAA': stale_then})).as_dict(), 'AAA', 2, r'^AAA: revenue: ')
    assert c['level'] == UNCERTAIN and c['reason_codes'] == ['STALE_AT_CUTOFF']


# ---------------------------------------------------------------- missing data

def test_missing_sources_are_data_unavailable_with_reasons():
    down = {'status': 'DATA UNAVAILABLE', 'filings': [], 'fetch': None, 'reason': 'HTTP 403 from proxy'}

    def no_facts(_known_at):
        return {'status': 'DATA UNAVAILABLE', 'revenue': None, 'debt_to_equity': None, 'fetch': None,
                'reason': 'SEC XBRL company facts unavailable: HTTP 403'}
    r = build(FakeCtx({'AAA': down}, {'AAA': no_facts})).as_dict()
    assert not [c for c in r['conclusions'] if c['scope'] == 'AAA']
    items = {(u['question'], u['item']): u['reason'] for u in r['unavailable'] if u['scope'] == 'AAA'}
    assert 'HTTP 403 from proxy' in items[(2, 'periodic filings accepted in the window')]
    assert 'HTTP 403 from proxy' in items[(7, 'SEC filings accepted in the window (events, Form 4, Form 144)')]
    assert 'HTTP 403' in items[(2, 'fundamentals as known at T_c')]
    assert all(u['level'] == UNAVAILABLE for u in r['unavailable'])
    overall = table(r, 'SEC filings in the window by class')
    assert all(row[1] is None and row[2] is None for row in overall['rows'])   # never 0 for unknown
    fund = table(r, 'Fundamental changes per company')
    assert fund['rows'][0][:6] == ['AAA', None, None, None, None, None]        # revision rows: unknown


def test_revision_rows_are_unknown_without_both_sources():
    col = 5                                                                    # 'revision rows'

    def changed(known_at):
        return view(revenue=1.05e9) if known_at == T_C else view()

    def no_facts(_known_at):
        return {'status': 'DATA UNAVAILABLE', 'fetch': None, 'reason': 'SEC XBRL company facts unavailable'}
    down = {'status': 'DATA UNAVAILABLE', 'filings': [], 'fetch': None, 'reason': 'HTTP 403 from proxy'}
    cases = [(down, changed, None), (feed([]), no_facts, None), (feed([]), changed, 1), (feed([]), same, 0)]
    for f, views, expected in cases:
        r = build(FakeCtx({'AAA': copy.deepcopy(f)}, {'AAA': views})).as_dict()
        row = table(r, 'Fundamental changes per company')['rows'][0]
        assert row[col] == expected and (expected is None or isinstance(row[col], int)), (f['status'], row)
    r = build(FakeCtx({'AAA': copy.deepcopy(down)}, {'AAA': changed})).as_dict()
    assert table(r, 'Fundamental changes per company')['rows'][0][3] == 'yes'
    assert table(r, 'AAA: revisions')['note'] == 'not determinable: submissions feed unavailable'


def test_unreported_ratio_is_unavailable_never_zero():
    def views(_known_at):
        return view(debt_to_equity=None, equity=-2e8,
                    reason='stockholders equity <= 0: debt-to-equity not meaningful')
    r = build(FakeCtx({'AAA': feed([])}, {'AAA': views})).as_dict()
    u = [u for u in r['unavailable'] if u['scope'] == 'AAA' and u['question'] == 2]
    assert len(u) == 1 and u[0]['item'] == 'debt-to-equity as known at T_p and T_c'
    assert 'equity <= 0' in u[0]['reason']
    fund = {row[0]: row for row in table(r, 'AAA: SEC XBRL fundamentals')['rows']}
    assert fund['debt / equity'][1:4] == [None, None, None]
    assert 'debt/equity not available' in find(r, 'AAA', 2, r'^AAA: balance sheet')['statement']


def test_feed_exception_does_not_stop_other_companies():
    class Ctx(FakeCtx):
        def filings(self, ticker):
            if ticker == 'BBB':
                raise RuntimeError('boom')
            return super().filings(ticker)
    ctx = Ctx({'AAA': feed([]), 'BBB': None}, {'AAA': same, 'BBB': same},
              FakeDB(facts={**balance_facts('AAA'), **balance_facts('BBB')}))
    r = build(ctx).as_dict()
    assert any(u['scope'] == 'BBB' and 'RuntimeError: boom' in u['reason'] for u in r['unavailable'])
    rows = {row[0]: row for row in table(r, 'Fundamental changes per company')['rows']}
    assert rows['BBB'][5] is None and rows['AAA'][5] == 0                       # unknown is not 0
    assert find(r, 'AAA', 7, r'no 8-K or 8-K/A')['level'] == STRONG


# ---------------------------------------------------------------- look-ahead

def test_facts_published_after_the_view_instant_raise():
    def late(known_at):
        return view(revenue_published_at='2026-10-07T06:00:00+00:00') if known_at == T_C else view()
    with pytest.raises(LookAheadError):
        build(FakeCtx({'AAA': feed([])}, {'AAA': late}))

    def late_tp(known_at):            # published inside the window but offered for the T_p view
        return view(revenue_published_at='2026-10-02T18:30:00+00:00')
    with pytest.raises(LookAheadError):
        build(FakeCtx({'AAA': feed([])}, {'AAA': late_tp}))


def test_data_published_after_the_cutoff_leaves_the_section_unchanged():
    base = build(quiet_ctx()).as_dict()
    ctx = quiet_ctx()
    ctx._feeds['AAA']['filings'] += [filing('8-K', '2026-10-07T03:00:00Z', 'post-1', items=['1.05']),
                                     filing('10-K', '2026-10-08T12:00:00Z', 'post-2')]
    ctx.db.txns.append(('AAA', '2026-10-07T07:00:00+00:00', txn('post-1', 'P', 5.0, 5.0, None)))
    assert json.dumps(build(ctx).as_dict(), sort_keys=True) == json.dumps(base, sort_keys=True)


# ---------------------------------------------------------------- policy lint

def test_no_system_output_no_causal_wording_and_admissible_evidence():
    for ctx in (quiet_ctx(), busy_ctx(), quiet_ctx(after=False)):
        r = build(ctx).as_dict()
        assert r['conclusions']
        for c in r['conclusions']:
            assert c['kind'] == 'official_fact' and c['level'] in (STRONG, UNCERTAIN)
            assert not CAUSAL.search(c['statement']), c['statement']
            for e in c['evidence']:
                assert e['rank'] == 1 and e['source'] == 'SEC EDGAR'
                assert e['published_at'] and e['published_at'] <= ctx.tm.cutoff
        text = json.dumps(r['notes']) + json.dumps([t['note'] for t in r['tables']])
        assert not CAUSAL.search(text)
    assert sec_events.NAME == 'sec_events' and sec_events.QUESTIONS == [2, 7]
