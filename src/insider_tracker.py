#!/usr/bin/env python3
"""
Insider Tracker - SEC Form 4

P0.1: the previous version always returned a NEUTRAL signal with zero buys/sells
without reading any filing; it was replaced by DATA UNAVAILABLE.

P0.2: the legacy insider_transactions table (never filled, with an invented "confidence"
column) is no longer created; it is backed up and dropped by the v2 migration.

P0.3: Form 4 transactions are parsed from the filed XML documents.
- Filings: Form 4 entries of the SEC submissions feed (amendments 4/A are not used).
  Each XML document is downloaded once (filed documents are immutable) and reused.
- Every non-derivative transaction is stored as an event observation
  (metric 'form4:transaction', as_of_date = transaction date, published_at = filing
  acceptance time), so the window can be evaluated point-in-time.
- Only open-market purchases (code P) and sales (code S) are counted. Grants (A), option
  exercises (M), tax withholding (F), gifts (G) etc. carry little information on the
  insider's view and are reported but not scored.
- Sales reported on filings that tick the Rule 10b5-1 box are "planned"; other sales are
  "discretionary". On forms without the checkbox the plan status is unknown (counted as
  discretionary, the conservative reading).

Insider score (heuristic 0-100, NOT a probability, not calibrated):
  open-market purchases by k distinct insiders  -> 60 + 10 * (min(k, 4) - 1)  (60..90)
  else discretionary sales by >= 3 insiders      -> 35
  else discretionary sales                       -> 45
  else (no purchase, sales only under 10b5-1 plans, or no P/S transaction) -> 50
50 here is a computed observation ("nothing informative was traded"), not a default for
missing data: when SEC cannot be reached the score is None.
"""

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from .common import DATA_UNAVAILABLE, to_utc_iso, unavailable, utc_now_iso
from .sec_parser import IMMUTABLE, SEC_SOURCE, SECParser

LOOKBACK_DAYS = 90
FORM4_METRIC = 'form4:transaction'
SCORED_CODES = {'P': 'open-market purchase', 'S': 'open-market sale'}


def _text(node, path):
    found = node.find(path)
    if found is None:
        return None
    value = found.find('value')
    text = (value if value is not None else found).text
    return text.strip() if text and text.strip() else None


def _float(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_form4(xml_text):
    """Owners, Rule 10b5-1 flag and non-derivative transactions of a Form 4 XML document."""
    root = ET.fromstring(xml_text.encode('utf-8') if isinstance(xml_text, str) else xml_text)
    owners = []
    for owner in root.findall('reportingOwner'):
        rel = owner.find('reportingOwnerRelationship')
        roles = []
        if rel is not None:
            for flag, label in (('isDirector', 'director'), ('isOfficer', 'officer'),
                                ('isTenPercentOwner', '10% owner'), ('isOther', 'other')):
                if (_text(rel, flag) or '').lower() in ('1', 'true'):
                    roles.append(label)
            title = _text(rel, 'officerTitle')
            if title:
                roles.append(title)
        owners.append({'name': _text(owner, 'reportingOwnerId/rptOwnerName'),
                       'cik': _text(owner, 'reportingOwnerId/rptOwnerCik'), 'roles': roles})
    flag = _text(root, 'aff10b5One')
    plan = None if flag is None else flag.lower() in ('1', 'true')
    transactions = []
    for txn in root.findall('nonDerivativeTable/nonDerivativeTransaction'):
        shares = _float(_text(txn, 'transactionAmounts/transactionShares'))
        price = _float(_text(txn, 'transactionAmounts/transactionPricePerShare'))
        transactions.append({
            'date': _text(txn, 'transactionDate'),
            'code': _text(txn, 'transactionCoding/transactionCode'),
            'acquired_disposed': _text(txn, 'transactionAmounts/transactionAcquiredDisposedCode'),
            'shares': shares,
            'price': price,
            'value_usd': round(shares * price, 2) if shares is not None and price else None,
            'security': _text(txn, 'securityTitle'),
        })
    return {'owners': owners, 'rule_10b5_1': plan, 'transactions': transactions}


def form4_xml_url(cik, accession, primary_document):
    """Raw XML URL of a Form 4 (the feed points to the XSL-rendered copy)."""
    document = primary_document.split('/')[-1]
    return (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/{document}")


def insider_score(summary):
    """Heuristic score from a window summary (see module docstring)."""
    if summary['distinct_buyers']:
        return 60 + 10 * (min(summary['distinct_buyers'], 4) - 1)
    if summary['discretionary_sellers'] >= 3:
        return 35
    if summary['discretionary_sellers']:
        return 45
    return 50


class InsiderTracker:
    """Track insider transactions from SEC Form 4"""

    def __init__(self, sec_parser=None):
        self.sec = sec_parser or SECParser()
        self.db = self.sec.db

    def ingest(self, ticker, known_at=None, days=LOOKBACK_DAYS, progress=False):
        """
        Download / reuse the Form 4 XML documents filed in the window and store their
        transactions. Returns (n_filings, n_parsed, failures) or None if SEC is unreachable.
        """
        filings = self.sec.get_filings(ticker)
        if not filings:
            return None
        cik = self.sec.get_cik(ticker)
        end = to_utc_iso(known_at) if known_at else utc_now_iso()
        start = to_utc_iso(datetime.fromisoformat(end) - timedelta(days=days))
        window = [f for f in filings['filings'] if f['form'] == '4' and f['published_at']
                  and start < f['published_at'] <= end]
        urls = {f['accession_number']: form4_xml_url(cik, f['accession_number'], f['primary_document'])
                for f in window if f.get('primary_document') and f['accession_number']}
        downloads = self.sec.prefetch(list(urls.values()), as_json=False, max_age=IMMUTABLE)
        parsed, failures = 0, []
        for n, filing in enumerate(window, 1):
            if progress and n % 100 == 0:
                print(f"    Form 4 documents: {n}/{len(window)}")
            if not filing.get('primary_document') or not filing['accession_number']:
                failures.append({'accession': filing['accession_number'],
                                 'published_at': filing['published_at'],
                                 'reason': 'primary document not listed in submissions feed'})
                continue
            url = urls[filing['accession_number']]
            xml_text = self.sec._get(url, as_json=False, max_age=IMMUTABLE,
                                     prefetched=downloads.get(url))
            if xml_text is None:
                failures.append({'accession': filing['accession_number'],
                                 'published_at': filing['published_at'],
                                 'reason': self.sec.last_error})
                continue
            try:
                doc = parse_form4(xml_text)
            except ET.ParseError as e:
                failures.append({'accession': filing['accession_number'],
                                 'published_at': filing['published_at'],
                                 'reason': f'XML parse error: {e}'})
                continue
            rows = []
            for i, txn in enumerate(doc['transactions']):
                if not txn['date']:
                    continue
                rows.append({
                    'entity': ticker, 'metric': FORM4_METRIC, 'as_of_date': txn['date'],
                    'value_text': json.dumps({
                        'accession': filing['accession_number'], 'index': i, **txn,
                        'owners': [o['name'] for o in doc['owners']],
                        'roles': sorted({r for o in doc['owners'] for r in o['roles']}),
                        'rule_10b5_1': doc['rule_10b5_1']}, sort_keys=True),
                    'published_at': filing['published_at'],
                    'published_at_basis': filing['published_at_basis']})
            self.db.upsert_observations(self.sec.last_fetch[url], rows)
            parsed += 1
        return len(window), parsed, failures

    def summarize(self, ticker, known_at=None, days=LOOKBACK_DAYS):
        """Window summary from stored transactions available at known_at (point-in-time)."""
        end = datetime.fromisoformat(to_utc_iso(known_at)) if known_at else datetime.now(timezone.utc)
        events = self.db.events(ticker, FORM4_METRIC, published_from=end - timedelta(days=days),
                                published_to=end, source=SEC_SOURCE)
        txns = [json.loads(e['value_text']) for e in events]
        buys = [t for t in txns if t.get('code') == 'P']
        sells = [t for t in txns if t.get('code') == 'S']
        discretionary = [t for t in sells if t.get('rule_10b5_1') is not True]

        def value(rows):
            return round(sum(t['value_usd'] for t in rows if t.get('value_usd')), 2)

        def people(rows):
            return len({name for t in rows for name in (t.get('owners') or [])})

        other = {}
        for t in txns:
            if t.get('code') not in SCORED_CODES:
                other[t.get('code') or '?'] = other.get(t.get('code') or '?', 0) + 1
        return {
            'window_days': days,
            'window_end': to_utc_iso(end),
            'transactions_total': len(txns),
            'insider_buys': len(buys),
            'insider_sells': len(sells),
            'buy_value_usd': value(buys),
            'sell_value_usd': value(sells),
            'planned_sell_value_usd': value([t for t in sells if t.get('rule_10b5_1') is True]),
            'discretionary_sell_value_usd': value(discretionary),
            'distinct_buyers': people(buys),
            'distinct_sellers': people(sells),
            'discretionary_sellers': people(discretionary),
            'other_transaction_codes': dict(sorted(other.items())),
        }

    def run(self, ticker, known_at=None):
        """Insider analysis for ticker over the last LOOKBACK_DAYS days."""
        print(f"\n[INSIDER TRACKER] {ticker}")
        print("=" * 60)
        self.sec.last_error = None
        ingested = self.ingest(ticker, known_at)
        if ingested is None:
            reason = f'SEC filings unavailable: {self.sec.last_error}'
            print(f"  {DATA_UNAVAILABLE} ({reason})")
            print("=" * 60)
            result = unavailable('SEC Form 4', reason)
            result.update({'ticker': ticker, 'insider_buys': None, 'insider_sells': None,
                           'insider_score': None, 'signal': None})
            return result
        n_filings, n_parsed, failures = ingested
        if n_filings and not n_parsed:
            reason = f'none of the {n_filings} Form 4 documents could be read'
            print(f"  {DATA_UNAVAILABLE} ({reason})")
            print("=" * 60)
            result = unavailable('SEC Form 4', reason, failures=failures[:5])
            result.update({'ticker': ticker, 'insider_buys': None, 'insider_sells': None,
                           'insider_score': None, 'signal': None})
            return result

        summary = self.summarize(ticker, known_at)
        score = insider_score(summary)
        signal = 'POSITIVE' if score >= 60 else 'NEGATIVE' if score <= 40 else 'NEUTRAL'
        status = 'PROVISIONAL' if failures else 'OK'
        filings = self.sec._filings_cache.get(ticker) or {}
        print(f"  Form 4 filings ({LOOKBACK_DAYS}d): {n_filings} (parsed {n_parsed})")
        print(f"  Open-market buys:  {summary['insider_buys']} "
              f"({summary['distinct_buyers']} insiders, {summary['buy_value_usd']:,.0f} USD)")
        print(f"  Open-market sells: {summary['insider_sells']} "
              f"({summary['distinct_sellers']} insiders, {summary['sell_value_usd']:,.0f} USD; "
              f"discretionary {summary['discretionary_sell_value_usd']:,.0f} USD)")
        print(f"  Insider score: {score} (heuristic) -> {signal}")
        print("=" * 60)
        return {
            'ticker': ticker,
            'status': status,
            'source': 'SEC Form 4',
            'form4_filings_window': n_filings,
            'form4_parsed': n_parsed,
            'failures': failures[:5],
            'warning': (f'{len(failures)} Form 4 document(s) could not be read; '
                        'score computed from the others') if failures else None,
            **summary,
            'insider_score': score,
            'signal': signal,
            'score_type': 'heuristic 0-100 score, not a probability; not calibrated',
            'method': 'open-market P/S transactions only; 10b5-1 planned sales not scored',
            'provenance': self.db.provenance(
                filings.get('fetch'), cadence='daily', as_of_date=summary['window_end'],
                published_at=None, published_at_basis='filing acceptance times (per transaction)'),
            'timestamp': utc_now_iso(),
        }


if __name__ == "__main__":
    from .common import tickers
    tracker = InsiderTracker()
    for t in tickers():
        tracker.run(t)
