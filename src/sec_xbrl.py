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
- Debt (P1.5 mapping): the first definition of DEBT_DEFINITIONS whose main concept is reported
  at the balance-sheet date. Each definition says how its current portion is found and whether
  short-term borrowings must be added (first of ShortTermBorrowings, CommercialPaper: commercial
  paper is part of short-term borrowings, never both). DebtCurrent already contains short-term
  borrowings, so they are not added on top of it. Definitions are checked against reported
  totals (e.g. ORCL 2024-05-31: DebtLongtermAndShorttermCombinedAmount 86.87 B =
  LongTermNotesAndLoans 76.26 + NotesPayableCurrent 10.61; GE 2023-09-30: 20.82 =
  LongTermDebtAndCapitalLeaseObligations 19.49 + DebtCurrent 1.33).
  'debt_and_finance_leases' includes finance-lease obligations (flagged in the output).
  No debt concept at that date -> debt unavailable (never 0): companies that tag debt only
  with company-specific extensions (not in company facts) stay DATA UNAVAILABLE.
- Equity: StockholdersEquity (parent); else total equity including noncontrolling interests
  (flagged).
- Debt / equity at the latest balance-sheet date where both debt and equity are reported
  (some filers tag debt only in the 10-K), at most MAX_BALANCE_AGE_DAYS before the latest
  equity date; unavailable when equity <= 0 (ratio not meaningful).
"""

from datetime import date, timedelta

from .common import end_of_us_trading_day_utc

REVENUE_TAGS = ('Revenues',
                'RevenueFromContractWithCustomerExcludingAssessedTax',
                'RevenueFromContractWithCustomerIncludingAssessedTax',
                'SalesRevenueNet')
EQUITY_TAG = 'StockholdersEquity'
EQUITY_TAGS = (EQUITY_TAG, 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest')
SHORT_TERM_TAGS = ('ShortTermBorrowings', 'CommercialPaper')
MAX_BALANCE_AGE_DAYS = 400
# name: (main concepts (first reported wins), current-portion concepts (first reported wins),
#        add short-term borrowings?, includes finance leases?)
# A current portion given by 'DebtCurrent' already includes short-term borrowings.
DEBT_DEFINITIONS = (
    ('combined_total', ('DebtLongtermAndShorttermCombinedAmount',), (), False, False),
    ('long_term_debt_total', ('LongTermDebt',), (), True, False),
    ('long_term_debt_split', ('LongTermDebtNoncurrent',), ('LongTermDebtCurrent', 'DebtCurrent'), True, False),
    ('debt_and_finance_leases', ('LongTermDebtAndCapitalLeaseObligations',),
     ('LongTermDebtAndCapitalLeaseObligationsCurrent', 'DebtCurrent'), True, True),
    ('notes_and_loans', ('LongTermNotesAndLoans',), ('NotesPayableCurrent', 'DebtCurrent'), True, False),
    ('convertible', ('ConvertibleDebtNoncurrent', 'ConvertibleNotesPayable', 'ConvertibleLongTermNotesPayable'),
     ('ConvertibleDebtCurrent', 'ConvertibleNotesPayableCurrent'), True, False),
)
DEBT_TAGS = tuple(dict.fromkeys([t for d in DEBT_DEFINITIONS for t in d[1] + d[2]] + list(SHORT_TERM_TAGS)))
INSTANT_TAGS = EQUITY_TAGS + DEBT_TAGS
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


def facts_to_observations(ticker, companyfacts, acceptance_by_accession=None,
                          instant_tags=INSTANT_TAGS, duration_tags=DURATION_TAGS,
                          namespace='us-gaap', unit='USD'):
    """
    Observation rows (see module docstring) from a companyfacts document.
    acceptance_by_accession: {accession: (published_at, basis)} from the submissions feed.
    instant_tags / duration_tags / namespace / unit select other concepts (research panel:
    e.g. dei EntityCommonStockSharesOutstanding in 'shares'); defaults = production set.
    """
    acceptance_by_accession = acceptance_by_accession or {}
    gaap = ((companyfacts or {}).get('facts') or {}).get(namespace) or {}
    rows, seen = [], set()
    for tag in tuple(instant_tags) + tuple(duration_tags):
        for fact in ((gaap.get(tag) or {}).get('units') or {}).get(unit, []):
            if fact.get('form') not in PERIODIC_FORMS or fact.get('val') is None or not fact.get('end'):
                continue
            if tag in duration_tags:
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
                         'value': float(fact['val']), 'value_text': start, 'unit': unit,
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
    Returns {'value', 'tags', 'definition', 'includes_finance_leases'} or None when no debt
    definition is reported at that date.
    """
    def first(tags):
        return next((t for t in tags if as_of in instants.get(t, {})), None)
    for name, main_tags, current_tags, add_short_term, leases in DEBT_DEFINITIONS:
        main = first(main_tags)
        if main is None:
            continue
        used = [main]
        current = first(current_tags)
        if current:
            used.append(current)
        if add_short_term and current != 'DebtCurrent':
            short = first(SHORT_TERM_TAGS)
            if short:
                used.append(short)
        return {'value': sum(instants[t][as_of]['value'] for t in used), 'tags': used,
                'definition': name, 'includes_finance_leases': leases}
    return None


def equity_at(instants, as_of):
    """(row, tag) of stockholders' equity at as_of: parent first, else including NCI."""
    for tag in EQUITY_TAGS:
        if as_of in instants.get(tag, {}):
            return instants[tag][as_of], tag
    return None, None


def balance_sheet(instants, max_age_days=MAX_BALANCE_AGE_DAYS):
    """
    Latest date with both equity and debt reported, within max_age_days of the latest
    equity date. Returns {'latest_equity_date', 'date', 'equity', 'equity_tag', 'debt'}.
    """
    equity_dates = sorted({d for t in EQUITY_TAGS for d in instants.get(t, {})}, reverse=True)
    if not equity_dates:
        return {'latest_equity_date': None, 'date': None, 'equity': None, 'equity_tag': None,
                'debt': None}
    latest = equity_dates[0]
    limit = date.fromisoformat(latest) - timedelta(days=max_age_days)
    for day in equity_dates:
        if date.fromisoformat(day) < limit:
            break
        debt = debt_at(instants, day)
        if debt:
            equity, tag = equity_at(instants, day)
            return {'latest_equity_date': latest, 'date': day, 'equity': equity,
                    'equity_tag': tag, 'debt': debt}
    equity, tag = equity_at(instants, latest)
    return {'latest_equity_date': latest, 'date': latest, 'equity': equity, 'equity_tag': tag,
            'debt': None}
