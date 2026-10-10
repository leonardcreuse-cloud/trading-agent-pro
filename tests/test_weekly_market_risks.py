"""Weekly report sections 'market' (Q1) and 'risks' (Q8) - offline tests on a fake context.

All prices, filings, FRED values and Form 4 rows below are SYNTHETIC: they exist only to check the
calculation, point-in-time and evidence-level logic and never reach a report.
"""

import json
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.common import end_of_us_trading_day_utc, to_utc_iso
from src.database import freshness
from src.weekly.core import STRONG, UNAVAILABLE, UNCERTAIN, LookAheadError, TimeModel
from src.weekly.sections import market, risks

ALL_SESSIONS = [d.date().isoformat() for d in pd.bdate_range(end='2026-10-09', periods=900)]
CUTOFF = '2026-10-07T12:00:00+00:00'          # s_0 = 2026-10-06, T_c = 2026-10-07T05:00Z
RETRIEVED = '2026-10-07T13:00:00+00:00'       # all fake fetches were made after the cutoff
THRESHOLDS = {'abs_excess_return_z': 2.0, 'volume_ratio': 2.0, 'sigma20_change_rel': 0.25,
              'drawdown_new_low_pct': -20.0}
WEEKLY = {'benchmark': 'SPY', 'sector_etf': {'AAA': 'XLK', 'BBB': 'XLB'}, 'thresholds_version': 'test-v1',
          'thresholds': dict(THRESHOLDS)}
CAUSAL = ('because', 'due to', 'drove', 'driven by', 'on the back of', 'caused')


# ---------------------------------------------------------------- fake context

def frame(closes, volumes=None, close_raw=None):
    idx = pd.to_datetime(ALL_SESSIONS[:len(closes)])
    return pd.DataFrame({'close': closes, 'close_raw': close_raw if close_raw is not None else closes,
                         'volume': volumes if volumes is not None else [1_000_000.0] * len(closes)}, index=idx)


def ok_prices(df, fetch_id=1):
    return {'status': 'OK', 'frame': df, 'fetch': {'fetch_id': fetch_id, 'retrieved_at': RETRIEVED}, 'reason': None}


class FakeDB:
    def __init__(self, events=None, xbrl=None):
        self._events = events or {}
        self._xbrl = xbrl or {}

    def events(self, entity, metric, published_from=None, published_to=None, source=None):
        lo, hi = to_utc_iso(published_from), to_utc_iso(published_to)
        rows = [r for r in self._events.get((entity, metric), [])
                if (lo is None or r['available_at'] > lo) and (hi is None or r['available_at'] <= hi)]
        return sorted(rows, key=lambda r: r['available_at'])

    def series(self, entity, metric, known_at=None, source=None, strict_vintage=False, start=None, end=None):
        """Like Database.series: one version per as_of_date, the latest published at known_at."""
        k = to_utc_iso(known_at)
        chosen = {}
        for d, r in sorted(self._xbrl.get((entity, metric), []), key=lambda x: x[1]['published_at']):
            if (k is None or r['published_at'] <= k) and (start is None or d >= start) and (end is None or d <= end):
                chosen[d] = dict(r)
        return sorted(chosen.items())


class StrictSEC:
    """Any use of the SEC client (which could download from sec.gov) fails the test."""

    def __getattr__(self, name):
        raise AssertionError(f'the weekly section touched the live SEC client (attribute {name!r})')


class FakeCtx:
    def __init__(self, prices=None, fred=None, fred_status=None, filings=None, sec=None, db=None,
                 universe=('AAA',), weekly=None):
        self.tm = TimeModel(ALL_SESSIONS, CUTOFF, CUTOFF)
        self._prices = prices or {}
        self._fred = fred or {}            # sid -> [(obs_date, value, published_at)] (all vintages)
        self._fred_status = fred_status or {}
        self._filings = filings or {}
        self.sec = sec or StrictSEC()
        self.db = db or FakeDB()
        self.universe = list(universe)
        self.weekly = weekly or json.loads(json.dumps(WEEKLY))
        self.value_at_calls = []

    def prices(self, ticker):
        return self._prices.get(ticker) or {'status': UNAVAILABLE, 'frame': None, 'fetch': None,
                                            'reason': 'yfinance returned no data'}

    def fred(self, sid):
        if sid in self._fred_status:
            return {'status': UNAVAILABLE, 'fetch': None, 'reason': self._fred_status[sid]}
        if sid not in self._fred:
            return {'status': UNAVAILABLE, 'fetch': None, 'reason': 'FRED HTTP 400: Bad Request'}
        return {'status': 'OK', 'fetch': {'fetch_id': 7, 'retrieved_at': RETRIEVED}, 'reason': None}

    def _known(self, sid, instant, start=None):
        t = to_utc_iso(instant)
        best = {}
        for d, v, pub in sorted(self._fred.get(sid, []), key=lambda x: x[2]):
            if pub <= t and (start is None or d >= start):
                best[d] = (v, pub)
        return sorted(best.items())

    def value_at(self, sid, instant):
        self.value_at_calls.append((sid, instant))
        rows = self._known(sid, instant)
        if not rows:
            return None
        d, (v, pub) = rows[-1]
        return d, v, pub

    def series_at(self, sid, instant, start=None):
        return [(d, v) for d, (v, _) in self._known(sid, instant, start)]

    def first_release(self, sid):
        return {}

    def filings(self, ticker):
        return self._filings.get(ticker) or {'status': UNAVAILABLE, 'filings': [], 'fetch': None,
                                             'reason': 'CIK not found for test'}

    def freshness(self, as_of, cadence):
        return freshness(as_of, cadence, now=datetime.fromisoformat(self.tm.cutoff))


def n_elig():
    return ALL_SESSIONS.index('2026-10-06') + 1


def week_pattern_closes(current=0.10, past=0.01, after=1e6):
    """Adjusted closes whose non-overlapping 5-session returns ending s_0 - 5k are known exactly."""
    n = n_elig()
    closes, c = [], 100.0
    for i in range(n):
        w = (n - 1 - i) // 5
        r = current if w == 0 else (past if w % 2 else -past)
        c *= (1 + r) ** 0.2
        closes.append(c)
    return closes + [after] * (len(ALL_SESSIONS) - n)          # absurd bars AFTER s_0 (look-ahead bait)


def flat(level=100.0, last_week=None):
    n = n_elig()
    closes = [level] * n
    if last_week is not None:
        for k, i in enumerate(range(n - 5, n), 1):
            closes[i] = level * (1 + last_week) ** (k / 5)
    return closes + [level * 50] * (len(ALL_SESSIONS) - n)


def sp500_vintages(values, same_day=False):
    """FRED-like vintages: the value of day d is first published the next day (or the same day)."""
    out = []
    for d, v in zip(ALL_SESSIONS, values):
        day = date.fromisoformat(d) + timedelta(days=0 if same_day else 1)
        out.append((d, v, end_of_us_trading_day_utc(day)))
    return out


def market_ctx(**kw):
    vols = [1_000_000.0] * n_elig() + [1e12] * (len(ALL_SESSIONS) - n_elig())
    for i in range(n_elig() - 5, n_elig()):
        vols[i] = 3_000_000.0
    prices = {'SPY': ok_prices(frame(flat()), 1), 'AAA': ok_prices(frame(week_pattern_closes(), vols), 2),
              'XLK': ok_prices(frame(flat(last_week=0.02)), 3)}
    prices.update(kw.pop('prices', {}))
    fred = {'SP500': sp500_vintages(flat(5000.0))}
    fred.update(kw.pop('fred', {}))
    return FakeCtx(prices=prices, fred=fred, **kw)


def by_scope(records, scope):
    return [r for r in records if r['scope'] == scope]


# ---------------------------------------------------------------- market (Q1)

def test_market_values_on_synthetic_data_and_no_bar_after_s0():
    out = market.build(market_ctx()).as_dict()
    assert out['name'] == 'market' and out['questions'] == [1]
    week = next(t for t in out['tables'] if t['title'] == 'AAA — week in figures')
    row = dict(zip(week['columns'], week['rows'][0]))
    assert row['weekly return %'] == pytest.approx(10.0)            # bars after s_0 (1e6) are ignored
    assert row['SPY weekly return %'] == pytest.approx(0.0)
    assert row['excess vs SPY pp'] == pytest.approx(10.0)
    assert row['sector ETF weekly return %'] == pytest.approx(2.0)
    assert row['excess vs sector ETF pp'] == pytest.approx(8.0)
    assert row['weekly volume / 20-week mean'] == pytest.approx(3.0)
    z = 0.10 / (0.01 * math.sqrt(156 / 155))                       # 78 x +1 %, 78 x -1 %: mean 0
    assert row['excess-return z (156 weeks)'] == pytest.approx(round(z, 2))
    assert row['unusual (|z| >= 2.0)'] == 'yes'
    timeline = next(t for t in out['tables'] if t['title'] == 'AAA — session timeline')
    assert [r[0] for r in timeline['rows']] == ['2026-09-30', '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06']
    assert all(r[2] == pytest.approx(100 * (1.1 ** 0.2 - 1), abs=1e-2) and r[3] == pytest.approx(3.0)
               for r in timeline['rows'])
    overall = next(t for t in out['tables'] if t['title'] == 'Market week — overall')
    assert overall['rows'][1][1] == pytest.approx(10.0)             # equal weight of a 1-ticker universe
    assert 'test-v1' in week['note'] and 'test-v1' in overall['note']


def test_market_levels_single_rank2_source_and_unusual_is_interpretation():
    out = market.build(market_ctx()).as_dict()
    aaa = by_scope(out['conclusions'], 'AAA')
    facts = [c for c in aaa if c['kind'] == 'market_fact']
    assert facts and all(c['level'] == UNCERTAIN and 'SINGLE_RANK2_SOURCE' in c['reason_codes'] for c in facts)
    unusual = [c for c in aaa if c['kind'] == 'interpretation']
    assert len(unusual) == 1 and unusual[0]['level'] == UNCERTAIN
    assert {'HEURISTIC_THRESHOLD', 'INTERPRETIVE'} <= set(unusual[0]['reason_codes'])
    assert all(c['kind'] != 'system_output' for c in out['conclusions'])
    for c in out['conclusions']:
        assert not any(w in c['statement'].lower() for w in CAUSAL)
        for e in c['evidence']:
            assert e['published_at'] <= '2026-10-07T05:00:00+00:00'
            assert e['source'] in ('yfinance', 'FRED') and e['rank'] == (2 if e['source'] == 'yfinance' else 1)


def test_market_sp500_lagging_one_day_keeps_the_week_uncertain():
    ctx = market_ctx()
    out = market.build(ctx).as_dict()
    spy = next(c for c in out['conclusions'] if c['statement'].startswith('SPY weekly return'))
    assert spy['level'] == UNCERTAIN and spy['reason_codes'] == ['SINGLE_RANK2_SOURCE']
    # FRED's s_0 value is published after T_c: the comparison runs over the latest window known at T_c
    aligned = next(c for c in out['conclusions'] if 'latest FRED SP500 window' in c['statement'])
    assert '2026-09-28 -> 2026-10-05' in aligned['statement'] and aligned['level'] == STRONG
    assert all(call[1] <= ctx.tm.cutoff for call in ctx.value_at_calls)
    check = next(t for t in out['tables'] if t['title'] == 'SPY vs FRED SP500 cross-check')
    assert check['rows'][0][1:3] == ['2026-09-28', '2026-10-05'] and 'not the week' in check['rows'][0][-1]


def test_market_exact_cross_check_agree_and_disagree():
    spy = [100 * 1.001 ** i for i in range(len(ALL_SESSIONS))]
    agree = market_ctx(prices={'SPY': ok_prices(frame(spy), 1)},
                       fred={'SP500': sp500_vintages([5000 * 1.001 ** i for i in range(len(ALL_SESSIONS))],
                                                     same_day=True)})
    c = next(c for c in market.build(agree).as_dict()['conclusions'] if c['statement'].startswith('SPY weekly'))
    assert c['level'] == STRONG and {e['source'] for e in c['evidence']} == {'yfinance', 'FRED'}
    differ = market_ctx(prices={'SPY': ok_prices(frame(spy), 1)},
                        fred={'SP500': sp500_vintages([5000 * 1.003 ** i for i in range(len(ALL_SESSIONS))],
                                                      same_day=True)})
    c = next(c for c in market.build(differ).as_dict()['conclusions'] if c['statement'].startswith('SPY weekly'))
    assert c['level'] == UNCERTAIN and 'CONFLICTING_SOURCES' in c['reason_codes']


def test_market_fred_revision_published_after_cutoff_is_not_used():
    vint = sp500_vintages(flat(5000.0), same_day=True)
    vint.append(('2026-10-06', 9999.0, '2026-10-08T05:00:00+00:00'))     # revision after T_c
    out = market.build(market_ctx(fred={'SP500': vint})).as_dict()
    check = next(t for t in out['tables'] if t['title'] == 'SPY vs FRED SP500 cross-check')
    assert check['rows'][0][4] == pytest.approx(0.0)                      # 5000 -> 5000, not 9999


def test_market_look_ahead_from_a_broken_accessor_raises():
    class Leaky(FakeCtx):
        def value_at(self, sid, instant):                                   # ignores the instant
            return '2026-10-06', 5000.0, '2026-10-08T05:00:00+00:00'
    base = market_ctx()
    ctx = Leaky(prices=base._prices, fred=base._fred)
    with pytest.raises(LookAheadError):
        market.build(ctx)


def test_market_missing_data_is_data_unavailable_with_reason():
    closes = week_pattern_closes()
    df = frame(closes)
    df = df.drop(pd.Timestamp('2026-10-06'))                               # no bar for s_0
    ctx = market_ctx(prices={'AAA': ok_prices(df, 2), 'XLK': {'status': UNAVAILABLE, 'frame': None, 'fetch': None,
                                                             'reason': 'yfinance returned no data'}},
                     fred_status={'SP500': 'FRED_API_KEY not set'}, universe=('AAA', 'ZZZ'))
    out = market.build(ctx).as_dict()
    items = {(u['scope'], u['item']): u['reason'] for u in out['unavailable']}
    assert 'not filled' in items[('AAA', 'weekly return')] and '2026-10-06' in items[('AAA', 'weekly return')]
    assert 'yfinance returned no data' in items[('AAA', 'excess return vs sector ETF XLK')]
    assert 'yfinance' in items[('ZZZ', 'weekly price facts')]
    assert items[('overall', 'FRED SP500 cross-check')] == 'FRED SP500: FRED_API_KEY not set'
    spy = next(c for c in out['conclusions'] if c['statement'].startswith('SPY weekly return'))
    assert 'cross-check unavailable' in spy['statement'] and spy['level'] == UNCERTAIN
    assert items[('overall', 'equal-weight universe weekly return')]
    week = next(t for t in out['tables'] if t['title'] == 'AAA — week in figures')
    assert week['rows'][0][1] is None                                      # never a placeholder number
    timeline = next(t for t in out['tables'] if t['title'] == 'AAA — session timeline')
    assert timeline['rows'][-1][1:] == [None, None, None]


# ---------------------------------------------------------------- risks (Q8)

T_C, T_P = '2026-10-07T05:00:00+00:00', '2026-09-30T05:00:00+00:00'


def risky_closes():
    """Calm history (+-1 % per day), then a 30 % fall over the last 5 sessions."""
    n = n_elig()
    closes, c = [], 100.0
    for i in range(n):
        c *= 0.7 ** 0.2 if i >= n - 5 else math.exp(0.01 if i % 2 else -0.01)
        closes.append(c)
    return closes + [1e6] * (len(ALL_SESSIONS) - n)


def form4(acc, code, value, owners, plan, available_at):
    return {'as_of_date': available_at[:10], 'available_at': available_at,
            'value_text': json.dumps({'accession': acc, 'code': code, 'value_usd': value, 'owners': owners,
                                      'rule_10b5_1': plan})}


STALE_RETRIEVAL = '2026-10-06T12:00:00+00:00'  # after T_p, before T_c


def feed(rows, after_cutoff=True):
    return {'status': 'OK', 'filings': rows,
            'fetch': {'fetch_id': 5, 'retrieved_at': RETRIEVED if after_cutoff else STALE_RETRIEVAL},
            'retrieved_after_cutoff': after_cutoff, 'reason': None}


def filing(form, published, items=(), acc=None, report=None):
    return {'form': form, 'filing_date': published[:10], 'report_date': report,
            'accession_number': acc or f'acc-{form}-{published}',
            'published_at': published, 'published_at_basis': 'test', 'items': list(items)}


def xbrl(versions, ticker='AAA'):
    """[(published_at, balance_sheet_date, equity, {debt_tag: value})] -> FakeDB xbrl rows (stored facts)."""
    out = {}
    for k, (pub, bsd, equity, debts) in enumerate(versions):
        for tag, v in [('StockholdersEquity', equity)] + list(debts.items()):
            out.setdefault((ticker, f'xbrl:{tag}'), []).append(
                (bsd, {'value': v, 'published_at': pub, 'published_at_basis': 'test acceptance',
                       'fetch_id': 100 + k, 'retrieved_at': max(pub, RETRIEVED)}))
    return out


BS_VERSIONS = [('2026-06-10T12:00:00+00:00', '2026-05-31', 2e9, {'LongTermDebt': 1e9}),       # D/E 0.5
               ('2026-10-02T12:00:00+00:00', '2026-08-31', 2e9, {'LongTermDebt': 1.2e9}),     # D/E 0.6, in P
               ('2026-10-08T12:00:00+00:00', '2026-11-30', 1e9, {'LongTermDebt': 9e9})]       # after T_c
PERIODIC = [filing('10-Q', '2026-06-10T12:00:00+00:00', report='2026-05-31'),
            filing('10-Q', '2026-10-02T12:00:00+00:00', report='2026-08-31')]


def weekly_fred(start_value, step, n=120, end='2026-09-25'):
    """Weekly (Friday) observations alternating +step / -step, published 5 days after each Friday."""
    last = date.fromisoformat(end)
    out, v = [], start_value
    for k in range(n, -1, -1):
        d = last - timedelta(weeks=k)
        v += step if k % 2 else -step
        out.append((d.isoformat(), round(v, 6), end_of_us_trading_day_utc(d + timedelta(days=5))))
    return out


def risks_ctx(**kw):
    vols = [1_000_000.0] * n_elig() + [1e12] * (len(ALL_SESSIONS) - n_elig())
    for i in range(n_elig() - 5, n_elig()):
        vols[i] = 3_000_000.0
    events = [
        form4('A1', 'S', 100_000.0, ['Alice', 'Fund LP'], False, '2026-10-01T14:00:00+00:00'),   # in P
        form4('A1', 'S', 50_000.0, ['Alice', 'Fund LP'], False, '2026-10-01T14:00:00+00:00'),
        form4('B1', 'S', 30_000.0, ['Bob'], None, '2026-09-10T14:00:00+00:00'),     # plan unknown -> discretionary
        form4('C1', 'S', 999_999.0, ['Carol'], True, '2026-09-12T14:00:00+00:00'),  # 10b5-1 plan: excluded
        form4('D1', 'P', 10_000.0, ['Dan'], False, '2026-09-15T14:00:00+00:00'),    # purchase: not a sale
        form4('E1', 'S', 777_777.0, ['Eve'], False, '2026-10-07T09:00:00+00:00'),   # after T_c: excluded
        form4('F1', 'S', 20_000.0, ['Fay'], False, '2026-07-05T14:00:00+00:00'),    # only in the T_p window
        form4('G1', 'S', 5_000.0, ['Gil'], False, '2026-03-01T14:00:00+00:00'),     # earliest stored
    ]
    db = FakeDB(events={('AAA', 'form4:transaction'): events}, xbrl=xbrl(kw.pop('bs_versions', BS_VERSIONS)))
    filings_rows = [filing('4', e, acc=a) for a, e in (('A1', '2026-10-01T14:00:00+00:00'),
                                                       ('B1', '2026-09-10T14:00:00+00:00'),
                                                       ('C1', '2026-09-12T14:00:00+00:00'),
                                                       ('D1', '2026-09-15T14:00:00+00:00'),
                                                       ('E1', '2026-10-07T09:00:00+00:00'),
                                                       ('F1', '2026-07-05T14:00:00+00:00'))]
    filings_rows += [filing('8-K', '2026-10-02T20:00:00+00:00', ['1.05', '9.01']),
                     filing('8-K', '2026-10-05T20:00:00+00:00', ['2.02']),          # earnings: not a red flag
                     filing('NT 10-Q', '2026-10-07T10:00:00+00:00'),               # after T_c: excluded
                     filing('10-K', '2025-01-01T12:00:00+00:00', report='2024-12-31')] + PERIODIC
    vix = [(d, 15.0, end_of_us_trading_day_utc(date.fromisoformat(d) + timedelta(days=1)))
           for d in ALL_SESSIONS[-400:]]
    vix = [(d, v + (0.5 if i % 2 else -0.5), p) for i, (d, v, p) in enumerate(vix)]
    vix = [(d, 30.0 if d == '2026-10-05' else v, p) for d, v, p in vix]            # spike known at T_c
    nfci = weekly_fred(-0.5, 0.01, end='2026-09-18')                               # nothing new after T_p
    stl = weekly_fred(0.0, 0.05, end='2026-10-02')
    stl.append(('2026-09-18', stl[-3][1] + 0.4, '2026-10-06T05:00:00+00:00'))       # T_p obs revised by T_c
    base = dict(prices={'AAA': ok_prices(frame(risky_closes(), vols), 2)},
                fred={'VIXCLS': vix, 'NFCI': nfci, 'STLFSI4': stl},
                fred_status={'BAMLH0A0HYM2': 'FRED HTTP 500'},
                filings={'AAA': feed(filings_rows)}, sec=StrictSEC(), db=db)
    base.update(kw)
    return FakeCtx(**base)


def risk_table(out, ticker='AAA'):
    t = next(t for t in out['tables'] if t['title'] == f'{ticker} — risk indicators (T_p vs T_c)')
    return {r[0]: dict(zip(t['columns'], r)) for r in t['rows']}


def test_risks_full_table_and_price_indicator_values():
    ctx = risks_ctx()
    out = risks.build(ctx).as_dict()
    assert out['name'] == 'risks' and out['questions'] == [8]
    rows = risk_table(out)
    assert len(rows) == 8                                                      # full pre-declared table
    closes = np.array(risky_closes()[:n_elig()])
    lr = np.diff(np.log(closes))
    s_c = np.std(lr[-20:], ddof=1) * math.sqrt(252) * 100
    s_p = np.std(lr[-25:-5], ddof=1) * math.sqrt(252) * 100
    sig = rows['sigma20 (annualised, %)']
    assert sig['as known at T_c'] == pytest.approx(s_c, abs=0.01) and sig['as known at T_p'] == pytest.approx(s_p, abs=0.01)
    assert sig['increased'] == 'yes'
    dd = rows['drawdown vs 252-session max (%)']
    assert dd['as known at T_c'] == pytest.approx((closes[-1] / closes[-252:].max() - 1) * 100, abs=0.01)
    assert dd['as known at T_p'] == pytest.approx((closes[-6] / closes[-257:-5].max() - 1) * 100, abs=0.01)
    assert dd['increased'] == 'yes'
    vol = rows['5-session volume ratio']
    assert vol['as known at T_c'] == pytest.approx(3.0) and vol['as known at T_p'] == pytest.approx(1.0)
    assert vol['increased'] == 'yes'
    assert 'test-v1' in next(t for t in out['tables'] if t['scope'] == 'AAA')['note']


def test_risks_sec_rows_are_point_in_time_official_and_reuse_only():
    ctx = risks_ctx()                                     # ctx.sec is StrictSEC: any live-client use fails
    out = risks.build(ctx).as_dict()
    rows = risk_table(out)
    de = rows['debt-to-equity (SEC XBRL)']
    assert (de['as known at T_p'], de['as known at T_c']) == (0.5, 0.6)       # 9.0 published after T_c: unseen
    assert de['increased'] == 'not assessed: no pre-declared threshold'
    debt = rows['debt (SEC XBRL, USD)']
    assert (debt['as known at T_p'], debt['as known at T_c'], debt['change']) == (1e9, 1.2e9, '+20.0% relative')
    c = next(c for c in out['conclusions'] if c['statement'].startswith('AAA balance-sheet'))
    assert c['kind'] == 'official_fact' and c['level'] == STRONG and c['reason_codes'] == []
    assert [e['published_at'] for e in c['evidence']] == ['2026-06-10T12:00:00+00:00', '2026-10-02T12:00:00+00:00']
    assert [e['fetch_id'] for e in c['evidence']] == [100, 101]           # provenance of the stored facts used
    assert 'new balance sheet' in c['statement'] and 'stored SEC XBRL facts' in c['statement']
    # an optional threshold key, once pre-declared in config, is honoured
    ctx = risks_ctx(weekly=dict(WEEKLY, thresholds=dict(THRESHOLDS, debt_to_equity_change_abs=0.05)))
    assert risk_table(risks.build(ctx).as_dict())['debt-to-equity (SEC XBRL)']['increased'] == 'yes'


def test_risks_insider_windows_distinct_first_owner_and_partial_coverage():
    out = risks.build(risks_ctx()).as_dict()
    rows = risk_table(out)
    val = rows['discretionary insider sales, 90 days (USD)']
    assert val['as known at T_c'] == pytest.approx(180_000.0)                 # A1 150k + B1 30k
    assert val['as known at T_p'] == pytest.approx(50_000.0)                  # B1 30k + F1 20k
    assert val['increased'] == 'not assessed: no pre-declared threshold'
    sellers = rows['distinct discretionary sellers, 90 days']
    assert (sellers['as known at T_p'], sellers['as known at T_c']) == (2, 2)  # Alice (joint filer counted once), Bob
    # earliest stored row (2026-03-01) precedes both windows, every Form 4 listed by SEC in both windows has
    # stored transactions and the feed was retrieved after the cutoff: coverage verified
    c = next(c for c in out['conclusions'] if 'discretionary open-market sales' in c['statement'])
    assert c['kind'] == 'official_fact' and c['level'] == STRONG and c['reason_codes'] == []
    assert 'USD 180,000' in c['statement'] and 'USD 50,000' in c['statement']
    assert '2 distinct seller(s)' in c['statement']


def test_risks_insider_coverage_gap_and_complete_coverage():
    ctx = risks_ctx()
    late = [e for e in ctx.db._events[('AAA', 'form4:transaction')] if e['available_at'] >= '2026-09-01']
    ctx.db._events[('AAA', 'form4:transaction')] = late                        # earliest 2026-09-10 > T_p - 90 d
    c = next(c for c in risks.build(ctx).as_dict()['conclusions'] if 'discretionary open-market' in c['statement'])
    assert 'PARTIAL_COVERAGE' in c['reason_codes'] and 'before the earliest stored transaction' in c['statement']
    ok = risks_ctx()
    ok._filings['AAA']['filings'].append(filing('4', '2026-09-20T12:00:00+00:00', acc='X9'))   # never ingested
    c = next(c for c in risks.build(ok).as_dict()['conclusions'] if 'discretionary open-market' in c['statement'])
    assert 'PARTIAL_COVERAGE' in c['reason_codes'] and '1 of' in c['statement']


def test_risks_insider_unverified_when_the_sec_feed_is_unavailable():
    ctx = risks_ctx(filings={})
    c = next(c for c in risks.build(ctx).as_dict()['conclusions'] if 'discretionary open-market' in c['statement'])
    assert c['level'] == UNCERTAIN and 'FRESHNESS_UNKNOWN' in c['reason_codes']
    assert 'coverage not verified' in c['statement']


def test_risks_red_flags_window_and_negative_fact():
    out = risks.build(risks_ctx()).as_dict()
    rf = risk_table(out)['red-flag SEC filings in the week (count)']
    assert rf['as known at T_c'] == 1 and rf['increased'] == 'yes'            # 1.05; NT 10-Q after T_c excluded
    c = next(c for c in out['conclusions'] if 'red-flag SEC filing(s)' in c['statement'])
    assert '1.05' in c['statement'] and c['level'] == STRONG and c['kind'] == 'official_fact'
    quiet = risks_ctx(filings={'AAA': feed([filing('8-K', '2026-10-05T20:00:00+00:00', ['2.02']),
                                            filing('10-K', '2025-01-01T12:00:00+00:00')])})
    c = next(c for c in risks.build(quiet).as_dict()['conclusions'] if 'no red-flag' in c['statement'])
    assert c['level'] == STRONG and c['evidence'][0]['published_at'] == T_C
    stale_feed = risks_ctx(filings={'AAA': feed([filing('10-K', '2025-01-01T12:00:00+00:00')], after_cutoff=False)})
    out = risks.build(stale_feed).as_dict()
    un = {u['item']: u['reason'] for u in out['unavailable']}
    assert 'negative fact' in un['absence of red-flag filings in the week']
    # the row must not show 0 / 'no' when the absence is not established, nor count as assessed
    rf = risk_table(out)['red-flag SEC filings in the week (count)']
    assert rf['as known at T_c'] is None and rf['increased'] is None and rf['change'] is None
    judge = next(c for c in out['conclusions'] if c['scope'] == 'AAA' and c['kind'] == 'interpretation')
    assert 'PARTIAL_COVERAGE' in judge['reason_codes']
    assert 'unavailable: ' in judge['statement'] and 'red-flag SEC filings in the week (count)' in judge['statement']
    per_flag = next(t for t in out['tables'] if t['title'] == 'Companies per flag')
    assert ['red-flag SEC filings in the week (count)', None, 0] in per_flag['rows']


def test_risks_market_stress_rows():
    ctx = risks_ctx()
    out = risks.build(ctx).as_dict()
    t = next(t for t in out['tables'] if t['title'] == 'Market stress indicators (FRED, rank 1)')
    rows = {r[0]: dict(zip(t['columns'], r)) for r in t['rows']}
    assert [r[0] for r in t['rows']] == ['VIXCLS', 'BAMLH0A0HYM2', 'NFCI', 'STLFSI4']     # full table
    vix = rows['VIXCLS']
    assert vix['obs date (T_c)'] == '2026-10-05' and vix['value (T_c)'] == 30.0          # s_0 obs not yet public
    assert vix['obs date (T_p)'] == '2026-09-28' and vix['increased'] == 'yes'
    assert rows['BAMLH0A0HYM2']['value (T_c)'] is None
    assert rows['NFCI']['increased'] == 'no (no new observation)'
    assert 'standard deviation' in t['note'] and 'test-v1' in t['note']
    fred_c = {c['statement'].split(':')[0]: c for c in out['conclusions'] if c['scope'] == 'overall'
              and c['kind'] == 'official_fact'}
    assert fred_c['VIXCLS']['level'] == STRONG
    assert 'FIRST_PRINT_WITHIN_REVISION_NOISE' in fred_c['STLFSI4']['reason_codes']
    assert fred_c['STLFSI4']['level'] == UNCERTAIN and 'change vs the revised value' in fred_c['STLFSI4']['statement']
    un = {u['item']: u['reason'] for u in out['unavailable']}
    assert un['BAMLH0A0HYM2 (ICE BofA US High Yield option-adjusted spread (%))'] == 'FRED: FRED HTTP 500'
    assert all(i <= T_C for _, i in ctx.value_at_calls)


def test_risks_judgement_is_interpretation_and_risk_score_not_implemented():
    out = risks.build(risks_ctx()).as_dict()
    judge = next(c for c in out['conclusions'] if c['scope'] == 'AAA' and c['kind'] == 'interpretation')
    assert judge['level'] == UNCERTAIN and 'INTERPRETIVE' in judge['reason_codes']
    assert 'sigma20' in judge['statement'] and 'interpretation' in judge['statement']
    prices = [c for c in out['conclusions'] if c['scope'] == 'AAA' and c['kind'] == 'market_fact']
    assert prices and all('SINGLE_RANK2_SOURCE' in c['reason_codes'] for c in prices)
    assert all(c['kind'] != 'system_output' for c in out['conclusions'])
    un = {u['item']: u['reason'] for u in out['unavailable']}
    assert un['risk_score'].startswith('NOT IMPLEMENTED')
    for c in out['conclusions']:
        assert not any(w in c['statement'].lower() for w in CAUSAL)
        assert all(e['published_at'] is None or e['published_at'] <= T_C for e in c['evidence'])


def test_risks_everything_missing_is_unavailable_never_zero():
    ctx = FakeCtx(universe=('QQQ',), fred_status={s: 'FRED_API_KEY not set' for s, _, _ in risks.STRESS_SERIES})
    out = risks.build(ctx).as_dict()
    rows = risk_table(out, 'QQQ')
    assert len(rows) == 8 and all(r['as known at T_c'] is None for r in rows.values())
    items = {(u['scope'], u['item']) for u in out['unavailable']}
    assert ('QQQ', 'risk judgement') in items and ('QQQ', 'sigma20 (annualised, %)') in items
    assert ('QQQ', 'discretionary insider sales, 90 days (USD)') in items
    assert ('overall', 'VIXCLS (CBOE Volatility Index (VIX), close)') in items
    assert not [c for c in out['conclusions'] if c['scope'] == 'QQQ']


def test_risks_look_ahead_from_a_broken_accessor_raises():
    class Leaky(FakeCtx):
        def value_at(self, sid, instant):
            return '2026-10-06', 99.0, '2026-10-08T05:00:00+00:00'
    base = risks_ctx()
    ctx = Leaky(prices=base._prices, fred=base._fred, filings=base._filings, sec=base.sec, db=base.db)
    with pytest.raises(LookAheadError):
        risks.build(ctx)


def test_weekly_changes_rule():
    pts = [('2026-09-04', 1.0), ('2026-09-10', 1.5), ('2026-09-11', 2.0), ('2026-09-18', 1.0), ('2026-10-02', 4.0)]
    assert risks.weekly_changes(pts) == [1.0, -1.0]          # last obs of each week; the 2-week gap is skipped


# ---------------------------------------------------------------- review fixes (P3.0 adversarial review)

def test_market_cross_check_uses_adjusted_close_through_a_spy_ex_dividend_week():
    """SPY's raw close drops by a quarter of dividends on its ex-date; the price index does not."""
    adj = [100 * 1.001 ** i for i in range(len(ALL_SESSIONS))]
    raw = [a / 0.9965 if d < '2026-10-02' else a for a, d in zip(adj, ALL_SESSIONS)]   # ex-date inside the week
    ctx = market_ctx(prices={'SPY': ok_prices(frame(adj, close_raw=raw), 1)},
                     fred={'SP500': sp500_vintages([5000 * 1.001 ** i for i in range(len(ALL_SESSIONS))],
                                                   same_day=True)})
    out = market.build(ctx).as_dict()
    c = next(c for c in out['conclusions'] if c['statement'].startswith('SPY weekly'))
    assert c['level'] == STRONG and 'FRED SP500 agrees' in c['statement']
    row = next(t for t in out['tables'] if t['title'] == 'SPY vs FRED SP500 cross-check')['rows'][0]
    assert 'adjusted close' in row[0] and row[5] == pytest.approx(0.0, abs=1e-6) and row[6] == 'yes'


def test_market_strong_figure_is_the_figure_that_was_checked():
    """Stated (adjusted) SPY return 0.35 pp away from FRED: never STRONGLY SUPPORTED with 'agrees'."""
    raw = [100 * 1.001 ** i for i in range(len(ALL_SESSIONS))]
    adj = [r * 0.9965 if d < '2026-10-02' else r for r, d in zip(raw, ALL_SESSIONS)]
    ctx = market_ctx(prices={'SPY': ok_prices(frame(adj, close_raw=raw), 1)},
                     fred={'SP500': sp500_vintages([5000 * 1.001 ** i for i in range(len(ALL_SESSIONS))],
                                                   same_day=True)})
    c = next(c for c in market.build(ctx).as_dict()['conclusions'] if c['statement'].startswith('SPY weekly'))
    assert c['level'] == UNCERTAIN and 'CONFLICTING_SOURCES' in c['reason_codes']
    assert 'FRED SP500 agrees' not in c['statement'] and 'FRED SP500 disagrees' in c['statement']
    assert market.agrees(0.005, 0.0049) is True and market.agrees(0.001, -0.001) is False
    assert market.agrees(None, 0.01) is None and market.agrees(0.0085, 0.005) is False


def test_risks_balance_sheet_gap_against_the_sec_feed_is_unavailable():
    # the feed lists the 10-Q for 2026-08-31 accepted in P, but its facts were never stored
    ctx = risks_ctx(bs_versions=BS_VERSIONS[:1])
    out = risks.build(ctx).as_dict()
    rows = risk_table(out)
    de, debt = rows['debt-to-equity (SEC XBRL)'], rows['debt (SEC XBRL, USD)']
    assert (de['as known at T_p'], de['as known at T_c']) == (0.5, None)      # never the stale 0.5 as "at T_c"
    assert (debt['as known at T_p'], debt['as known at T_c']) == (1e9, None)
    un = {(u['scope'], u['item']): u['reason'] for u in out['unavailable']}
    assert '10-Q for period 2026-08-31' in un[('AAA', 'debt-to-equity (SEC XBRL) at T_c')]
    assert 'not in the stored XBRL facts' in un[('AAA', 'debt (SEC XBRL, USD) at T_c')]
    c = next(c for c in out['conclusions'] if c['statement'].startswith('AAA balance-sheet'))
    assert c['level'] == UNCERTAIN and 'PARTIAL_COVERAGE' in c['reason_codes']
    assert '(balance sheet unknown, as known at T_c)' in c['statement'] and len(c['evidence']) == 1


def test_risks_balance_sheet_coverage_unverified_with_a_feed_retrieved_before_the_cutoff():
    ctx = risks_ctx(weekly=dict(WEEKLY, thresholds=dict(THRESHOLDS, debt_to_equity_change_abs=0.05)))
    ctx._filings['AAA'] = dict(ctx._filings['AAA'], retrieved_after_cutoff=False,
                               fetch={'fetch_id': 5, 'retrieved_at': STALE_RETRIEVAL})
    out = risks.build(ctx).as_dict()
    de = risk_table(out)['debt-to-equity (SEC XBRL)']
    assert (de['as known at T_p'], de['as known at T_c']) == (0.5, 0.6)       # stored values, coverage unverified
    assert de['increased'] is None                                            # a declared rule is not applied
    un = {(u['scope'], u['item']): u['reason'] for u in out['unavailable']}
    assert 'not verified' in un[('AAA', 'debt-to-equity (SEC XBRL): change vs the pre-declared rule')]
    c = next(c for c in out['conclusions'] if c['statement'].startswith('AAA balance-sheet'))
    assert 'PARTIAL_COVERAGE' in c['reason_codes'] and 'retrieved before this instant' in c['statement']


def test_risks_debt_unknown_at_tp_has_a_reason_and_debt_from_zero():
    out = risks.build(risks_ctx(bs_versions=BS_VERSIONS[1:2])).as_dict()     # first balance sheet public in P
    debt = risk_table(out)['debt (SEC XBRL, USD)']
    assert (debt['as known at T_p'], debt['as known at T_c'], debt['increased']) == (None, 1.2e9, None)
    un = {(u['scope'], u['item']): u['reason'] for u in out['unavailable']}
    assert 'no SEC XBRL balance-sheet fact stored' in un[('AAA', 'debt (SEC XBRL, USD) at T_p')]
    assert ('AAA', 'debt-to-equity (SEC XBRL) at T_p') in un
    zero = [('2026-06-10T12:00:00+00:00', '2026-05-31', 2e9, {'LongTermDebt': 0.0}),
            ('2026-10-02T12:00:00+00:00', '2026-08-31', 2e9, {'LongTermDebt': 1e8})]
    ctx = risks_ctx(bs_versions=zero, weekly=dict(WEEKLY, thresholds=dict(THRESHOLDS, debt_change_rel=0.2)))
    out = risks.build(ctx).as_dict()
    debt = risk_table(out)['debt (SEC XBRL, USD)']
    assert (debt['as known at T_p'], debt['as known at T_c']) == (0.0, 1e8)
    assert debt['change'] == 'from zero' and debt['increased'] == 'yes'
    assert not [u for u in out['unavailable'] if u['scope'] == 'AAA' and 'debt' in u['item']]
    ctx = risks_ctx(bs_versions=zero)
    assert risk_table(risks.build(ctx).as_dict())['debt (SEC XBRL, USD)']['increased'] == risks.NOT_ASSESSED


def test_risks_no_stored_xbrl_is_unavailable_without_any_sec_call():
    out = risks.build(risks_ctx(bs_versions=[])).as_dict()                  # StrictSEC would raise on any call
    rows = risk_table(out)
    assert rows['debt-to-equity (SEC XBRL)']['as known at T_c'] is None
    un = {(u['scope'], u['item']): u['reason'] for u in out['unavailable']}
    assert 'never downloads' in un[('AAA', 'debt (SEC XBRL, USD)')]


def test_risks_red_flag_row_unknown_unless_the_feed_covers_the_window():
    # the feed does not reach back to T_p: absence not established
    short = risks_ctx(filings={'AAA': feed([filing('8-K', '2026-10-05T20:00:00+00:00', ['2.02'])])})
    out = risks.build(short).as_dict()
    rf = risk_table(out)['red-flag SEC filings in the week (count)']
    assert rf['as known at T_c'] is None and rf['increased'] is None
    un = {u['item']: u['reason'] for u in out['unavailable']}
    assert 'does not reach back to T_p' in un['absence of red-flag filings in the week']
    # an 8-K of the window without item codes: its items are unknown
    noitems = risks_ctx(filings={'AAA': feed([filing('8-K', '2026-10-05T20:00:00+00:00'),
                                              filing('10-K', '2025-01-01T12:00:00+00:00')])})
    out = risks.build(noitems).as_dict()
    assert risk_table(out)['red-flag SEC filings in the week (count)']['as known at T_c'] is None
    assert not [c for c in out['conclusions'] if 'no red-flag' in c['statement']]
    # a listed red flag is a positive fact even from a stale feed; the count is then a lower bound
    stale = risks_ctx(filings={'AAA': feed([filing('8-K', '2026-10-02T20:00:00+00:00', ['4.02']),
                                            filing('10-K', '2025-01-01T12:00:00+00:00')], after_cutoff=False)})
    out = risks.build(stale).as_dict()
    rf = risk_table(out)['red-flag SEC filings in the week (count)']
    assert rf['as known at T_c'] == '>= 1' and rf['increased'] == 'yes' and rf['change'] is None
    c = next(c for c in out['conclusions'] if 'red-flag SEC filing(s)' in c['statement'])
    assert 'PARTIAL_COVERAGE' in c['reason_codes'] and 'may be incomplete' in c['statement']


def test_risks_stress_rule_scales_with_the_weeks_between_observations():
    nfci = weekly_fred(0.0, 0.1, end='2026-09-11')                  # known at T_p: latest obs 2026-09-11
    last = nfci[-1][1]
    nfci += [('2026-09-18', last + 0.5, '2026-10-08T05:00:00+00:00'),       # published after T_c: unseen
             ('2026-09-25', round(last + 0.12, 6), '2026-10-01T05:00:00+00:00')]
    ctx = risks_ctx(fred={'NFCI': nfci}, fred_status={})
    out = risks.build(ctx).as_dict()
    t = next(t for t in out['tables'] if t['title'] == 'Market stress indicators (FRED, rank 1)')
    row = {r[0]: dict(zip(t['columns'], r)) for r in t['rows']}['NFCI']
    assert (row['obs date (T_p)'], row['obs date (T_c)'], row['weeks between obs']) == ('2026-09-11', '2026-09-25', 2)
    sd = row['1 sd of weekly changes (known at T_p)']
    assert sd == pytest.approx(0.1, rel=0.01) and row['change'] == pytest.approx(0.12)
    assert row['rule threshold (1 sd x sqrt(weeks))'] == pytest.approx(sd * math.sqrt(2), rel=1e-3)
    assert row['increased'] == 'no'                                  # 0.12 > 1 sd but < sqrt(2) sd
    assert 'sqrt' in t['note']
    assert risks.weeks_spanned('2026-09-28', '2026-10-05') == 1 and risks.weeks_spanned('2026-09-25', '2026-10-06') == 2


def test_risks_stress_counts_only_assessed_series():
    out = risks.build(risks_ctx()).as_dict()                         # BAMLH0A0HYM2: FRED HTTP 500
    per_flag = next(t for t in out['tables'] if t['title'] == 'Companies per flag')
    market_row = per_flag['rows'][-1]
    assert market_row[1:] == [1, 3]                                  # VIXCLS beyond; 3 of 4 assessed
    stress = next(c for c in out['conclusions'] if c['scope'] == 'overall' and c['kind'] == 'interpretation')
    assert 'PARTIAL_COVERAGE' in stress['reason_codes'] and 'BAMLH0A0HYM2' in stress['statement']
    assert '3 of 4 series assessed' in stress['statement']
    none = FakeCtx(universe=('QQQ',), fred_status={s: 'FRED_API_KEY not set' for s, _, _ in risks.STRESS_SERIES})
    out = risks.build(none).as_dict()
    per_flag = next(t for t in out['tables'] if t['title'] == 'Companies per flag')
    assert per_flag['rows'][-1][1:] == [None, 0]                     # never "0 beyond, 4 assessed"
    assert all(r[1] is None and r[2] == 0 for r in per_flag['rows'][:-1])
