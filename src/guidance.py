#!/usr/bin/env python3
"""
Company-issued guidance, quoted from the earnings release filed with the SEC (master mission 3.1, gap round G1)

Source (rank 1, official filing): the latest Form 8-K with item 2.02 "Results of Operations and Financial
Condition" accepted at or before the cutoff, and its exhibit 99.x (the press release), located through the filing
index page (`<accession>-index.htm`, document type EX-99.*).

Extraction rule (deterministic, version GUIDANCE_RULES_VERSION):
  1. the exhibit HTML is turned into text lines (block elements end a line, table cells are joined with ' | ');
  2. the outlook section starts at the first HEADING line: at most 80 characters, containing 'outlook' or
     'guidance', not a bullet and not ending with a period (e.g. 'Financial Outlook', 'Third Quarter 2026 Guidance');
  3. it ends before the first STOP line (conference call, webcast, forward-looking statements, non-GAAP
     definitions, 'About ...', contacts) or after MAX_LINES lines.
The lines are quoted verbatim (truncated at MAX_LINE_CHARS). Nothing is parsed into numbers: guidance is a
forward-looking statement by the company, often on a non-GAAP basis, and the report presents it as "the company
stated", never as a verified figure. No outlook section -> 'NOT REPORTED' (many companies do not guide); a
download failure -> DATA UNAVAILABLE with the error.
"""

import html as html_lib
import re
from datetime import timedelta

GUIDANCE_RULES_VERSION = 'guidance-v1-2026-10-12'
EARNINGS_ITEM = '2.02'
MAX_LINES = 25
MAX_LINE_CHARS = 400
HEADING = re.compile(r'\b(outlook|guidance)\b', re.I)
STOP = re.compile(r'^(conference call|webcast|earnings call|forward[- ]looking|use of non-gaap|non-gaap financial '
                  r'(measures|information)|about [A-Z]|safe harbor|investor (relations|contact)|media contact|'
                  r'contacts?$|key (business )?metrics|definitions)', re.I)
INDEX_CACHE = timedelta(days=3650)          # a filing never changes once accepted


def text_lines(html):
    """Visible text of an HTML document as non-empty lines (block elements end lines, cells joined by ' | ')."""
    h = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', html or '')
    h = re.sub(r'(?i)</(p|div|tr|li|h\d|table)\s*>|<br\s*/?>', '\n', h)
    h = re.sub(r'(?i)</t[dh]\s*>', ' | ', h)
    text = html_lib.unescape(re.sub(r'<[^>]+>', ' ', h)).replace('\xa0', ' ')
    out = []
    for line in text.split('\n'):
        line = re.sub(r'\s+', ' ', line).strip(' |')
        line = re.sub(r'(\s*\|\s*)+', ' | ', line)
        if line:
            out.append(line)
    return out


def is_heading(line):
    return (len(line) <= 80 and bool(HEADING.search(line)) and not line.startswith(('•', '-', '*'))
            and not line.rstrip().endswith('.'))


def find_outlook(lines):
    """(heading, [lines]) of the first outlook section, or (None, [])."""
    for i, line in enumerate(lines):
        if is_heading(line):
            body = []
            for nxt in lines[i + 1:]:
                if STOP.search(nxt) or len(body) >= MAX_LINES:
                    break
                body.append(nxt[:MAX_LINE_CHARS] + ('...' if len(nxt) > MAX_LINE_CHARS else ''))
            if body:
                return line, body
    return None, []


def exhibit_from_index(index_html):
    """Archive path of the first EX-99.* document listed on a filing index page, or None."""
    for row in re.findall(r'(?is)<tr[^>]*>(.*?)</tr>', index_html or ''):
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'(?is)<td[^>]*>(.*?)</td>', row)]
        href = re.search(r'href="([^"]+)"', row)
        if len(cells) >= 4 and cells[3].upper().startswith('EX-99') and href:
            return href.group(1).replace('/ix?doc=', '')
    return None


def latest_release(filings, known_at):
    """The latest 8-K with item 2.02 published at or before known_at (filings: weekly context rows)."""
    rows = [f for f in filings if f.get('form') == '8-K' and EARNINGS_ITEM in (f.get('items') or [])
            and f.get('published_at') and f['published_at'] <= known_at]
    return max(rows, key=lambda f: f['published_at']) if rows else None


def guidance(sec, cik, filings, known_at):
    """
    {'status': OK | NOT REPORTED | DATA UNAVAILABLE, 'heading', 'lines', 'filing', 'url', 'reason',
     'rules': GUIDANCE_RULES_VERSION} for the latest earnings release known at `known_at`.
    """
    base = {'status': 'DATA UNAVAILABLE', 'heading': None, 'lines': [], 'filing': None, 'url': None,
            'reason': None, 'rules': GUIDANCE_RULES_VERSION}
    filing = latest_release(filings, known_at)
    if filing is None:
        return {**base, 'status': 'NOT REPORTED',
                'reason': 'no 8-K with item 2.02 (earnings release) in the filings known at the cutoff'}
    base['filing'] = {k: filing.get(k) for k in ('accession_number', 'filing_date', 'published_at')}
    acc = filing['accession_number']
    index_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{acc}-index.htm"
    index_html = sec._get(index_url, as_json=False, max_age=INDEX_CACHE)
    if not index_html:
        return {**base, 'reason': f'filing index unavailable ({sec.last_error or "no response"})'}
    path = exhibit_from_index(index_html)
    if path is None:
        return {**base, 'status': 'NOT REPORTED', 'url': index_url,
                'reason': f'no EX-99 exhibit listed in the 8-K {acc}'}
    url = 'https://www.sec.gov' + path
    doc = sec._get(url, as_json=False, max_age=INDEX_CACHE)
    if not doc:
        return {**base, 'url': url, 'reason': f'exhibit unavailable ({sec.last_error or "no response"})'}
    heading, lines = find_outlook(text_lines(doc))
    if heading is None:
        return {**base, 'status': 'NOT REPORTED', 'url': url,
                'reason': f'no outlook / guidance section in the earnings release of the 8-K {acc} (rules '
                          f'{GUIDANCE_RULES_VERSION})'}
    return {**base, 'status': 'OK', 'heading': heading, 'lines': lines, 'url': url}
