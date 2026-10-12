#!/usr/bin/env python3
"""
Weekly report section 'positioning' - Q1 (market-wide positioning) and Q8 (company short interest and option
implied volatility) (phase P4.0).

Data: observations stored by `python main.py collect` (src/external_sources.py); this section downloads nothing.
Every value is read as known at an instant T: COALESCE(published_at, retrieved_at) <= T (Database.series).

Overall (Q1)
  CFTC Commitments of Traders (rank 1): net positions (long - short, contracts) by trader group for the
  pre-declared contracts (external_sources.COT_CONTRACTS): the latest report known at T_c vs the latest known
  at T_p (a report dated Tuesday is released Friday 15:30 New York). Change also in % of open interest.
  Cboe daily put/call ratios (rank 1; Cboe-listed volume only, not the whole market): mean of the sessions of
  the week (s_-4 .. s_0) known at T_c vs the mean of the previous week (s_-9 .. s_-5) known at T_p.
Company (Q8)
  FINRA equity short interest (rank 1): latest settlement known at T_c vs the latest known at T_p (shares and
  days to cover); a revised row is dated by its retrieval.
  Option snapshot (yfinance, rank 2, unofficial): ATM implied volatility (expiry nearest 30 days) and put/call
  open-interest ratio (expiries within 60 days), from the newest snapshot RETRIEVED at or before the instant
  (snapshots carry no publication time) for a session <= s_0, at T_c vs at T_p.

Rule (pre-declared, heuristic, never validated): a change is "large" when |change| > 1 sample standard
deviation of the changes between consecutive observations in the history known at T_p (COT reports,
short-interest settlements, weekly means of put/call ratios), with at least MIN_CHANGES changes; otherwise
the rule is "not assessed". Positioning describes who holds what: no price direction is implied, and reading a
change as a change in risk is an interpretation (no validated risk model).

Levels: CFTC, Cboe and FINRA measurements are official_fact; option snapshots are market_fact (single rank-2
source: UNCERTAIN by rule); summaries using the rule are interpretations (HEURISTIC_THRESHOLD).
"""

from statistics import mean

from ...external_sources import CBOE_RATIOS, COT_CONTRACTS, COT_GROUPS
from ..core import SectionResult, conclude, evidence, unavailable
from .market import _std, fresh_flag, thresholds_version

NAME = 'positioning'
QUESTIONS = [1, 8]
Q_MARKET, Q_COMPANY = 1, 8
MIN_CHANGES = 26
COT_SOURCE, CBOE_SOURCE, FINRA_SOURCE, YF_SOURCE = 'CFTC', 'Cboe', 'FINRA', 'yfinance'
GROUP_LABELS = {'leveraged_funds_net': 'leveraged funds', 'asset_managers_net': 'asset managers',
                'dealers_net': 'dealers', 'managed_money_net': 'managed money',
                'producers_net': 'producers / merchants'}
CBOE_LABELS = {metric: name.replace(' PUT/CALL RATIO', '').lower() for name, metric in CBOE_RATIOS.items()}
COLLECT_HINT = '`python main.py collect` stores these data; run it daily'


# ---------------------------------------------------------------- helpers

def _point(db, entity, metric, source, known_at, end=None):
    """(as_of, row) of the latest observation known at `known_at` (as_of <= end), or None."""
    rows = [(d, r) for d, r in db.series(entity, metric, known_at=known_at, source=source, end=end)
            if r['value'] is not None]
    return rows[-1] if rows else None


def _changes(db, entity, metric, source, known_at):
    """Changes between consecutive observations as known at `known_at`."""
    values = [r['value'] for _, r in db.series(entity, metric, known_at=known_at, source=source)
              if r['value'] is not None]
    return [b - a for a, b in zip(values, values[1:])]


def _rule(delta, changes):
    """(sd, large): large is None when the history is shorter than MIN_CHANGES or delta is None."""
    sd = _std(changes) if len(changes) >= MIN_CHANGES else None
    return sd, (None if sd is None or delta is None else abs(delta) > sd)


def _item(ctx, source, rank, fact, as_of, row, cadence):
    return evidence(ctx.tm, source, rank, fact, as_of=as_of, published_at=row['published_at'],
                    retrieved_at=row['retrieved_at'], fetch_id=row['fetch_id'],
                    fresh=fresh_flag(ctx, as_of, cadence), basis=row['published_at_basis'])


def _r(x, digits=4):
    return None if x is None else round(x, digits)


def _verdict(large):
    return 'not assessed' if large is None else 'yes' if large else 'no'


# ---------------------------------------------------------------- CFTC COT (Q1)

def _cot(ctx, res):
    tm, db = ctx.tm, ctx.db
    rows, items, large, assessed, not_assessed = [], [], [], [], []
    for code, (name, dataset) in COT_CONTRACTS.items():
        entity = f'COT:{code}'
        oi = _point(db, entity, 'open_interest', COT_SOURCE, tm.cutoff)
        if oi is None:
            res.add(unavailable('overall', Q_MARKET, f'CFTC COT, {name}',
                                f'no report known at the cutoff; {COLLECT_HINT}'))
            continue
        parts, contract_items = [], []
        for metric, _, _ in COT_GROUPS[dataset]:
            now = _point(db, entity, metric, COT_SOURCE, tm.cutoff)
            if now is None:
                continue
            prev = _point(db, entity, metric, COT_SOURCE, tm.previous_cutoff)
            (d_c, r_c), (d_p, r_p) = now, prev or (None, None)
            new = prev is not None and d_c != d_p
            delta = r_c['value'] - r_p['value'] if new else None
            changes = _changes(db, entity, metric, COT_SOURCE, tm.previous_cutoff)
            sd, big = _rule(delta, changes)
            share = delta / oi[1]['value'] if delta is not None and oi[1]['value'] else None
            label = GROUP_LABELS[metric]
            rows.append([name, label, d_p, r_p and r_p['value'], d_c, r_c['value'], delta,
                         _r(None if share is None else 100 * share, 2), _r(sd, 1), len(changes),
                         _verdict(big) if new else 'no new report'])
            if new:
                (assessed if big is not None else not_assessed).append(f'{name} {label}')
                if big:
                    large.append(f'{name} {label} ({delta:+,.0f})')
                parts.append(f'{label} {r_c["value"]:+,.0f} (change {delta:+,.0f}'
                             + (f', {100 * share:+.2f}% of open interest' if share is not None else '') + ')')
            else:
                parts.append(f'{label} {r_c["value"]:+,.0f}')
            contract_items.append(_item(ctx, COT_SOURCE, 1, f'COT {name} {label} net {r_c["value"]:+,.0f} '
                                                            f'(report {d_c})', d_c, r_c, 'weekly'))
        if not contract_items:
            continue
        d_c = oi[0]
        prev_oi = _point(db, entity, 'open_interest', COT_SOURCE, tm.previous_cutoff)
        if prev_oi is None:
            head = f'CFTC COT, {name}, report of {d_c} (no report known at T_p): net positions'
        elif prev_oi[0] == d_c:
            head = f'CFTC COT, {name}: no new report between T_p and T_c (latest {d_c}): net positions'
        else:
            head = f'CFTC COT, {name}, report of {d_c} vs {prev_oi[0]}: net positions'
        res.add(conclude('overall', Q_MARKET, f'{head} {"; ".join(parts)} contracts (CFTC, rank 1).',
                         contract_items, 'official_fact'))
        items += contract_items
    res.table('CFTC Commitments of Traders — net positions by trader group', [
        'contract', 'group', 'report (known at T_p)', 'net (T_p)', 'report (known at T_c)', 'net (T_c)',
        'change (contracts)', 'change, % of open interest', '1 sd of past report-to-report changes',
        'changes in history (known at T_p)', 'large (|change| > 1 sd)'], rows, question=Q_MARKET,
        note='CFTC (rank 1): TFF report for financial futures (leveraged funds, asset managers, dealers), '
             'disaggregated report for commodities (managed money, producers / merchants); net = long - short '
             'contracts. Released Friday 15:30 New York for the Tuesday report date. Rule (heuristic, never '
             'validated): large when |change| > 1 sample sd of past report-to-report changes known at T_p, at least '
             f'{MIN_CHANGES} changes. Positioning describes holdings: no price direction is implied.')
    if items and (assessed or not_assessed):
        missing = (f'; not assessed (history < {MIN_CHANGES} changes): {", ".join(not_assessed)}' if not_assessed
                   else '')
        head = (f'Large week-to-week changes in CFTC net positions: {", ".join(large)}' if large
                else 'No assessed CFTC net position changed by more than 1 sd of its past changes')
        res.add(conclude('overall', Q_MARKET, f'{head} ({len(assessed)} group positions assessed{missing}). Reading '
                                              'this as a shift in market risk or sentiment is an interpretation.',
                         items, 'interpretation',
                         reason_codes=['HEURISTIC_THRESHOLD'] + (['PARTIAL_COVERAGE'] if not_assessed else [])))


# ---------------------------------------------------------------- Cboe put/call (Q1)

def _week_mean(db, metric, sessions, known_at):
    """(mean, [(session, row)]) of the sessions with a value known at `known_at`."""
    if not sessions:
        return None, []
    values = dict(db.series('CBOE', metric, known_at=known_at, source=CBOE_SOURCE, start=sessions[0],
                            end=sessions[-1]))
    got = [(s, values[s]) for s in sessions if s in values and values[s]['value'] is not None]
    return (mean(r['value'] for _, r in got) if got else None), got


def _weekly_mean_changes(ctx, metric):
    """Changes between consecutive complete 5-session weekly means before T_p, as known at T_p."""
    tm, sessions, means = ctx.tm, ctx.tm.sessions, []
    k = 1
    while len(sessions) - 5 * (k + 1) >= 0:
        window = sessions[len(sessions) - 5 * (k + 1):len(sessions) - 5 * k]
        m, got = _week_mean(ctx.db, metric, window, tm.previous_cutoff)
        if len(got) != len(window):
            break                                     # history starts (or has a gap) here
        means.append(m)
        k += 1
    means.reverse()
    return [b - a for a, b in zip(means, means[1:])]


def _cboe(ctx, res):
    tm = ctx.tm
    rows, parts, items, partial, large = [], [], [], False, []
    for metric, label in CBOE_LABELS.items():
        now, got_c = _week_mean(ctx.db, metric, tm.week, tm.cutoff)
        prev, got_p = _week_mean(ctx.db, metric, tm.previous_week, tm.previous_cutoff)
        if now is None:
            rows.append([label, _r(prev), len(got_p), None, 0, None, None, 0, 'not assessed'])
            continue
        partial = partial or len(got_c) < len(tm.week) or (prev is not None and len(got_p) < len(tm.previous_week))
        delta = now - prev if prev is not None else None
        changes = _weekly_mean_changes(ctx, metric)
        sd, big = _rule(delta, changes)
        rows.append([label, _r(prev), len(got_p), _r(now), len(got_c), _r(delta), _r(sd), len(changes),
                     _verdict(big)])
        if big:
            large.append(label)
        parts.append(f'{label} {_r(prev, 3) if prev is not None else "N/A"} -> {_r(now, 3)}')
        if metric == 'put_call_total':
            s, row = got_c[-1]
            items.append(_item(ctx, CBOE_SOURCE, 1, f'Cboe total put/call ratio {s} = {row["value"]}', s, row,
                               'daily_market'))
    res.table('Cboe put/call ratios — weekly means', [
        'ratio', 'previous week mean (known at T_p)', 'sessions (T_p)', 'week mean (known at T_c)', 'sessions (T_c)',
        'change', '1 sd of past week-to-week changes', 'changes in history (known at T_p)', 'large (|change| > 1 sd)'],
        rows, question=Q_MARKET,
        note='Cboe (rank 1) end-of-day statistics, Cboe-listed volume only (not the whole options market). Week = the '
             f'sessions s_-4 .. s_0 ({", ".join(tm.week)}); previous week s_-9 .. s_-5. Rule as for the COT table, on '
             f'complete weekly means (at least {MIN_CHANGES} changes).')
    if not items:
        res.add(unavailable('overall', Q_MARKET, 'Cboe put/call ratios for the week',
                            f'no Cboe daily statistics known at the cutoff for the week sessions; {COLLECT_HINT}'))
        return
    res.add(conclude('overall', Q_MARKET, 'Cboe put/call ratios, mean of the week known at T_c vs the previous week '
                                          f'known at T_p (Cboe-listed volume only): {"; ".join(parts)} (Cboe, rank 1).'
                                          + (f' Changes larger than 1 sd of past weekly changes: {", ".join(large)}.'
                                             if large else ''),
                     items, 'official_fact', reason_codes=['PARTIAL_COVERAGE'] if partial else []))


# ---------------------------------------------------------------- FINRA short interest and options (Q8)

def _short_interest(ctx, res, ticker, rows):
    tm, db = ctx.tm, ctx.db
    now = _point(db, ticker, 'short_interest_shares', FINRA_SOURCE, tm.cutoff)
    if now is None:
        rows.append([ticker, 'short interest (FINRA)', None, None, None, None, None, 'not assessed'])
        res.add(unavailable(ticker, Q_COMPANY, 'short interest (FINRA)',
                            f'no FINRA settlement known at the cutoff; {COLLECT_HINT}'))
        return None, None
    prev = _point(db, ticker, 'short_interest_shares', FINRA_SOURCE, tm.previous_cutoff)
    (d_c, r_c), (d_p, r_p) = now, prev or (None, None)
    dtc = _point(db, ticker, 'short_interest_days_to_cover', FINRA_SOURCE, tm.cutoff, end=d_c)
    dtc_text = f' ({dtc[1]["value"]:g} days to cover)' if dtc and dtc[0] == d_c else ''
    new = prev is not None and d_c != d_p
    delta = r_c['value'] - r_p['value'] if new else None
    sd, big = _rule(delta, _changes(db, ticker, 'short_interest_shares', FINRA_SOURCE, tm.previous_cutoff))
    rel = delta / r_p['value'] if delta is not None and r_p['value'] else None
    rows.append([ticker, 'short interest (FINRA), shares', f'{d_p}: {r_p["value"]:,.0f}' if r_p else None,
                 f'{d_c}: {r_c["value"]:,.0f}{dtc_text}', delta, _r(None if rel is None else 100 * rel, 2), _r(sd, 0),
                 _verdict(big) if new else 'no new settlement'])
    item = _item(ctx, FINRA_SOURCE, 1, f'{ticker} short interest {r_c["value"]:,.0f} shares, settlement {d_c}', d_c,
                 r_c, 'semi_monthly')
    if prev is None:
        text = (f'{ticker}: FINRA short interest {r_c["value"]:,.0f} shares{dtc_text} at settlement {d_c} (no '
                'settlement known at T_p)')
    elif not new:
        text = (f'{ticker}: no new FINRA short-interest settlement published between T_p and T_c (latest {d_c}: '
                f'{r_c["value"]:,.0f} shares{dtc_text})')
    else:
        rule = ('rule not assessed' if big is None else
                f'{"larger" if big else "not larger"} than 1 sd of past settlement-to-settlement changes ({sd:,.0f})')
        text = (f'{ticker}: FINRA short interest {r_c["value"]:,.0f} shares{dtc_text} at settlement {d_c} vs '
                f'{r_p["value"]:,.0f} at {d_p}: change {delta:+,.0f} ({100 * rel:+.1f}%); {rule}')
    res.add(conclude(ticker, Q_COMPANY, text + ' (FINRA, rank 1).', [item], 'official_fact'))
    return big, item


IV_PERCENTILE_MIN = 252          # about one year of daily snapshots


def _options(ctx, res, ticker, rows):
    tm, db = ctx.tm, ctx.db
    now = _point(db, ticker, 'opt_atm_iv_30d', YF_SOURCE, tm.cutoff, end=tm.s0)
    if now is None:
        rows.append([ticker, 'ATM implied volatility (yfinance)', None, None, None, None, None, 'not assessed'])
        res.add(unavailable(ticker, Q_COMPANY, 'option implied volatility (yfinance snapshot)',
                            'no option snapshot retrieved at or before the cutoff (snapshots carry no publication '
                            f'time, so only one retrieved before the cutoff is admissible); {COLLECT_HINT}'))
        return
    prev = _point(db, ticker, 'opt_atm_iv_30d', YF_SOURCE, tm.previous_cutoff, end=tm.s0)
    (d_c, r_c), (d_p, r_p) = now, prev or (None, None)
    pc = _point(db, ticker, 'opt_put_call_oi_60d', YF_SOURCE, tm.cutoff, end=tm.s0)
    pc_text = f'; put/call open interest (60 days) {pc[1]["value"]:.2f}' if pc and pc[0] == d_c else ''
    delta = r_c['value'] - r_p['value'] if prev is not None and d_c != d_p else None
    rows.append([ticker, 'ATM implied volatility (yfinance), annualised',
                 f'{d_p}: {r_p["value"]:.1%}' if r_p else None, f'{d_c}: {r_c["value"]:.1%}',
                 _r(None if delta is None else 100 * delta, 1), None, None, 'not assessed (no history rule)'])
    item = _item(ctx, YF_SOURCE, 2, f'{ticker} ATM implied volatility {r_c["value"]:.1%} (session {d_c})', d_c, r_c,
                 'daily_market')
    text = (f'{ticker}: ATM implied volatility (expiry nearest 30 days) {r_c["value"]:.1%} in the yfinance option '
            f'snapshot of session {d_c}{pc_text}'
            + (f'; {r_p["value"]:.1%} in the snapshot known at T_p ({d_p}), change {100 * delta:+.1f} points'
               if delta is not None else '; no other snapshot known at T_p'))
    res.add(conclude(ticker, Q_COMPANY, text + ' (unofficial source, rank 2).', [item], 'market_fact'))
    # master mission P2: skew, term structure and IV percentile (same snapshot session only)
    extra = []
    for metric, label in (('opt_skew_90_110_30d', 'skew (put IV at 90% minus call IV at 110% of spot, ~30 days)'),
                          ('opt_term_slope_60d', 'term slope (ATM IV of the longest minus the shortest expiry, 7-60 days)')):
        pt = _point(db, ticker, metric, YF_SOURCE, tm.cutoff, end=tm.s0)
        if pt and pt[0] == d_c:
            rows.append([ticker, label, None, f'{d_c}: {100 * pt[1]["value"]:+.1f} points', None, None, None,
                         'descriptive'])
            extra.append(f'{label} {100 * pt[1]["value"]:+.1f} volatility points')
    history = [r['value'] for _, r in db.series(ticker, 'opt_atm_iv_30d', known_at=tm.cutoff, source=YF_SOURCE)
               if r.get('value') is not None]
    if len(history) >= IV_PERCENTILE_MIN:
        pct = (sum(v < r_c['value'] for v in history) + 0.5 * sum(v == r_c['value'] for v in history)) / len(history)
        extra.append(f'ATM IV at the {100 * pct:.0f}th percentile of {len(history)} snapshots')
    else:
        res.add(unavailable(ticker, Q_COMPANY, 'implied volatility rank / percentile',
                            f'insufficient history: {len(history)} daily option snapshot(s) known at the cutoff, at '
                            f'least {IV_PERCENTILE_MIN} needed (snapshots are collected daily since 2026-10; no '
                            'historical option data source is configured)'))
    if extra:
        res.add(conclude(ticker, Q_COMPANY, f'{ticker}: in the same snapshot (session {d_c}): ' + '; '.join(extra)
                         + '. Descriptive (unofficial source, rank 2).', [item], 'market_fact'))


# ---------------------------------------------------------------- section

def build(ctx, tickers=None):
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    _cot(ctx, res)
    _cboe(ctx, res)
    rows, large = [], {}
    for t in (tickers or ctx.universe):
        big, item = _short_interest(ctx, res, t, rows)
        if big:
            large[t] = item
        _options(ctx, res, t, rows)
    res.table('Company positioning — short interest (FINRA) and option snapshots (yfinance)', [
        'company', 'measure', 'known at T_p', 'known at T_c', 'change', 'change %', '1 sd of past changes',
        'large (|change| > 1 sd)'], rows, question=Q_COMPANY,
        note='FINRA short interest (rank 1): twice-monthly settlement dates, disseminated about 7 business days later '
             '(conservative publication date). Option snapshots (yfinance, rank 2, unofficial) have no publication '
             'time: only snapshots retrieved before the cutoff are used; implied volatility changes have no '
             'pre-declared rule. A large change in short interest is not a forecast and not a risk score.')
    if large:
        res.add(conclude('overall', Q_COMPANY, 'Short interest changed by more than 1 sd of its past settlement-to-'
                                               f'settlement changes for: {", ".join(large)}. Whether this raises risk '
                                               'is an interpretation (no validated risk model).',
                         list(large.values()), 'interpretation', reason_codes=['HEURISTIC_THRESHOLD']))
    res.notes.append(f'T_p = {tm.previous_cutoff}, T_c = {tm.cutoff}; thresholds {thresholds_version(ctx)} (the '
                     f'positioning rule is the 1 sd rule above, at least {MIN_CHANGES} past changes). Data from '
                     '`python main.py collect`; nothing is downloaded by this section. Timing only: no causal link and '
                     'no prediction is asserted.')
    return res
