#!/usr/bin/env python3
"""
Form 4 history for the research panel (phase P2.2) - pre-registered in
docs/research/STAGE2_PREREGISTRATION.md

- Filings: Form 4 entries of the SEC submissions feed, including its older 'files'
  (CIK##########-submissions-NNN.json), accepted on or after HISTORY_START.
- Documents: the raw XML of each filing, downloaded once (immutable; reused from the fetch
  log afterwards) through SECParser.prefetch in chunks of CHUNK (bounded memory, resumable).
- Transactions: non-derivative open-market purchases (P) and sales (S), parsed with
  insider_tracker.parse_form4; each carries its filing's acceptance time and one insider
  identity per filing (primary reporting owner; joint filers count once - amendment 1).
- Coverage: features at T need the whole window (T - 90 d, T] covered: T - 90 d must be on or
  after the coverage start (HISTORY_START, or the company's first listed filing when its full
  history is shorter) and no Form 4 in the window may have failed to download or parse.
  Otherwise every insider feature is None (never "no transaction").
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from ..insider_tracker import form4_xml_url, parse_form4
from ..sec_parser import IMMUTABLE, SECParser

HISTORY_START = '2016-06-01'
WINDOW_DAYS = 90
CHUNK = 400
OLDER_FILES_MAX_AGE = timedelta(days=30)


def _iso_day(published_at):
    return published_at[:10]


class InsiderHistory:
    def __init__(self, sec=None, db=None):
        self.sec = sec or SECParser(db=db)

    def filings(self, cik):
        """Form 4 filings since HISTORY_START: (filings, coverage_start) or (None, reason)."""
        feed = self.sec._get_json(f"{self.sec.SEC_API}/submissions/CIK{cik}.json")
        if not feed:
            return None, f'submissions feed unavailable: {self.sec.last_error}'
        listed = self.sec._recent_filings(feed)
        complete = True
        for older in (feed.get('filings') or {}).get('files') or []:
            if (older.get('filingTo') or '') < HISTORY_START:
                continue
            data = self.sec._get_json(f"{self.sec.SEC_API}/submissions/{older['name']}",
                                      max_age=OLDER_FILES_MAX_AGE)
            if not data:
                complete = False
                continue
            listed += self.sec._recent_filings({'filings': {'recent': data}})
        dates = [f['filing_date'] for f in listed if f['filing_date']]
        first_listed = min(dates) if dates else None
        coverage_start = max(HISTORY_START, first_listed) if first_listed else HISTORY_START
        if not complete:
            return None, 'an older submissions file could not be downloaded'
        form4 = [f for f in listed if f['form'] == '4' and f['published_at']
                 and _iso_day(f['published_at']) >= HISTORY_START]
        return form4, coverage_start

    def load(self, cik, progress=None):
        """
        {'transactions': [...], 'failed_at': [...], 'coverage_start': date, 'n_filings': n,
         'n_parsed': n} or {'error': reason}.
        """
        form4, coverage = self.filings(cik)
        if form4 is None:
            return {'error': coverage}
        urls = {}
        failed_at = []
        for f in form4:
            if f.get('primary_document') and f['accession_number']:
                urls[f['accession_number']] = form4_xml_url(cik, f['accession_number'],
                                                            f['primary_document'])
            else:
                failed_at.append(f['published_at'])
        transactions, parsed = [], 0
        items = [f for f in form4 if f['accession_number'] in urls]
        for start in range(0, len(items), CHUNK):
            chunk = items[start:start + CHUNK]
            downloads = self.sec.prefetch([urls[f['accession_number']] for f in chunk],
                                          as_json=False, max_age=IMMUTABLE)
            for f in chunk:
                url = urls[f['accession_number']]
                text = self.sec._get(url, as_json=False, max_age=IMMUTABLE, prefetched=downloads.get(url))
                if text is None:
                    failed_at.append(f['published_at'])
                    continue
                try:
                    doc = parse_form4(text)
                except ET.ParseError:
                    failed_at.append(f['published_at'])
                    continue
                parsed += 1
                # One Form 4 = one reporting group (joint filers such as a fund and its general
                # partners are one economic decision): the primary (first) reporting owner, by
                # CIK when present, identifies the insider.
                primary = doc['owners'][0] if doc['owners'] else {}
                insider = primary.get('cik') or primary.get('name') or f['accession_number']
                for t in doc['transactions']:
                    if t['code'] in ('P', 'S'):
                        transactions.append({'published_at': f['published_at'], 'code': t['code'],
                                             'value_usd': t['value_usd'], 'insider': insider,
                                             'planned': doc['rule_10b5_1'] is True})
            if progress:
                progress(min(start + CHUNK, len(items)), len(items))
        transactions.sort(key=lambda t: t['published_at'])
        return {'transactions': transactions, 'failed_at': sorted(failed_at),
                'coverage_start': coverage, 'n_filings': len(form4), 'n_parsed': parsed}


def insider_features_at(history, known_at, market_cap):
    """Pre-registered insider features at known_at (all None when the window is not covered)."""
    empty = {'insider_buyers_90d': None, 'insider_net_buy_to_mcap': None,
             'insider_disc_sellers_90d': None}
    if not history or history.get('error'):
        return empty
    end = datetime.fromisoformat(known_at)
    start = end - timedelta(days=WINDOW_DAYS)
    if start.date().isoformat() < history['coverage_start']:
        return empty
    lo, hi = start.isoformat(), end.isoformat()
    if any(lo < t <= hi for t in history['failed_at']):
        return empty
    window = [t for t in history['transactions'] if lo < t['published_at'] <= hi]
    buys = [t for t in window if t['code'] == 'P']
    disc = [t for t in window if t['code'] == 'S' and not t['planned']]
    net = sum(t['value_usd'] or 0 for t in buys) - sum(t['value_usd'] or 0 for t in disc)
    return {'insider_buyers_90d': float(len({t['insider'] for t in buys})),
            'insider_net_buy_to_mcap': net / market_cap if market_cap else None,
            'insider_disc_sellers_90d': float(len({t['insider'] for t in disc}))}


def utc(day):
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
