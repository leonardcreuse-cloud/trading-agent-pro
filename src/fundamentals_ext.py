#!/usr/bin/env python3
"""
Extended company fundamentals (master mission P1) - descriptive, point-in-time

Built on SECParser.fundamentals(ticker, known_at) (revenue TTM, growth, debt, equity, margins, cash flow: the
definitions of src/sec_xbrl.py, unchanged) and the extended XBRL concepts (sec_xbrl EXT_*, EPS, cover-page shares).
Every value comes from SEC XBRL facts available at known_at; a value that cannot be computed is None and its
reason is listed in 'reasons', never 0. These values are NOT inputs of the heuristic signal.

Formulas (E = period end of the revenue TTM, B = balance-sheet date of debt / equity):
  revenue_q, revenue_q_yoy_pct  3-month revenue ending E with the TTM's tag (3M fact; at a fiscal year end without
                                a 3M fact: 12M(E) - 9M YTD of the same fiscal year, 'derived'); growth vs the
                                3-month period ending ~1 year earlier (same rule)
  *_margin_pct_prior_year       margins at the TTM end ~1 year before E (trend = difference in points)
  eps_diluted_ttm               EarningsPerShareDiluted: 12M fact ending E ('exact'); else FY + YTD - prior YTD
                                ('approximate': EPS is not additive when the share count changes), used only when
                                no split is suspected (cover-page count changed < 40% in a year) and its sign
                                matches net income TTM; else net income TTM / diluted weighted shares of the
                                latest period ('approximate, consistent share basis')
  cash, short_term_investments  at B (+/- 10 days): CashAndCashEquivalentsAtCarryingValue; first reported of
                                ShortTermInvestments, MarketableSecuritiesCurrent, AFS debt securities current
  net_debt                      debt - cash - short-term investments (debt and cash required; same date)
  current_ratio                 AssetsCurrent / LiabilitiesCurrent at B
  da_ttm, ebitda_ttm            first computable of DA_TAGS (TTM at E), else Depreciation + AmortizationOfIntangible-
                                Assets (both TTM at E, 'sum'); EBITDA = operating income TTM + D&A TTM
  cash_conversion               operating cash flow TTM / net income TTM, only when the net margin is at least
                                CONVERSION_MIN_NET_MARGIN_PCT (a ratio over a near-zero profit is not meaningful)
  cash_runway_years             (cash + short-term investments) / -FCF TTM when FCF TTM < 0 (cash burn)
  interest_coverage             operating income TTM / interest expense TTM (interest > 0)
  rnd_ttm, rnd_pct_revenue      ResearchAndDevelopmentExpense TTM and its share of revenue
  equity_prior_year             equity of the same tag ~1 year before B (for an average-equity ROE)
  shares_outstanding            cover-page shares (dei) of the latest filing known at T, its date, the change vs
                                ~1 year earlier ('sum of N values (share classes)' is flagged)
Not implemented: company guidance (press releases and 8-K exhibits are unstructured text; no structured source).
"""

from datetime import date, timedelta

from .sec_xbrl import (CASH_TAGS, DA_PARTS, DA_TAGS, DATE_TOLERANCE_DAYS, EPS_TAGS, INTEREST_TAGS, LIQUIDITY_TAGS,
                       RND_TAGS, SHORT_TERM_INVESTMENT_TAGS, _near, ttm_at)

GUIDANCE_STATUS = ('NOT IMPLEMENTED: company guidance is published in press releases and 8-K exhibits as '
                   'unstructured text; no structured, verifiable source is wired in')
SHARES_PRIOR_TOLERANCE_DAYS = 45      # cover dates are a few weeks after the period end
SPLIT_SUSPECT_PCT = 40.0              # cover-page share count change in a year above which a split is suspected
CONVERSION_MIN_NET_MARGIN_PCT = 2.0


def _d(day):
    return date.fromisoformat(day)


def quarter_at(durations, end):
    """3-month value ending `end` from {months: {end: row}}: {'value', 'end', 'method', 'inputs'} or None."""
    row = durations.get(3, {}).get(end)
    if row:
        return {'value': row['value'], 'end': end, 'method': '3M fact', 'inputs': [row]}
    year = durations.get(12, {}).get(end)
    if year and year.get('value_text'):
        nine = _near(durations.get(9, {}), _d(end) - timedelta(days=91))
        if nine and nine[1].get('value_text') and \
                abs((_d(nine[1]['value_text']) - _d(year['value_text'])).days) <= DATE_TOLERANCE_DAYS:
            return {'value': year['value'] - nine[1]['value'], 'end': end,
                    'method': f'12M ending {end} - 9M YTD ending {nine[0]} (derived)', 'inputs': [year, nine[1]]}
    return None


def _ends(durations):
    return sorted({e for by_end in durations.values() for e in by_end})


def _prior_end(durations, end, compute):
    """A period end ~1 year before `end` (within the date tolerance) where `compute` succeeds: (end, value)."""
    target = _d(end) - timedelta(days=365)
    for other in sorted(_ends(durations), key=lambda e: abs((_d(e) - target).days)):
        if abs((_d(other) - target).days) > DATE_TOLERANCE_DAYS:
            break
        got = compute(durations, other)
        if got:
            return other, got
    return None, None


def _instant(instants, tags, day, tol=DATE_TOLERANCE_DAYS):
    """First of `tags` reported within tol days of `day`: {'tag', 'value', 'date', 'row'} or None."""
    for tag in tags:
        hit = _near(instants.get(tag, {}), _d(day), tol)
        if hit:
            return {'tag': tag, 'value': hit[1]['value'], 'date': hit[0], 'row': hit[1]}
    return None


def _ratio(num, den, digits=2, positive_den=True):
    if num is None or den is None or (positive_den and den <= 0) or den == 0:
        return None
    return round(num / den, digits)


def _pct(num, den):
    v = _ratio(num, den, 6)
    return None if v is None else round(v * 100, 2)


def extended(sec, ticker, known_at=None, base=None):
    """
    Extended fundamentals at known_at (see module docstring). base: SECParser.fundamentals(ticker, known_at), reused
    when the caller already has it. Returns a dict with the base fields, the extended fields and 'reasons'.
    """
    F = base or sec.fundamentals(ticker, known_at)
    out = dict(F)
    reasons = []
    out.update({'guidance': None, 'guidance_status': GUIDANCE_STATUS})
    known = F.get('known_at')
    end, tag = F.get('revenue_period_end'), F.get('revenue_tag')
    if not known:
        out['reasons'] = [F.get('reason') or 'SEC fundamentals unavailable']
        return out

    # quarterly revenue and its growth
    q = qp = None
    if end and tag:
        rev = sec._durations(ticker, tag, known)
        q = quarter_at(rev, end)
        if q:
            _, qp = _prior_end(rev, end, quarter_at)
        else:
            reasons.append(f'3-month revenue ending {end} not computable')
    out.update({'revenue_q': q and q['value'], 'revenue_q_method': q and q['method'],
                'revenue_q_prior_year': qp and qp['value'],
                'revenue_q_yoy_pct': _pct(q['value'] - qp['value'], qp['value']) if q and qp and qp['value'] > 0
                else None})

    # margins one year earlier (trend)
    prior_margins = {}
    if end and tag:
        prior_end, prior_ttm = _prior_end(sec._durations(ticker, tag, known), end, ttm_at)
        if prior_ttm:
            P = sec.profitability(ticker, prior_end, prior_ttm['value'], known)
            prior_margins = {k: P.get(k) for k in ('gross_margin_pct', 'operating_margin_pct', 'net_margin_pct',
                                                   'fcf_margin_pct')}
            out['margins_prior_year_end'] = prior_end
    for k in ('gross_margin_pct', 'operating_margin_pct', 'net_margin_pct', 'fcf_margin_pct'):
        prev = prior_margins.get(k)
        out[f'{k}_prior_year'] = prev
        out[f'{k}_change_pts'] = round(F[k] - prev, 2) if F.get(k) is not None and prev is not None else None
    out.setdefault('margins_prior_year_end', None)

    # cover-page shares outstanding (dilution)
    shares = dict(sec.db.series(ticker, 'dei:SharesOutstanding', known_at=known, source='SEC EDGAR'))
    if shares:
        last = max(shares)
        row = shares[last]
        prior = _near(shares, _d(last) - timedelta(days=365), SHARES_PRIOR_TOLERANCE_DAYS)
        out.update({'shares_outstanding': row['value'], 'shares_outstanding_date': last,
                    'shares_outstanding_note': row.get('value_text'),
                    'shares_outstanding_published_at': row.get('published_at'),
                    'shares_outstanding_prior_year': prior[1]['value'] if prior else None,
                    'shares_outstanding_change_pct': _pct(row['value'] - prior[1]['value'], prior[1]['value'])
                    if prior else None})
    else:
        out.update({'shares_outstanding': None, 'shares_outstanding_date': None, 'shares_outstanding_note': None,
                    'shares_outstanding_published_at': None, 'shares_outstanding_prior_year': None,
                    'shares_outstanding_change_pct': None})
        reasons.append('cover-page shares outstanding not reported (several share classes, or not tagged)')
    # EPS, D&A / EBITDA, interest, R&D (TTM at E)
    eps = ttm_at(sec._durations(ticker, EPS_TAGS[0], known), end) if end else None
    eps_value = eps_method = None
    if eps and eps['method'].startswith('annual'):
        eps_value, eps_method = eps['value'], 'exact (12M fact)'
    else:
        split = out.get('shares_outstanding_change_pct') is not None and \
            abs(out['shares_outstanding_change_pct']) >= SPLIT_SUSPECT_PCT
        ni = F.get('net_income_ttm')
        sign_ok = eps is not None and ni is not None and (eps['value'] >= 0) == (ni >= 0)
        if eps and not split and sign_ok:
            eps_value = eps['value']
            eps_method = f"approximate ({eps['method']}; EPS is not additive across periods)"
        elif ni is not None and F.get('diluted_shares'):
            eps_value = ni / F['diluted_shares']
            eps_method = ('approximate, consistent share basis (net income TTM / diluted weighted shares of the period '
                          f"ending {F.get('diluted_shares_period_end')})"
                          + ('; possible split in the period: per-share facts of different periods not combined'
                             if split else '; quarterly EPS facts not combinable' if eps else ''))
    out.update({'eps_diluted_ttm': None if eps_value is None else round(eps_value, 4), 'eps_method': eps_method})
    if end and eps_value is None:
        reasons.append('diluted EPS TTM not computable from XBRL facts')
    flows = {name: sec._flow_ttm(ticker, tags, end, known) if end else None
             for name, tags in (('da', DA_TAGS), ('interest', INTEREST_TAGS), ('rnd', RND_TAGS))}
    da = flows['da']
    if end and not da:
        parts = [sec._flow_ttm(ticker, (tag,), end, known) for tag in DA_PARTS]
        if all(parts):
            da = {'value': sum(x['value'] for x in parts), 'tag': ' + '.join(DA_PARTS) + ' (sum)'}
    out.update({'da_ttm': da and da['value'], 'da_tag': da and da['tag'],
                'ebitda_ttm': F['operating_income_ttm'] + da['value']
                if da and F.get('operating_income_ttm') is not None else None,
                'interest_expense_ttm': flows['interest'] and flows['interest']['value'],
                'rnd_ttm': flows['rnd'] and flows['rnd']['value']})
    if end and not da:
        reasons.append('depreciation and amortisation TTM not reported: EBITDA unavailable')
    out['interest_coverage'] = _ratio(F.get('operating_income_ttm'), out['interest_expense_ttm'], 1)
    out['rnd_pct_revenue'] = _pct(out['rnd_ttm'], F.get('revenue'))
    ni, ocf, fcf = F.get('net_income_ttm'), F.get('operating_cash_flow_ttm'), F.get('free_cash_flow_ttm')
    margin = F.get('net_margin_pct')
    out['cash_conversion'] = _ratio(ocf, ni, 2) if ni is not None and ni > 0 and margin is not None and \
        margin >= CONVERSION_MIN_NET_MARGIN_PCT else None
    if ocf is not None and ni is not None and out['cash_conversion'] is None:
        reasons.append(f'cash conversion not meaningful (net margin below {CONVERSION_MIN_NET_MARGIN_PCT}% or a loss)')

    # balance sheet: cash, investments, liquidity, net debt, prior-year equity
    day = F.get('balance_sheet_date') or F.get('latest_equity_date')
    instants = sec._instants(ticker, CASH_TAGS + SHORT_TERM_INVESTMENT_TAGS + LIQUIDITY_TAGS +
                             ((F.get('equity_tag'),) if F.get('equity_tag') else ()), known)
    cash = _instant(instants, CASH_TAGS, day) if day else None
    sti = _instant(instants, SHORT_TERM_INVESTMENT_TAGS, day) if day else None
    ca = _instant(instants, ('AssetsCurrent',), day) if day else None
    cl = _instant(instants, ('LiabilitiesCurrent',), day) if day else None
    out.update({'cash_date': day if cash else None, 'cash': cash and cash['value'],
                'short_term_investments': sti and sti['value'], 'short_term_investments_tag': sti and sti['tag'],
                'current_ratio': _ratio(ca and ca['value'], cl and cl['value'], 2)})
    if day and not cash:
        reasons.append(f'cash and equivalents not reported at {day}')
    liquid = None if cash is None else cash['value'] + (sti['value'] if sti else 0.0)
    out['cash_and_short_term_investments'] = liquid
    out['net_debt'] = F['debt'] - liquid if F.get('debt') is not None and liquid is not None and \
        F.get('balance_sheet_date') else None
    if F.get('debt') is None:
        reasons.append('debt unavailable: net debt and enterprise value unavailable')
    out['cash_runway_years'] = round(liquid / -fcf, 1) if fcf is not None and fcf < 0 and liquid is not None else None
    eq_prior = None
    if day and F.get('equity_tag'):
        eq_prior = _near(instants.get(F['equity_tag'], {}), _d(day) - timedelta(days=365))
    out['equity_prior_year'] = eq_prior[1]['value'] if eq_prior else None

    out['reasons'] = reasons
    return out


def revenue_years_ago(sec, ticker, F, years=3):
    """Revenue TTM (same tag) at the period end ~`years` years before F's TTM end, known at F's instant; None if not
    computable."""
    end, tag, known = F.get('revenue_period_end'), F.get('revenue_tag'), F.get('known_at')
    if not (end and tag and known):
        return None
    durations = sec._durations(ticker, tag, known)
    target = _d(end) - timedelta(days=round(365.25 * years))
    for other in sorted(_ends(durations), key=lambda e: abs((_d(e) - target).days)):
        if abs((_d(other) - target).days) > DATE_TOLERANCE_DAYS:
            break
        got = ttm_at(durations, other)
        if got:
            return got['value']
    return None
