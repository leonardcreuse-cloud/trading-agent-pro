#!/usr/bin/env python3
"""
Weekly report section 'valuation' - Q2 "What changed fundamentally?" (master mission P1: extended fundamentals,
valuation ratios, valuation history, peers and intrinsic-value scenarios)

Per company of ctx.universe, everything known at T_c (and T_p for the changes):
  fundamentals   src/fundamentals_ext.extended(ctx.sec, t, known_at): SEC XBRL facts and calculations from them
                 (formulas in that module) -> official_fact (rank 1), one evidence item citing the latest filing used
  ratios         src/valuation.ratios at the unadjusted close of s_0 (yfinance, rank 2) with fundamentals known at
                 T_c -> market_fact + ESTIMATE (single rank-2 price; share count and balance sheet are dated)
  history        the same ratios every 91 days back over 5 years, each with the fundamentals known at that date
                 (point-in-time) and that date's close; percentile of the current value -> interpretation
                 (descriptive; truncated at a suspected split, never mixed)
  peers          the pre-declared peers (config weekly.peers): their ratios at the same close and cutoff; the peer
                 median -> market_fact + ESTIMATE ('relative', no cheap / expensive judgement)
  scenarios      src/intrinsic.dcf: risk-free DGS10 known at T_c (FRED), beta from closes up to s_0 vs the
                 benchmark, revenue history from SEC, ERP / terminal growth from config (assumptions) -> model_output
                 (UNCERTAIN, MODEL_NOT_VALIDATED + ESTIMATE): an estimate under stated assumptions, never a fair value
  guidance       NOT IMPLEMENTED (unstructured text), stated as DATA UNAVAILABLE with that reason
Sections never call the wall clock and never write files.
"""

from ...common import to_utc_iso
from ...database import source_rank
from ...fundamentals_ext import GUIDANCE_STATUS, extended, revenue_years_ago
from ...intrinsic import MIN_BETA_WEEKS, dcf, settings
from ...intrinsic import beta as beta_of
from ...market_data import session_close_utc
from ...sec_parser import SEC_SOURCE
from ...valuation import (FORMULAS, LABELS, RATIOS, SHARE_COUNT_SUSPECT, history_points, peer_medians, percentile,
                          ratios, shares_for, split_explained)
from ..core import SectionResult, conclude, evidence, unavailable

NAME = 'valuation'
QUESTIONS = [2]
SEC_RANK = source_rank(SEC_SOURCE)
FRED_SOURCE = 'FRED'
RISK_FREE_SERIES = 'DGS10'
HISTORY_KEYS = ('ps', 'ev_sales', 'pe', 'pb', 'ev_ebitda', 'fcf_yield_pct')
FUND_ROWS = (
    ('revenue', 'revenue TTM (USD)'), ('revenue_growth_pct', 'revenue growth TTM YoY (%)'),
    ('revenue_q', 'revenue, latest quarter (USD)'), ('revenue_q_yoy_pct', 'quarterly revenue YoY (%)'),
    ('gross_margin_pct', 'gross margin TTM (%)'), ('gross_margin_pct_change_pts', 'gross margin change vs 1 year (pts)'),
    ('operating_margin_pct', 'operating margin TTM (%)'),
    ('operating_margin_pct_change_pts', 'operating margin change vs 1 year (pts)'),
    ('net_margin_pct', 'net margin TTM (%)'), ('eps_diluted_ttm', 'diluted EPS TTM (USD)'),
    ('operating_cash_flow_ttm', 'operating cash flow TTM (USD)'), ('capex_ttm', 'capital expenditure TTM (USD)'),
    ('free_cash_flow_ttm', 'free cash flow TTM (USD)'), ('fcf_margin_pct', 'FCF margin TTM (%)'),
    ('cash_conversion', 'cash conversion (OCF / net income)'), ('ebitda_ttm', 'EBITDA TTM (USD)'),
    ('cash', 'cash and equivalents (USD)'), ('short_term_investments', 'short-term investments (USD)'),
    ('debt', 'debt (USD)'), ('net_debt', 'net debt (USD)'), ('equity', 'equity (USD)'),
    ('debt_to_equity', 'debt / equity'), ('current_ratio', 'current ratio'),
    ('interest_coverage', 'interest coverage (operating income / interest)'),
    ('cash_runway_years', 'cash runway at the current burn (years)'), ('rnd_pct_revenue', 'R&D / revenue (%)'),
    ('shares_outstanding', 'shares outstanding, cover page'),
    ('shares_outstanding_change_pct', 'shares outstanding change vs 1 year (%)'))


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _fmt(v):
    v = _num(v)
    if v is None:
        return None
    return round(v, 2) if abs(v) < 1e5 else round(v)


def _fresh(ctx, as_of, cadence='quarterly_filing'):
    if not as_of:
        return None
    status = (ctx.freshness(str(as_of)[:10], cadence) or {}).get('status')
    return True if status == 'FRESH' else False if status == 'STALE' else None


def _published(X):
    pubs = [to_utc_iso(X.get(k)) for k in ('revenue_published_at', 'profitability_published_at',
                                           'shares_outstanding_published_at', 'diluted_shares_published_at')]
    return max((p for p in pubs if p), default=None)


def _sec_item(ctx, t, X):
    pub = _published(X)
    if not pub:
        return None
    fetch = X.get('fetch') or {}
    as_of = X.get('revenue_period_end') or X.get('balance_sheet_date')
    return evidence(ctx.tm, SEC_SOURCE, SEC_RANK, f'{t}: SEC XBRL facts for the period ending {as_of} '
                    f"(revenue tag {X.get('revenue_tag')}, balance sheet {X.get('balance_sheet_date')})",
                    as_of=as_of, published_at=pub, retrieved_at=fetch.get('retrieved_at'),
                    fetch_id=fetch.get('fetch_id'), fresh=_fresh(ctx, as_of),
                    basis='acceptance time of the latest filing used')


def _close(ctx, t, idx=-1):
    from .market import prices_aligned, value
    px = prices_aligned(ctx, t)
    if px.get('status') != 'OK':
        return None, None, px
    frame = px['frame']
    v = value(frame, 'close_raw', idx)
    day = frame.index[idx] if v is not None and len(frame) >= -idx else None
    return v, day, px


def _closes(ctx, t, col='close'):
    p = ctx.prices(t)
    frame = p.get('frame')
    if p.get('status') != 'OK' or frame is None:
        return {}
    out = {}
    for d, v in frame[col].items():
        v = _num(v)
        if v is not None and v > 0:
            out[d.date().isoformat() if hasattr(d, 'date') else str(d)[:10]] = v
    return out


def _risk_free(ctx):
    """(value %, obs date, published_at, fetch) of DGS10 known at T_c, or (None, reason)."""
    st = ctx.fred(RISK_FREE_SERIES) or {}
    if st.get('status') != 'OK':
        return None, f"FRED {RISK_FREE_SERIES}: {st.get('reason') or 'unavailable'}"
    got = ctx.value_at(RISK_FREE_SERIES, ctx.tm.cutoff)
    if not got or got[1] is None:
        return None, f'FRED {RISK_FREE_SERIES}: no observation known at the cutoff'
    return {'value': got[1], 'date': str(got[0])[:10], 'published_at': got[2], 'fetch': st.get('fetch') or {}}, None


def _fundamentals(ctx, res, t, X, X_p, item):
    rows = []
    for key, label in FUND_ROWS:
        a, b = X_p.get(key) if X_p else None, X.get(key)
        rows.append([label, _fmt(a), _fmt(b),
                     None if _num(a) is None or _num(b) is None else _fmt(_num(b) - _num(a))])
    res.table(f'{t}: fundamentals (SEC XBRL, point-in-time)', ['measure', 'known at T_p', 'known at T_c', 'change'],
              rows, scope=t, question=2,
              note=f"Period end {X.get('revenue_period_end')}, balance sheet {X.get('balance_sheet_date')}. EPS: "
                   f"{X.get('eps_method') or 'n/a'}. D&A tag: {X.get('da_tag') or 'n/a'}. Formulas: "
                   'src/fundamentals_ext.py. A missing value is not reported or not computable (reasons: '
                   + ('; '.join(X.get('reasons') or []) or 'none') + ').')
    if item is None:
        res.add(unavailable(t, 2, 'extended fundamentals', X.get('reason') or 'no SEC facts known at the cutoff'))
        return
    parts = []
    for key, label in (('revenue_q_yoy_pct', 'quarterly revenue YoY'), ('gross_margin_pct', 'gross margin'),
                       ('operating_margin_pct', 'operating margin'), ('fcf_margin_pct', 'FCF margin'),
                       ('net_debt', 'net debt'), ('current_ratio', 'current ratio'),
                       ('shares_outstanding_change_pct', 'share count change in a year')):
        v = _num(X.get(key))
        if v is not None:
            unit = '%' if key.endswith('pct') else '' if key == 'current_ratio' else ' USD'
            shown = f'{v:,.0f}{unit}' if unit == ' USD' else f'{v:.2f}{unit}'
            change = X.get(f'{key}_change_pts')
            parts.append(f'{label} {shown}' + (f' ({change:+.2f} pts vs a year earlier)' if change is not None else ''))
    if parts:
        res.add(conclude(t, 2, f"{t}: SEC facts known at the cutoff (period ending {X.get('revenue_period_end')}): "
                               + '; '.join(parts) + '. Calculated from reported facts (formulas in '
                               'src/fundamentals_ext.py).', [item], 'official_fact'))


def _ratios_table(t, R, title_suffix):
    rows = [[LABELS[k], FORMULAS[k], _fmt(R[k]['value']), R[k]['reason']]
            for k in ('market_cap', 'enterprise_value') + RATIOS]
    return rows, (f"{t}: valuation ratios {title_suffix}", ['ratio', 'formula', 'value', 'not computed because'])


def _split_note(ctx, ticker, X, R):
    """For a share count flagged SHARE_COUNT_SUSPECT: whether a split in the price data explains it (noted in flags)."""
    if not any(SHARE_COUNT_SUSPECT in f for f in R['flags']):
        return None
    sp = ctx.splits(ticker) if hasattr(ctx, 'splits') else {'splits': None, 'reason': 'no split accessor'}
    ok = split_explained(X, sp.get('splits'))
    R['flags'].append('the change matches the split(s) in the price data (yfinance): market cap on one basis'
                      if ok else 'no split of that ratio in the price data (yfinance): share count and price may '
                                 'be on different bases' if ok is False else
                      f"split data unavailable ({sp.get('reason') or 'no prior count'})")
    return ok


def build(ctx, tickers=None, history=True):
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    universe = list(tickers or ctx.universe)
    peers_cfg = (getattr(ctx, 'weekly', None) or {}).get('peers') or {}
    config = getattr(ctx, 'config', None) or {}
    dcf_settings, defaulted = settings(config)
    rf, rf_reason = _risk_free(ctx) if hasattr(ctx, 'fred') else (None, 'no FRED accessor in this context')
    rf_item = None
    if rf:
        rf_item = evidence(tm, FRED_SOURCE, source_rank(FRED_SOURCE),
                           f"10-year Treasury yield (DGS10) {rf['value']}% on {rf['date']}", as_of=rf['date'],
                           published_at=rf['published_at'], retrieved_at=rf['fetch'].get('retrieved_at'),
                           fetch_id=rf['fetch'].get('fetch_id'), basis='FRED vintage known at the cutoff')
    benchmark = (getattr(ctx, 'weekly', None) or {}).get('benchmark', 'SPY')
    bench = _closes(ctx, benchmark) if hasattr(ctx, 'prices') else {}
    cache = {}

    def ext(ticker, known):
        key = (ticker, known)
        if key not in cache:
            cache[key] = extended(ctx.sec, ticker, known)
        return cache[key]

    for t in universe:
        X = ext(t, tm.cutoff)
        X_p = ext(t, tm.previous_cutoff)
        item = _sec_item(ctx, t, X)
        _fundamentals(ctx, res, t, X, X_p, item)
        res.add(unavailable(t, 2, 'company guidance', GUIDANCE_STATUS))
        if not hasattr(ctx, 'prices'):
            res.add(unavailable(t, 2, 'valuation ratios', 'no price accessor in this context'))
            continue
        close, day, px = _close(ctx, t)
        if close is None:
            res.add(unavailable(t, 2, 'valuation ratios', f"no close at s_0 ({px.get('reason')})"))
            continue
        from .market import price_evidence
        p_item = price_evidence(ctx, t, px, f'unadjusted close {close:.2f} on {day}', as_of=day)
        R = ratios(X, close, day)
        _split_note(ctx, t, X, R)
        rows, (title, cols) = _ratios_table(t, R, f'at the close of {day} (fundamentals known at T_c)')
        res.table(title, cols, rows, scope=t, question=2,
                  note=f"Shares: {R['shares_basis']}. " + ' '.join(R['flags']) + ' Enterprise value excludes '
                       'minority interests, preferred stock and operating leases. Descriptive: no cheap / expensive '
                       'judgement.')
        shown = [f"{LABELS[k]} {R[k]['value']}" for k in RATIOS if R[k]['value'] is not None]
        mc = R['market_cap']['value']
        codes = ['ESTIMATE'] + (['PARTIAL_COVERAGE'] if R['flags'] else [])
        res.add(conclude(t, 2, f"{t}: at the close of {day} ({close:.2f}), market capitalisation "
                               + (f'{mc / 1e9:,.1f} B USD' if mc else 'unavailable') + ' ('
                               + str(R['shares_basis']) + ')' + ('; ' + '; '.join(shown) if shown else '')
                               + ('; flags: ' + '; '.join(R['flags']) if R['flags'] else '')
                               + '. Derived ratios, descriptive only.',
                         [p_item] + ([item] if item else []), 'market_fact', reason_codes=codes,
                         resolve='a second price source; cover-page share count of the latest filing'))

        # history (point-in-time)
        if history:
            closes_raw = _closes(ctx, t, 'close_raw')
            points, note = history_points(ctx.sec, lambda sec, tk, known: ext(tk, known), t, closes_raw, day,
                                          known_at_fn=lambda d: min(session_close_utc(d), tm.cutoff))
            hist_rows, readings = [], []
            for k in HISTORY_KEYS:
                now = R[k]['value']
                pct, n = percentile(points[:-1], k, now)
                vals = sorted(p[k] for p in points[:-1] if p.get(k) is not None)
                med = vals[len(vals) // 2] if vals else None
                hist_rows.append([LABELS[k], _fmt(now), _fmt(med), _fmt(vals[0]) if vals else None,
                                  _fmt(vals[-1]) if vals else None, n, pct])
                if pct is not None:
                    readings.append(f'{LABELS[k]} {now} is at the {pct:.0f}th percentile of {n} quarterly points')
            first = points[0]['date'] if points else None
            res.table(f'{t}: valuation versus its own history (point-in-time, quarterly points)',
                      ['ratio', 'now', 'history median', 'history min', 'history max', 'points', 'percentile now'],
                      hist_rows, scope=t, question=2,
                      note=f'Points from {first} to {day}, each with the fundamentals known at that date. '
                           + (note or 'No suspected split in the window.') + ' A percentile needs at least 8 '
                           'points. Descriptive: a high percentile is not a sell signal.')
            if readings:
                res.add(conclude(t, 2, f'{t}: ' + '; '.join(readings) + '. Descriptive comparison with its own '
                                       'recent history, not a valuation judgement.',
                                 [p_item] + ([item] if item else []), 'interpretation', reason_codes=['ESTIMATE']))
            elif note:
                res.add(unavailable(t, 2, 'valuation history', note))

        # peers
        peers = peers_cfg.get(t) or []
        if peers:
            computed, explained = [], {}
            for peer in peers:
                pc, pday, _ = _close(ctx, peer)
                if pc is None:
                    computed.append((peer, None))
                    continue
                PX = ext(peer, tm.cutoff)
                PR = ratios(PX, pc, pday)
                explained[peer] = _split_note(ctx, peer, PX, PR)
                computed.append((peer, PR))
            medians, excluded = peer_medians([(peer, PR) for peer, PR in computed if PR is not None], explained)
            peer_rows = [[peer] + [None] * len(HISTORY_KEYS) + ['no close at s_0'] if PR is None else
                         [peer] + [_fmt(PR[k]['value']) for k in HISTORY_KEYS] + ['; '.join(PR['flags']) or None]
                         for peer, PR in computed]
            med_row, readings = ['peer median (n)'], []
            for k in HISTORY_KEYS:
                med, n = medians[k]
                med_row.append(f'{_fmt(med)} ({n})' if med is not None else None)
                if med is not None and R[k]['value'] is not None:
                    readings.append(f'{LABELS[k]} {R[k]["value"]} vs peer median {_fmt(med)} ({n} peers)')
            res.table(f'{t}: valuation versus pre-declared peers (same close date, fundamentals known at T_c)',
                      ['company'] + [LABELS[k] for k in HISTORY_KEYS] + ['flags'],
                      [[t] + [_fmt(R[k]['value']) for k in HISTORY_KEYS] + ['; '.join(R['flags']) or None]]
                      + peer_rows + [med_row + [None]], scope=t, question=2,
                      note='Peers declared in config weekly.peers before any report. Ratios are not adjusted for '
                           'differences in growth, margins or accounting. A peer whose share count moved by 40% or '
                           'more in a year (possible split or large issuance; its market-cap ratios may mix pre- and '
                           'post-split figures) is shown but left out of the median'
                           + (f" (this week: {', '.join(excluded)})" if excluded else '') + '. Descriptive only.')
            if readings:
                res.add(conclude(t, 2, f'{t}: ' + '; '.join(readings) + '. Relative position only: no judgement of '
                                       'cheap or expensive.', [p_item] + ([item] if item else []), 'market_fact',
                                 reason_codes=['ESTIMATE']))

        # intrinsic-value scenarios
        stock = _closes(ctx, t)
        b, n_weeks = beta_of(stock, bench, dcf_settings['beta_weeks']) if bench else (None, 0)
        shares, basis, flags = shares_for(X, day)
        D = dcf(X, close, rf['value'] if rf else None, b, revenue_years_ago(ctx.sec, t, X), config, shares, basis,
                flags)
        if not D['scenarios']:
            reasons = D['reasons'] + ([rf_reason] if rf_reason and not rf else [])
            res.add(unavailable(t, 2, 'intrinsic-value scenarios (DCF)', 'NOT RELIABLE: ' + '; '.join(reasons)))
            continue
        a = D['assumptions']
        rows = [[name, s['growth_pct'], s['per_share'], s['vs_close_pct'], s['terminal_share_pct']]
                for name, s in D['scenarios'].items()]
        res.table(f'{t}: intrinsic-value scenarios (two-stage FCF model, estimate under stated assumptions)',
                  ['scenario', 'starting growth (%)', 'value per share (USD)', 'vs close (%)',
                   'terminal value share (%)'], rows, scope=t, question=2,
                  note=(f"Cost of equity {a['cost_of_equity_pct']}% = risk-free {a['risk_free_pct']}% (FRED DGS10) + "
                        f"beta {a['beta']} ({n_weeks} weekly returns vs {benchmark}) x ERP "
                        f"{a['equity_risk_premium_pct']}% (assumption); terminal growth {a['terminal_growth_pct']}% "
                        f"(assumption); {a['years']} years, growth fading linearly to terminal; base growth: "
                        f"{a['growth_basis']}. FCF {a['free_cash_flow_ttm']:,.0f} USD treated as free cash flow to "
                        'equity. Settings from config valuation.dcf' + (f" (defaults used for: {', '.join(defaulted)})"
                                                                      if defaulted else '')
                        + '. Sensitivity (base case, per share): ' + '; '.join(
                            f"ke {g['cost_of_equity_pct']}%: " + ', '.join(f'gT {k}% -> {v}' for k, v in
                                                                          g['per_share_by_terminal_growth'].items())
                            for g in D['sensitivity'])
                        + f". Market-implied starting growth (reverse DCF, same rates): "
                        f"{D.get('implied_growth_pct')}%."))
        base = D['scenarios']['base']
        statement = (f"{t}: under the stated assumptions (cost of equity {a['cost_of_equity_pct']}%, terminal growth "
                     f"{a['terminal_growth_pct']}%, base starting growth {a['base_growth_pct']}%), the two-stage FCF "
                     f"model gives {base['per_share']} USD per share in the base case "
                     f"({D['scenarios']['bear']['per_share']} bear, {D['scenarios']['bull']['per_share']} bull) "
                     f"against a close of {close:.2f}; the price is consistent with a starting growth of "
                     f"{D.get('implied_growth_pct')}% under the same rates. Reliability {D['reliability']}"
                     + (': ' + '; '.join(D['flags']) if D['flags'] else '') + '. An estimate under assumptions, not a '
                     'fair value or a price target.')
        items = [p_item] + ([item] if item else []) + ([rf_item] if rf_item else [])
        res.add(conclude(t, 2, statement, items, 'model_output', reason_codes=['ESTIMATE']))
        if b is None:
            res.add(unavailable(t, 2, 'beta', f'fewer than {MIN_BETA_WEEKS} common weekly returns'))
    res.notes.append('Valuation figures are descriptive. Ratios with a near-zero or negative denominator are shown as '
                     'not meaningful; intrinsic-value scenarios are estimates under configurable assumptions and are '
                     'never presented as fair values.')
    return res
