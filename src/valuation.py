#!/usr/bin/env python3
"""
Valuation ratios (master mission P1) - market value from an observed close and SEC fundamentals

Every ratio carries its formula, its inputs (value, date, source) and, when it is not computed, the reason. A
ratio whose denominator is not positive is 'not meaningful' (None), never a number; so is an earnings, EBITDA or
free-cash-flow multiple whose denominator is below MIN_DENOMINATOR_PCT_OF_REVENUE of revenue (a multiple of a
near-zero profit, e.g. a P/E of several thousand, says nothing about valuation).

  shares            cover-page shares outstanding known at T (dei, src/fundamentals_ext.py) when dated within
                    MAX_SHARES_AGE_DAYS before the close; else diluted weighted-average shares of the latest
                    reported period ('approximation' flag)
  market_cap        close x shares
  enterprise_value  market_cap + debt - cash - short-term investments, all at the same balance-sheet date (debt per
                    the frozen definitions of src/sec_xbrl.py; finance leases only where that definition includes
                    them). Minority interests, preferred stock and operating leases are not added (limitation).
  pe                close / diluted EPS TTM (EPS > 0)
  pb                market_cap / equity (equity > 0)
  roe_pct           net income TTM / average(equity, equity ~1 year earlier) (both > 0); else / equity (flagged)
  ps, pfcf          market_cap / revenue TTM, market_cap / free cash flow TTM (FCF > 0)
  ev_sales          enterprise_value / revenue TTM
  ev_ebitda         enterprise_value / EBITDA TTM (EBITDA > 0)
  fcf_yield_pct     free cash flow TTM / market_cap
The close is the caller's (yfinance, rank 2, split-adjusted). A change of >= SPLIT_SUSPECT_PCT in the cover-page
share count over one year is flagged (a split or a large issuance makes per-share comparisons unreliable).

Historical comparison (history_points / percentile): the same ratios at past dates, each with the fundamentals
known at that date and the close of that date. Yahoo closes are split-adjusted to today's share basis while SEC
counts are as reported, so the history stops at the first earlier point whose share count differs from the
current one by SPLIT_SUSPECT_PCT or more (possible split): it is truncated, never mixed. Descriptive only:
a percentile says where the ratio sits in its own recent history, not whether the stock is cheap.
"""

from datetime import date, timedelta

MAX_SHARES_AGE_DAYS = 200
SPLIT_SUSPECT_PCT = 40.0
MIN_HISTORY_POINTS = 8
MIN_DENOMINATOR_PCT_OF_REVENUE = 2.0
RATIOS = ('pe', 'pb', 'roe_pct', 'ps', 'pfcf', 'ev_sales', 'ev_ebitda', 'fcf_yield_pct')
LABELS = {'market_cap': 'market capitalisation (USD)', 'enterprise_value': 'enterprise value (USD)',
          'pe': 'price / diluted EPS TTM', 'pb': 'price / book (market cap / equity)',
          'roe_pct': 'return on equity (%)', 'ps': 'price / sales TTM', 'pfcf': 'price / free cash flow TTM',
          'ev_sales': 'EV / sales TTM', 'ev_ebitda': 'EV / EBITDA TTM', 'fcf_yield_pct': 'free cash flow yield (%)'}
FORMULAS = {'market_cap': 'close x shares', 'enterprise_value': 'market cap + debt - cash - short-term investments',
            'pe': 'close / diluted EPS TTM', 'pb': 'market cap / equity',
            'roe_pct': 'net income TTM / average equity (now, ~1 year earlier) x 100',
            'ps': 'market cap / revenue TTM', 'pfcf': 'market cap / free cash flow TTM',
            'ev_sales': 'enterprise value / revenue TTM', 'ev_ebitda': 'enterprise value / EBITDA TTM',
            'fcf_yield_pct': 'free cash flow TTM / market cap x 100'}


def _entry(value, reason=None, digits=2, **inputs):
    return {'value': None if value is None else round(value, digits), 'reason': None if value is not None else reason,
            'inputs': inputs}


def _div(num, den, name, revenue=None, per_share=None):
    """num / den, or (None, reason). revenue (and per_share = shares, for a per-share denominator) applies the
    MIN_DENOMINATOR_PCT_OF_REVENUE rule."""
    if num is None:
        return None, f'{name}: numerator unavailable'
    if den is None:
        return None, f'{name}: denominator unavailable'
    if den <= 0:
        return None, f'{name}: not meaningful (denominator <= 0)'
    if revenue:
        total = den * per_share if per_share else den
        if total / revenue * 100 < MIN_DENOMINATOR_PCT_OF_REVENUE:
            return None, (f'{name}: not meaningful (denominator {total / revenue * 100:.2f}% of revenue, below '
                          f'{MIN_DENOMINATOR_PCT_OF_REVENUE}%)')
    return num / den, None


# flag of a share count that moved by SPLIT_SUSPECT_PCT or more in a year: the market-cap-based ratios may mix pre- and
# post-split figures, or the share count and the price data may disagree on a split; unless the change is explained
# by a split in the price data (split_explained), such a peer is shown but left out of peer medians
SHARE_COUNT_SUSPECT = 'possible split or large issuance'
SPLIT_MATCH_TOL = 0.15          # split ratio vs share-count ratio (issuance / buybacks in between), as in the audit


def split_explained(X, splits):
    """
    True when the yearly change of the cover-page share count in X equals (within SPLIT_MATCH_TOL) the product of
    the splits dated after the prior count and no later than the latest count's cover date or publication (a
    filing made after a split reports the post-split count); False when it does not; None when unknown.
    """
    change, lo, hi = (X.get('shares_outstanding_change_pct'), X.get('shares_outstanding_prior_date'),
                      X.get('shares_outstanding_date'))
    if change is None or not lo or not hi or splits is None or change <= -100:
        return None
    hi = max(hi, (X.get('shares_outstanding_published_at') or hi)[:10])
    product = 1.0
    for d, r in splits.items():
        if lo < d <= hi and r:
            product *= r
    return product != 1.0 and abs(product / (1 + change / 100) - 1) <= SPLIT_MATCH_TOL


def shares_for(X, close_date):
    """(shares, basis, flags) for a close on close_date from extended fundamentals X."""
    flags = []
    so, so_date = X.get('shares_outstanding'), X.get('shares_outstanding_date')
    if so and so_date and 0 <= (date.fromisoformat(close_date) - date.fromisoformat(so_date)).days <= MAX_SHARES_AGE_DAYS:
        if X.get('shares_outstanding_note'):
            flags.append(f"shares: {X['shares_outstanding_note']}")
        change = X.get('shares_outstanding_change_pct')
        if change is not None and abs(change) >= SPLIT_SUSPECT_PCT:
            flags.append(f'share count changed {change:+.1f}% in a year: {SHARE_COUNT_SUSPECT}')
        return so, f'cover-page shares outstanding on {so_date} (SEC dei)', flags
    if X.get('diluted_shares'):
        flags.append('approximation: diluted weighted-average shares of the period ending '
                     f"{X.get('diluted_shares_period_end')} (cover-page count not available or too old)")
        return X['diluted_shares'], 'diluted weighted-average shares (SEC)', flags
    return None, None, ['no share count known at that date']


def ratios(X, close, close_date, close_source='yfinance close (rank 2)'):
    """
    {'market_cap', 'enterprise_value', <ratio>: {'value', 'reason', 'inputs'}, 'shares_basis', 'flags'} from
    extended fundamentals X (src/fundamentals_ext.py) and a close.
    """
    shares, basis, flags = shares_for(X, close_date) if close is not None else (None, None, ['no close'])
    out = {'close': close, 'close_date': close_date, 'close_source': close_source, 'shares': shares,
           'shares_basis': basis, 'flags': list(flags)}
    mc = close * shares if close is not None and shares else None
    out['market_cap'] = _entry(mc, 'no close or no share count', 0, close=close, shares=shares)
    ev, ev_reason = None, None
    if mc is None:
        ev_reason = 'market cap unavailable'
    elif X.get('debt') is None:
        ev_reason = 'debt unavailable at the balance-sheet date'
    elif X.get('cash_and_short_term_investments') is None:
        ev_reason = 'cash unavailable at the balance-sheet date'
    else:
        ev = mc + X['debt'] - X['cash_and_short_term_investments']
    out['enterprise_value'] = _entry(ev, ev_reason, 0, market_cap=mc, debt=X.get('debt'),
                                     cash_and_short_term_investments=X.get('cash_and_short_term_investments'),
                                     balance_sheet_date=X.get('balance_sheet_date'))
    eps = X.get('eps_diluted_ttm')
    v, r = _div(close, eps, 'P/E', X.get('revenue'), shares)
    out['pe'] = _entry(v, r, close=close, eps_diluted_ttm=eps, eps_method=X.get('eps_method'))
    v, r = _div(mc, X.get('equity'), 'P/B')
    out['pb'] = _entry(v, r, market_cap=mc, equity=X.get('equity'))
    eq, eq0, ni = X.get('equity'), X.get('equity_prior_year'), X.get('net_income_ttm')
    if eq is not None and eq0 is not None and eq > 0 and eq0 > 0:
        v, r = _div(ni, (eq + eq0) / 2, 'ROE')
        roe_basis = 'average equity'
    else:
        v, r = _div(ni, eq, 'ROE')
        roe_basis = 'ending equity (prior-year equity unavailable)'
    out['roe_pct'] = _entry(None if v is None else v * 100, r, net_income_ttm=ni, equity=eq,
                            equity_prior_year=eq0, basis=roe_basis)
    rev = X.get('revenue')
    for key, num, den, name, floor in (('ps', mc, rev, 'P/S', None), ('pfcf', mc, X.get('free_cash_flow_ttm'), 'P/FCF', rev),
                                       ('ev_sales', ev, rev, 'EV/sales', None),
                                       ('ev_ebitda', ev, X.get('ebitda_ttm'), 'EV/EBITDA', rev)):
        v, r = _div(num, den, name, floor)
        out[key] = _entry(v, r, numerator=num, denominator=den)
    fcf = X.get('free_cash_flow_ttm')
    out['fcf_yield_pct'] = _entry(fcf / mc * 100 if fcf is not None and mc else None,
                                  'free cash flow or market cap unavailable', free_cash_flow_ttm=fcf, market_cap=mc)
    return out


def history_points(sec, extended_fn, ticker, closes, end_day, years=5, step_days=91, known_at_fn=None):
    """
    Ratios at past dates (every step_days back from end_day over `years`), each with the fundamentals known at the
    close of that date (point-in-time) and that close. closes: {iso date: close}. extended_fn(sec, ticker, known_at)
    returns extended fundamentals. Returns (points oldest first, truncation note or None).
    """
    from .market_data import session_close_utc
    known_at_fn = known_at_fn or session_close_utc
    days = sorted(closes)
    points, note, current_shares = [], None, None
    target = date.fromisoformat(end_day)
    stop = target - timedelta(days=int(365.25 * years))
    while target >= stop:
        eligible = [d for d in days if d <= target.isoformat()]
        if not eligible:
            break
        day = eligible[-1]
        X = extended_fn(sec, ticker, known_at_fn(day))
        r = ratios(X, closes[day], day)
        if current_shares is None:
            current_shares = r['shares']
        elif r['shares'] and current_shares and \
                abs(r['shares'] / current_shares - 1) * 100 >= SPLIT_SUSPECT_PCT:
            note = (f'history stops at {day}: share count {r["shares"]:,.0f} vs {current_shares:,.0f} now '
                    f'(>= {SPLIT_SUSPECT_PCT:.0f}% apart: possible split; split-adjusted closes would be mixed with '
                    'as-reported share counts)')
            break
        points.append({'date': day, **{k: r[k]['value'] for k in RATIOS}})
        target -= timedelta(days=step_days)
    return list(reversed(points)), note


def percentile(points, key, current):
    """Share (%) of historical points below `current` (ties count half); None below MIN_HISTORY_POINTS."""
    values = [p[key] for p in points if p.get(key) is not None]
    if current is None or len(values) < MIN_HISTORY_POINTS:
        return None, len(values)
    below = sum(v < current for v in values) + 0.5 * sum(v == current for v in values)
    return round(below / len(values) * 100, 1), len(values)


def peer_median(values):
    """Median of the non-missing values and their count."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None, 0
    n = len(xs)
    return (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2), n


def peer_medians(peer_ratios, explained=None):
    """
    peer_ratios: [(ticker, ratios(...) output)]; explained: {ticker: split_explained(...)}. Returns
    ({ratio key: (median, n)}, [excluded tickers]); a peer whose share count is flagged SHARE_COUNT_SUSPECT is left
    out of every median (and marked in its flags) unless a split in the price data explains the change.
    """
    kept, excluded = [], []
    for ticker, R in peer_ratios:
        if any(SHARE_COUNT_SUSPECT in f for f in R['flags']) and not (explained or {}).get(ticker):
            excluded.append(ticker)
            R['flags'].append('left out of the peer median')
        else:
            kept.append(R)
    return {k: peer_median([R[k]['value'] for R in kept]) for k in RATIOS}, excluded
