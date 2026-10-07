#!/usr/bin/env python3
"""
SEC XBRL company facts -> point-in-time fundamentals (phase P0.3)

Source: https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json (SEC EDGAR, rank 1).
Only facts from 10-K / 10-Q filings (and their amendments) in USD are used.

Storage (observations, source 'SEC EDGAR'):
- instant facts (balance sheet):  metric 'xbrl:<Tag>',        as_of_date = period end
- duration facts (income stmt):   metric 'xbrl:<Tag>:<m>M',   as_of_date = period end,
                                  value_text = period start, m in {3, 6, 9, 12}
- published_at = acceptance time of the filing (accession matched in the submissions feed),
  else the end of the SEC 'filed' date (conservative). A value restated by a later filing is
  stored as a new version: at instant T only the version available at T is used.

Definitions (documented, not calibrated):
- Revenue TTM at period end E:
    12M fact ending at E, else  FY (12M ending the day before the YTD start)
                                + YTD(E) - YTD(same length, ending ~1 year before E).
  Tags tried: REVENUE_TAGS; the tag with the most recent computable TTM wins (ties: order).
  Tags are never mixed inside one TTM computation.
- Revenue growth: TTM(E) / TTM(~E - 1 year) - 1, same tag.
- Debt: first definition of DEBT_DEFINITIONS whose main tag is reported at the balance-sheet
  date; optional current portions of the same definition are added when reported.
  Lease liabilities are excluded. No debt tag at that date -> debt unavailable (never 0).
- Debt / equity: debt / StockholdersEquity (parent only) at the same date; unavailable when
  equity <= 0 (ratio not meaningful).
"""

from datetime import date, timedelta

from .common import end_of_us_trading_day_utc

REVENUE_TAGS = ('Revenues',
                'RevenueFromContractWithCustomerExcludingAssessedTax',
                'RevenueFromContractWithCustomerIncludingAssessedTax',
                'SalesRevenueNet')
EQUITY_TAG = 'StockholdersEquity'
# (main tags (first reported is used), optional additional tags of the same definition)
DEBT_DEFINITIONS = (
    (('LongTermDebt',), ()),
    (('LongTermDebtNoncurrent',), ('LongTermDebtCurrent', 'DebtCurrent')),
    (('ConvertibleDebtNoncurrent', 'ConvertibleNotesPayable'),
     ('ConvertibleDebtCurrent', 'ConvertibleNotesPayableCurrent')),
)
DEBT_TAGS = tuple(dict.fromkeys(t for main, extra in DEBT_DEFINITIONS for t in main + extra))
INSTANT_TAGS = (EQUITY_TAG,) + DEBT_TAGS
DURATION_TAGS = REVENUE_TAGS
PERIODIC_FORMS = ('10-K', '10-Q', '10-K/A', '10-Q/A', '10-KT', '10-QT')
DURATION_MONTHS = (3, 6, 9, 12)
DATE_TOLERANCE_DAYS = 10     # 52/53-week fiscal years shift period ends by a few days


def duration_months(start, end):
    """3 / 6 / 9 / 12 for a fiscal quarter / YTD / year period, else None."""
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    for m in DURATION_MONTHS:
        if abs(days - m * 365.25 / 12) <= DATE_TOLERANCE_DAYS:
            return m
    return None


def facts_to_observations(ticker, companyfacts, acceptance_by_accession=None):
    """
    Observation rows (see module docstring) from a companyfacts document.
    acceptance_by_accession: {accession: (published_at, basis)} from the submissions feed.
    """
    acceptance_by_accession = acceptance_by_accession or {}
    gaap = ((companyfacts or {}).get('facts') or {}).get('us-gaap') or {}
    rows, seen = [], set()
    for tag in INSTANT_TAGS + DURATION_TAGS:
        for fact in ((gaap.get(tag) or {}).get('units') or {}).get('USD', []):
            if fact.get('form') not in PERIODIC_FORMS or fact.get('val') is None or not fact.get('end'):
                continue
            if tag in DURATION_TAGS:
                if not fact.get('start'):
                    continue
                months = duration_months(fact['start'], fact['end'])
                if months is None:
                    continue
                metric, start = f'xbrl:{tag}:{months}M', fact['start']
            else:
                if fact.get('start'):
                    continue
                metric, start = f'xbrl:{tag}', None
            accession = fact.get('accn')
            if accession in acceptance_by_accession:
                published, basis = acceptance_by_accession[accession]
            elif fact.get('filed'):
                published = end_of_us_trading_day_utc(fact['filed'])
                basis = 'end of SEC filed date (conservative; acceptance time not matched)'
            else:
                continue
            key = (metric, fact['end'], published)
            if key in seen:      # same fact repeated in one filing (e.g. several frames)
                continue
            seen.add(key)
            rows.append({'entity': ticker, 'metric': metric, 'as_of_date': fact['end'],
                         'value': float(fact['val']), 'value_text': start, 'unit': 'USD',
                         'published_at': published, 'published_at_basis': basis})
    return rows


# ---------------------------------------------------------------- computations

def _near(series, target, tol=DATE_TOLERANCE_DAYS):
    """Entry of {end_date: entry} whose date is within tol days of target (closest)."""
    best = None
    for end, entry in series.items():
        gap = abs((date.fromisoformat(end) - target).days)
        if gap <= tol and (best is None or gap < best[0]):
            best = (gap, end, entry)
    return (best[1], best[2]) if best else None


def ttm_at(durations, end):
    """
    Trailing-twelve-month value at period end `end` from {months: {end: row}} where each row
    has 'value' and 'value_text' (= period start). Returns {'value', 'end', 'method', 'inputs'}.
    """
    if end in durations.get(12, {}):
        row = durations[12][end]
        return {'value': row['value'], 'end': end, 'method': 'annual (12M) fact',
                'inputs': [row]}
    for m in (9, 6, 3):
        row = durations.get(m, {}).get(end)
        if not row or not row.get('value_text'):
            continue
        fy = _near(durations.get(12, {}), date.fromisoformat(row['value_text']) - timedelta(days=1))
        prior = _near(durations.get(m, {}), date.fromisoformat(end) - timedelta(days=365))
        if fy and prior:
            return {'value': fy[1]['value'] + row['value'] - prior[1]['value'], 'end': end,
                    'method': f'FY {fy[0]} + {m}M YTD {end} - {m}M YTD {prior[0]}',
                    'inputs': [fy[1], row, prior[1]]}
    return None


def latest_ttm(durations):
    """(ttm at the most recent computable period end, ttm one year earlier or None)."""
    ends = sorted({e for by_end in durations.values() for e in by_end}, reverse=True)
    for end in ends:
        current = ttm_at(durations, end)
        if current:
            target = date.fromisoformat(end) - timedelta(days=365)
            prior = None
            for other in ends:
                if abs((date.fromisoformat(other) - target).days) <= DATE_TOLERANCE_DAYS:
                    prior = ttm_at(durations, other)
                    if prior:
                        break
            return current, prior
    return None, None


def debt_at(instants, as_of):
    """
    Debt at balance-sheet date `as_of` from {tag: {end: row}}.
    Returns {'value', 'tags'} or None when no debt definition is reported at that date.
    """
    for main_tags, extra_tags in DEBT_DEFINITIONS:
        main = next((t for t in main_tags if as_of in instants.get(t, {})), None)
        if main is None:
            continue
        used = [main] + [t for t in extra_tags if as_of in instants.get(t, {})]
        return {'value': sum(instants[t][as_of]['value'] for t in used), 'tags': used}
    return None
