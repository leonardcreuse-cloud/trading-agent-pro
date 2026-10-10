"""Weekly report sections 'news' (Q4, Q1) and 'sector' (Q6) - offline tests on a fake context.

All prices, filings, articles and NewsAPI payloads below are SYNTHETIC: they exist only to check the
calculation, point-in-time, de-duplication and evidence-level logic and never reach a report.
Network access is blocked by tests/conftest.py; NewsAPI calls go to an injected fake HTTP getter.
"""

import gzip
import json
import math
from datetime import datetime

import pandas as pd
import pytest

from src import database as database_module
from src.database import Database, freshness
from src.weekly.core import STRONG, UNAVAILABLE, UNCERTAIN, LookAheadError, TimeModel
from src.weekly.sections import news, sector

ALL_SESSIONS = [d.date().isoformat() for d in pd.bdate_range(end='2026-10-09', periods=900)]
CUTOFF = '2026-10-07T12:00:00+00:00'          # s_0 = 2026-10-06, T_c = 2026-10-07T05:00Z, T_p = 2026-09-30T05:00Z
RETRIEVED = '2026-10-07T13:00:00+00:00'
CAUSAL = ('because', 'due to', 'drove', 'driven by', 'on the back of', 'caused', 'thanks to')
WEEKLY = {'benchmark': 'SPY', 'sector_etf': {'AAA': 'XLK', 'BBB': 'XLB'},
          'peers': {'AAA': ['P1', 'P2', 'P3'], 'BBB': ['P4', 'P5']},
          'all_sector_etfs': ['XLK', 'XLB', 'XLE'], 'thresholds_version': 'test-v1',
          'thresholds': {'abs_excess_return_z': 2.0}}
TEST_KEY = 'synthetic-test-key-0123456789'


# ---------------------------------------------------------------- shared fakes

class BaseCtx:
    def __init__(self, cutoff=CUTOFF, generated=None, universe=('AAA',), weekly=None):
        self.tm = TimeModel(ALL_SESSIONS, cutoff, generated or cutoff)
        self.universe = list(universe)
        self.weekly = json.loads(json.dumps(weekly or WEEKLY))

    def freshness(self, as_of, cadence):
        return freshness(as_of, cadence, now=datetime.fromisoformat(self.tm.cutoff))


def all_conclusions(out):
    return out['conclusions']


def assert_no_causal_wording(out):
    for c in out['conclusions']:
        text = c['statement'].lower()
        assert not any(w in text for w in CAUSAL), c['statement']


# ================================================================ sector (Q6)

def n_elig():
    return ALL_SESSIONS.index('2026-10-06') + 1


def closes(current, past=0.01, after=1e6):
    """Adjusted closes: the 5 sessions ending s_0 return `current`; earlier 5-session windows +/- past."""
    n = n_elig()
    out, c = [], 100.0
    for i in range(n):
        w = (n - 1 - i) // 5
        r = current if w == 0 else (past if w % 2 else -past)
        c *= (1 + r) ** 0.2
        out.append(c)
    return out + [after] * (len(ALL_SESSIONS) - n)          # absurd bars AFTER s_0 (look-ahead bait)


def frame(values):
    idx = pd.to_datetime(ALL_SESSIONS[:len(values)])
    return pd.DataFrame({'close': values, 'close_raw': values, 'volume': [1e6] * len(values)}, index=idx)


def ok(values, fetch_id=1):
    return {'status': 'OK', 'frame': frame(values), 'fetch': {'fetch_id': fetch_id, 'retrieved_at': RETRIEVED},
            'reason': None}


SIC_FEED = {'status': 'OK', 'sic': '7372', 'sic_description': 'Services-Prepackaged Software', 'name': 'AAA Inc',
            'fetch': {'fetch_id': 77, 'retrieved_at': RETRIEVED}, 'reason': None,
            'filings': [{'form': '8-K', 'filing_date': '2026-10-07', 'accession_number': 'acc-after',
                         'published_at': '2026-10-07T20:00:00+00:00'},            # after the cutoff: not an anchor
                        {'form': '4', 'filing_date': '2026-10-05', 'accession_number': 'acc-form4',
                         'published_at': '2026-10-05T21:00:00+00:00'},            # insider filing: not preferred
                        {'form': '10-Q', 'filing_date': '2026-09-02', 'accession_number': 'acc-before',
                         'published_at': '2026-09-02T20:10:00+00:00'}]}


class SectorCtx(BaseCtx):
    def __init__(self, prices=None, filings=None, **kw):
        super().__init__(**kw)
        self._prices = prices or {}
        self._filings = filings or {}
        self.price_calls = []

    def prices(self, ticker):
        self.price_calls.append(ticker)
        return self._prices.get(ticker) or {'status': UNAVAILABLE, 'frame': None, 'fetch': None,
                                            'reason': 'yfinance returned no data'}

    def filings(self, ticker):
        return self._filings.get(ticker) or {'status': UNAVAILABLE, 'filings': [], 'fetch': None,
                                             'reason': 'CIK not found for test'}


def sector_prices(**over):
    p = {'SPY': ok(closes(0.01), 1), 'AAA': ok(closes(0.05), 2), 'XLK': ok(closes(0.03), 3),
         'P1': ok(closes(0.02), 4), 'P2': ok(closes(0.04), 5), 'P3': ok(closes(-0.01), 6),
         'XLB': ok(closes(-0.002), 7), 'XLE': ok(closes(0.0), 8)}
    p.update(over)
    return p


def table(out, title):
    return next(t for t in out['tables'] if t['title'] == title)


def row_of(t, key):
    return dict(zip(t['columns'], next(r for r in t['rows'] if r[0] == key)))


def test_sector_values_flag_and_no_bar_after_s0():
    ctx = SectorCtx(prices=sector_prices(), filings={'AAA': SIC_FEED})
    out = sector.build(ctx).as_dict()
    assert out['name'] == 'sector' and out['questions'] == [6]
    row = row_of(table(out, 'Sector-relative performance by company'), 'AAA')
    assert row['weekly return %'] == pytest.approx(5.0)                 # bars after s_0 (1e6) ignored
    assert row['ETF weekly return %'] == pytest.approx(3.0)
    sd = 0.01 * math.sqrt(156 / 155)                                     # 78 x +1 %, 78 x -1 %
    assert row['ETF sd of weekly returns %'] == pytest.approx(round(100 * sd, 2))
    assert row['peer median %'] == pytest.approx(2.0)                   # median of +2, +4, -1
    assert row['peer IQR pp'] == pytest.approx(2.5)                     # percentiles 0.5 / 3.0 (linear)
    assert row['peers with the median sign'] == '2/3'
    assert row['relative to ETF pp'] == pytest.approx(2.0)
    assert row['relative to peer median pp'] == pytest.approx(3.0)
    assert row['sector-wide flag'] == 'yes' and row['conditions not met'] is None

    flag = next(c for c in out['conclusions'] if 'sector-wide move flag SET' in c['statement'])
    assert flag['kind'] == 'interpretation' and flag['level'] == UNCERTAIN
    assert {'HEURISTIC_THRESHOLD', 'INTERPRETIVE'} <= set(flag['reason_codes'])
    assert 'coincided with' in flag['statement'] and 'no causal link' in flag['statement']
    assert sector.SECTOR_RULE_VERSION in flag['statement'] and '2/3' in flag['statement']

    fact = next(c for c in out['conclusions'] if c['statement'].startswith('AAA sector week'))
    assert fact['kind'] == 'market_fact' and fact['level'] == UNCERTAIN
    assert fact['reason_codes'] == ['SINGLE_RANK2_SOURCE']
    assert {e['fact'].split(':')[0] for e in fact['evidence']} == {'AAA', 'XLK', 'P1', 'P2', 'P3'}
    assert all(e['published_at'] == '2026-10-06T21:00:00+00:00' and e['rank'] == 2 for e in fact['evidence'])

    peers = table(out, 'AAA — peers (pre-declared)')
    assert [r[0] for r in peers['rows']] == ['P1', 'P2', 'P3']           # full pre-declared list
    assert [r[3] for r in peers['rows']] == ['yes', 'yes', 'no']
    assert 'selection' in peers['note'] and '2026' in peers['note']

    assert not any(c['kind'] == 'system_output' for c in out['conclusions'])
    assert not any(c['level'] == STRONG for c in out['conclusions'])
    assert_no_causal_wording(out)
    items = {u['item'] for u in out['unavailable']}
    assert 'sector ETF holdings' in items
    holdings = next(u for u in out['unavailable'] if u['item'] == 'sector ETF holdings')
    assert 'mechanical co-movement' in holdings['reason']
    assert any('test-v1' in n for n in out['notes'])
    assert ctx.price_calls.count('XLK') == 1                             # one ctx.prices call per ticker


def test_sector_flag_not_set_reports_failed_conditions():
    ctx = SectorCtx(prices=sector_prices(XLK=ok(closes(0.005), 3)), filings={'AAA': SIC_FEED})
    out = sector.build(ctx).as_dict()
    row = row_of(table(out, 'Sector-relative performance by company'), 'AAA')
    assert row['sector-wide flag'] == 'no' and '|ETF r_W|' in row['conditions not met']
    flag = next(c for c in out['conclusions'] if 'sector-wide move flag NOT set' in c['statement'])
    assert flag['kind'] == 'interpretation' and flag['level'] == UNCERTAIN
    assert 'coincided' not in flag['statement']

    # sign disagreement only (2 of 3 peers share the negative median sign: the share condition holds)
    ctx = SectorCtx(prices=sector_prices(P1=ok(closes(-0.02), 4), P2=ok(closes(-0.04), 5), P3=ok(closes(0.01), 6)))
    row = row_of(table(sector.build(ctx).as_dict(), 'Sector-relative performance by company'), 'AAA')
    assert row['sector-wide flag'] == 'no' and 'sign(ETF' in row['conditions not met']
    assert 'peers with the median sign' not in row['conditions not met']


def _flag_row(peer_returns, weekly=None):
    """AAA with ETF XLK +3 % (> 1 sd, positive) and the given peer returns (median positive in the cases below)."""
    names = [f'Q{i}' for i in range(1, len(peer_returns) + 1)]
    weekly = json.loads(json.dumps(weekly or WEEKLY))
    weekly['peers']['AAA'] = names
    prices = sector_prices(**{n: ok(closes(r), 10 + i) for i, (n, r) in enumerate(zip(names, peer_returns))})
    out = sector.build(SectorCtx(prices=prices, weekly=weekly)).as_dict()
    return row_of(table(out, 'Sector-relative performance by company'), 'AAA'), out


def test_sector_flag_peer_share_condition_is_checked_on_counts():
    # ETF sign = peer median sign and |ETF| > k sd, but only 2 of 4 peers share the sign: flag 'no'
    row, out = _flag_row([-0.03, -0.01, 0.02, 0.04])                   # median +0.5 %
    assert row['peer median %'] == pytest.approx(0.5) and row['peers with the median sign'] == '2/4'
    assert row['sector-wide flag'] == 'no'
    assert row['conditions not met'] == 'peers with the median sign 2/4 below the minimum share 2/3'
    # 3 of 5 (0.6) is below 2/3
    row, _ = _flag_row([-0.02, -0.01, 0.01, 0.02, 0.03])
    assert row['peers with the median sign'] == '3/5' and row['sector-wide flag'] == 'no'
    assert 'peers with the median sign 3/5' in row['conditions not met']
    # exactly 2/3 passes (default fixture: 2 of 3) and 4 of 6 passes
    row, _ = _flag_row([0.02, 0.04, -0.01])
    assert row['peers with the median sign'] == '2/3' and row['sector-wide flag'] == 'yes'
    row, _ = _flag_row([0.02, 0.04, -0.01, 0.03, -0.02, 0.01])
    assert row['peers with the median sign'] == '4/6' and row['sector-wide flag'] == 'yes'


@pytest.mark.parametrize('declared', ['2/3', [2, 3], 0.6667, '0.6667', 0.667])
def test_sector_declared_two_thirds_keeps_exactly_two_thirds_passing(declared):
    weekly = json.loads(json.dumps(WEEKLY))
    weekly['thresholds'][sector.SHARE_KEY] = declared
    row, out = _flag_row([0.02, 0.04, -0.01], weekly)                   # 2 of 3 share the sign
    assert row['sector-wide flag'] == 'yes', row['conditions not met']
    note = table(out, 'Sector-relative performance by company')['note']
    assert 'peer share from config thresholds test-v1' in note
    assert sector.share_met(2, 3, sector.parse_share(declared))
    assert sector.share_met(4, 6, sector.parse_share(declared))
    assert not sector.share_met(3, 5, sector.parse_share(declared))


def test_sector_share_parsing_and_invalid_config():
    assert sector.parse_share('2/3')['text'] == '2/3' and sector.parse_share([2, 3])['tol'] == 0
    assert 'share >= 0.6662' in sector.parse_share(0.6667)['text']      # effective bound is printed
    assert not sector.share_met(2, 3, sector.parse_share(0.7))           # 0.667 < 0.6995: a stricter rule is kept
    assert not sector.share_met(2, 3, sector.parse_share(0.67))
    assert sector.share_met(1, 1, sector.parse_share(1)) and not sector.share_met(4, 5, sector.parse_share(1))
    assert not sector.share_met(None, 3, sector.parse_share('2/3')) and not sector.share_met(0, 0, sector.parse_share('2/3'))
    for bad in ('abc', [2, 0], 1.5, 0, True, '1/0'):
        with pytest.raises(ValueError):
            sector.parse_share(bad)
    weekly = json.loads(json.dumps(WEEKLY))
    weekly['thresholds'][sector.SHARE_KEY] = 'two thirds'
    row, out = _flag_row([0.02, 0.04, -0.01], weekly)
    assert row['sector-wide flag'] is None                               # never a silent default
    u = next(u for u in out['unavailable'] if u['item'] == 'sector-wide move flag')
    assert 'invalid' in u['reason'] and sector.SHARE_KEY in u['reason']
    assert not any('sector-wide move flag' in c['statement'] for c in out['conclusions'])


def test_sector_rule_parameters_come_from_config_when_declared():
    weekly = json.loads(json.dumps(WEEKLY))
    weekly['thresholds'][sector.SIGMA_KEY] = 5.0                         # |3 %| is not > 5 sd
    ctx = SectorCtx(prices=sector_prices(), weekly=weekly)
    out = sector.build(ctx).as_dict()
    row = row_of(table(out, 'Sector-relative performance by company'), 'AAA')
    assert row['sector-wide flag'] == 'no'
    assert 'from config thresholds test-v1' in table(out, 'Sector-relative performance by company')['note']
    default = sector.build(SectorCtx(prices=sector_prices())).as_dict()
    assert 'spec default' in table(default, 'Sector-relative performance by company')['note']


def test_sector_missing_data_is_unavailable_never_filled():
    prices = sector_prices()
    del prices['XLK'], prices['P3']
    ctx = SectorCtx(prices=prices)
    out = sector.build(ctx).as_dict()
    row = row_of(table(out, 'Sector-relative performance by company'), 'AAA')
    assert row['ETF weekly return %'] is None and row['sector-wide flag'] is None
    assert row['peers with a return'] == '2/3' and row['peer median %'] == pytest.approx(3.0)
    items = {(u['scope'], u['item']) for u in out['unavailable']}
    assert ('AAA', 'sector ETF XLK weekly return') in items
    assert ('AAA', 'peer P3 weekly return') in items
    assert ('AAA', 'sector-wide move flag') in items
    assert ('AAA', 'SEC SIC code at the cutoff') in items               # filings unavailable in this ctx
    assert all(u['reason'] for u in out['unavailable'])
    fact = next(c for c in out['conclusions'] if c['statement'].startswith('AAA sector week'))
    assert 'PARTIAL_COVERAGE' in fact['reason_codes']                    # one peer missing
    etfs = table(out, 'Sector ETFs vs benchmark — week')
    assert [r[0] for r in etfs['rows']] == ['XLK', 'XLB', 'XLE']           # full list, missing ETF kept
    assert row_of(etfs, 'XLK')['weekly return %'] is None

    # a missing bar inside the week is not filled: the return still uses s_-5 and s_0, flagged partial
    values = closes(0.02)
    values[n_elig() - 3] = float('nan')
    out = sector.build(SectorCtx(prices=sector_prices(P1=ok(values, 4)))).as_dict()
    peers = table(out, 'AAA — peers (pre-declared)')
    assert peers['rows'][0][4] == '2026-10-02'
    fact = next(c for c in out['conclusions'] if c['statement'].startswith('AAA sector week'))
    assert 'PARTIAL_COVERAGE' in fact['reason_codes']

    # no bar on s_0: no weekly return (never interpolated)
    values = closes(0.02)[:n_elig() - 1]
    out = sector.build(SectorCtx(prices=sector_prices(AAA=ok(values, 2)))).as_dict()
    assert row_of(table(out, 'Sector-relative performance by company'), 'AAA')['weekly return %'] is None
    assert any(u['item'] == 'company weekly return' and '2026-10-06' in u['reason'] for u in out['unavailable'])


def test_sector_short_history_has_no_sd_and_no_flag():
    short = closes(0.03)[n_elig() - 100:]                                # ~19 weeks of history only
    ctx = SectorCtx(prices=sector_prices(XLK=ok_shift(short)))
    out = sector.build(ctx).as_dict()
    row = row_of(table(out, 'Sector-relative performance by company'), 'AAA')
    assert row['ETF weekly return %'] == pytest.approx(3.0) and row['ETF sd of weekly returns %'] is None
    assert row['sector-wide flag'] is None
    assert any('156-week sd' in u['item'] for u in out['unavailable'])


def ok_shift(values):
    """Frame whose bars end on the same sessions as the full series (history truncated at the start)."""
    n = n_elig()
    idx = pd.to_datetime(ALL_SESSIONS[n - (len(values) - (len(ALL_SESSIONS) - n)):len(ALL_SESSIONS)])
    df = pd.DataFrame({'close': values, 'close_raw': values, 'volume': [1e6] * len(values)}, index=idx)
    return {'status': 'OK', 'frame': df, 'fetch': {'fetch_id': 3, 'retrieved_at': RETRIEVED}, 'reason': None}


def _available_at(e):
    return e['published_at'] or e['retrieved_at']


@pytest.mark.parametrize('retrieved', [RETRIEVED, '2026-10-16T13:00:00+00:00'])
def test_sector_sic_from_a_feed_retrieved_after_the_cutoff_is_not_concluded(retrieved):
    # the feed shows the CURRENT code; the time it became public is unknown: never back-dated to another filing
    feed = dict(SIC_FEED, fetch={'fetch_id': 77, 'retrieved_at': retrieved})
    ctx = SectorCtx(prices=sector_prices(), filings={'AAA': feed})
    out = sector.build(ctx).as_dict()
    assert not any('SIC' in c['statement'] for c in out['conclusions'])
    u = next(u for u in out['unavailable'] if u['scope'] == 'AAA' and u['item'] == 'SEC SIC code at the cutoff')
    assert 'after the cutoff' in u['reason'] and 'current SIC' in u['reason']
    row = table(out, 'Official industry label (SEC SIC)')['rows'][0]
    assert row[:3] == ['AAA', '7372', 'Services-Prepackaged Software']
    assert 'not point-in-time' in row[3] and row[4] == retrieved
    for c in out['conclusions']:                                         # COALESCE(published_at, retrieved_at) <= T_c
        assert all(_available_at(e) <= ctx.tm.cutoff for e in c['evidence'])
    # the same fact offered as evidence with an unknown publication time is look-ahead
    with pytest.raises(LookAheadError):
        sector.evidence(ctx.tm, 'SEC EDGAR', 1, 'SIC 7372', published_at=None, retrieved_at=retrieved)


def test_sector_sic_from_a_feed_retrieved_before_the_cutoff_is_rank1_freshness_unknown():
    before = '2026-10-07T03:00:00+00:00'                                 # T_c = 2026-10-07T05:00Z
    feed = dict(SIC_FEED, fetch={'fetch_id': 77, 'retrieved_at': before})
    ctx = SectorCtx(prices=sector_prices(), filings={'AAA': feed})
    out = sector.build(ctx).as_dict()
    sic = next(c for c in out['conclusions'] if 'SIC 7372' in c['statement'])
    assert sic['kind'] == 'official_fact' and sic['evidence'][0]['rank'] == 1
    e = sic['evidence'][0]
    assert e['published_at'] is None and e['retrieved_at'] == before and e['fetch_id'] == 77   # never another filing's time
    assert sic['level'] == UNCERTAIN and sic['reason_codes'] == ['FRESHNESS_UNKNOWN']
    row = table(out, 'Official industry label (SEC SIC)')['rows'][0]
    assert row[:3] == ['AAA', '7372', 'Services-Prepackaged Software'] and 'before the cutoff' in row[3]
    assert not any(u['item'] == 'SEC SIC code at the cutoff' for u in out['unavailable'])

    # no SIC in the feed -> DATA UNAVAILABLE, no conclusion
    out = sector.build(SectorCtx(prices=sector_prices(), filings={'AAA': dict(feed, sic='')})).as_dict()
    assert not any('SIC' in c['statement'] for c in out['conclusions'])
    assert any(u['item'] == 'SEC SIC code at the cutoff' and 'no SIC code' in u['reason'] for u in out['unavailable'])


def test_sector_ticker_subset_and_overall_etf_conclusion():
    ctx = SectorCtx(prices=sector_prices(), universe=('AAA', 'BBB'))
    out = sector.build(ctx, tickers=['AAA']).as_dict()
    rows = table(out, 'Sector-relative performance by company')['rows']
    assert [r[0] for r in rows] == ['AAA']
    overall = next(c for c in out['conclusions'] if c['statement'].startswith('Sector ETF weekly returns'))
    assert overall['kind'] == 'market_fact' and overall['level'] == UNCERTAIN
    assert 'SPY +1.00%' in overall['statement'] and 'XLK +3.00% (+2.00 pp vs SPY)' in overall['statement']
    etfs = table(out, 'Sector ETFs vs benchmark — week')
    assert row_of(etfs, 'XLE')['excess vs SPY pp'] == pytest.approx(-1.0)


def test_sector_look_ahead_frame_after_s0_is_ignored_and_evidence_after_cutoff_raises():
    ctx = SectorCtx(prices=sector_prices())
    px = sector.series(ctx, 'AAA')
    assert list(px['close'].index)[-1] == '2026-10-06' and px['close'].max() < 1e5
    with pytest.raises(LookAheadError):
        sector.evidence(ctx.tm, 'yfinance', 2, 'close of 2026-10-07', published_at='2026-10-07T21:00:00+00:00')


# ================================================================ news (Q4, Q1)

class FakeHTTPResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = json.dumps(payload).encode()

    def json(self):
        return self._payload


class FakeHTTP:
    """requests.get-compatible fake: answers by query string, records every call."""

    def __init__(self, by_query, status=200):
        self.by_query, self.status, self.calls = by_query, status, []

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.calls.append({'url': url, 'params': dict(params), 'headers': dict(headers or {})})
        return FakeHTTPResponse(self.by_query[params['q']], self.status)


def art(title, outlet, published, url, description=''):
    return {'source': {'id': None, 'name': outlet}, 'author': None, 'title': title, 'description': description,
            'url': url, 'publishedAt': published, 'content': None}


GEO_ARTICLES = [
    art('US expands export controls on chips', 'Reuters', '2026-10-01T10:00:00Z', 'https://www.reuters.com/a/1'),
    art('US expands export controls on chips', 'Yahoo Entertainment', '2026-10-01T12:00:00Z',
        'https://yahoo.com/x/9'),                                         # syndicated copy: identical title
    art('US expands export controls on advanced chips', 'The Verge', '2026-10-02T09:00:00Z',
        'https://theverge.com/b'),                                        # near-duplicate, other outlet
    art('US widens export controls on chips', 'Reuters', '2026-10-01T15:00:00Z',
        'https://reuters.com/a/1/?utm_source=x#frag'),                    # same canonical URL, similar title
    art('tariffs-parser 1.2 released', 'Pypi.org', '2026-10-02T10:00:00Z', 'https://pypi.org/project/tariffs'),
    art('Stocks end the week mixed', 'CNBC', '2026-10-02T21:00:00Z', 'https://cnbc.com/s',
        'Indexes were little changed.'),                                  # not relevant to any topic
    art('New tariffs announced on steel', 'Bloomberg', '2026-10-07T06:00:00Z',
        'https://bloomberg.com/late'),                                    # after the cutoff: excluded
    art('Election calendar set', 'AP', '2026-09-29T10:00:00Z', 'https://ap.org/old'),   # before the window
    art('Steelmaker shares jump as new tariffs announced', 'MarketWatch', '2026-10-03T14:00:00Z',
        'https://marketwatch.com/t1'),
    art('Steelmaker shares jump as new tariffs announced today', 'Biztoc.com', '2026-10-03T15:00:00Z',
        'https://biztoc.com/x/t1'),
    art('Parliament sets snap elections', 'BBC News', '2026-10-04T08:00:00Z', 'https://bbc.co.uk/e'),
]
COMPANY_ARTICLES = [
    art('Acme Robotics wins contract', 'Reuters', '2026-10-01T10:00:00Z', 'https://reuters.com/acme1'),
    art('Acme Robotics wins large contract', 'Bloomberg', '2026-10-01T11:00:00Z', 'https://bloomberg.com/acme1'),
    art('Robots are everywhere', 'Wired', '2026-10-02T10:00:00Z', 'https://wired.com/r',
        'An industry overview.'),                                         # does not contain the name
    art('Acme Robotics docs', 'GitHub.com', '2026-10-02T11:00:00Z', 'https://github.com/acme/docs'),
]


def geo_payload(total=250):
    return {'status': 'ok', 'totalResults': total, 'articles': GEO_ARTICLES}


def company_payload(total=4):
    return {'status': 'ok', 'totalResults': total, 'articles': COMPANY_ARTICLES}


class NewsCtx(BaseCtx):
    def __init__(self, companies=None, **kw):
        super().__init__(**kw)
        self.db = Database()                    # isolated temporary data dir (conftest)
        self.companies = companies if companies is not None else {'AAA': 'Acme Robotics'}

    def company(self, ticker):
        return self.companies.get(ticker, ticker)


def http_for(geo=None, company=None, status=200):
    return FakeHTTP({news.GEO_QUERY: geo or geo_payload(), '"Acme Robotics"': company or company_payload()}, status)


def test_news_global_query_dedup_clusters_and_levels(monkeypatch):
    monkeypatch.setenv('NEWSAPI_KEY', TEST_KEY)
    ctx = NewsCtx()
    http = http_for()
    out = news.build(ctx, tickers=[], http_get=http).as_dict()
    assert out['name'] == 'news' and out['questions'] == [4, 1]
    assert len(http.calls) == 1
    call = http.calls[0]
    assert call['headers'] == {'X-Api-Key': TEST_KEY} and TEST_KEY not in json.dumps(call['params'])
    assert call['params']['from'] == '2026-09-30T05:00:00' and call['params']['to'] == '2026-10-07T05:00:00'
    assert call['params']['pageSize'] == 100 and call['params']['q'] == news.GEO_QUERY
    for term in ('sanctions', '"export controls"', 'tariffs', '"armed conflict"', 'elections', '"government shutdown"'):
        assert term in news.GEO_QUERY

    cov_table = table(out, 'Geopolitical news — query and coverage')
    cov = dict(zip(cov_table['columns'], cov_table['rows'][0]))
    assert cov['returned'] == 11 and cov['totalResults'] == 250 and cov['coverage'] == '4.4%'
    assert cov['after the cutoff (excluded)'] == 1 and cov['before the window'] == 1
    assert cov['code hosts dropped'] == 1 and cov['not relevant'] == 1
    assert cov['duplicates'] == 2 and cov['kept'] == 5 and cov['story clusters'] == 3
    assert cov['first publishedAt returned'] == '2026-09-29T10:00:00+00:00'
    assert cov['last publishedAt returned'] == '2026-10-07T06:00:00+00:00'

    topics = table(out, 'Geopolitical news — pre-declared topics')
    assert [r[0] for r in topics['rows']] == [t[0] for t in news.GEO_TOPICS]      # full list
    by_topic = {r[0]: r for r in topics['rows']}
    assert by_topic['export controls'][3:6] == [2, 1, 1]      # 2 deduplicated articles, 1 cluster with 2 outlets
    assert by_topic['tariffs'][3:6] == [2, 1, 1]
    assert by_topic['elections'][3:6] == [1, 1, 0]
    missing_topics = {u['item'] for u in out['unavailable'] if u['question'] == 4}
    assert "geopolitical topic 'sanctions' (news)" in missing_topics
    assert "geopolitical topic 'armed conflict' (news)" in missing_topics

    clusters = table(out, 'Geopolitical news — story clusters (all)')
    assert len(clusters['rows']) == 3
    first = dict(zip(clusters['columns'], clusters['rows'][0]))
    assert first['distinct outlets'] == 2 and first['outlets'] == 'Reuters, The Verge'
    assert first['duplicate / syndicated copies counted once (outlets)'] == '2 (Reuters, Yahoo Entertainment)'

    for c in out['conclusions']:
        assert c['kind'] == 'aggregator' and c['level'] == UNCERTAIN
        assert 'AGGREGATOR_ONLY' in c['reason_codes'] and 'PARTIAL_COVERAGE' in c['reason_codes']
        assert all(e['published_at'] <= ctx.tm.cutoff and e['rank'] == 3 for e in c['evidence'])
        assert all(e['published_at'] > ctx.tm.previous_cutoff for e in c['evidence'])
        assert 'bloomberg.com/late' not in json.dumps(c)
    stories = [c for c in out['conclusions'] if ': story G' in c['statement']]
    assert len(stories) == 2
    export = next(c for c in stories if 'export controls on chips' in c['statement'])
    assert 'reported by 2 outlets (aggregator)' in export['statement'] and 'not established' in export['statement']
    jump = next(c for c in stories if 'G2' in c['statement'] or 'MarketWatch' in c['statement'])
    assert 'jump' not in jump['statement'].lower() and 'headline not quoted' in jump['statement']
    assert_no_causal_wording(out)
    assert any('official primary documents' in u['item'] for u in out['unavailable'])
    assert any('requests made by this section: 1' in n for n in out['notes'])


def test_news_call_is_logged_with_raw_payload_and_never_the_key(monkeypatch, offline):
    monkeypatch.setenv('NEWSAPI_KEY', TEST_KEY)
    ctx = NewsCtx()
    out = news.build(ctx, tickers=[], http_get=http_for()).as_dict()
    fetch_ids = {e['fetch_id'] for c in out['conclusions'] for e in c['evidence']}
    assert len(fetch_ids) == 1
    fid = fetch_ids.pop()
    row = ctx.db.get_fetch(fid)
    assert row['source'] == 'NewsAPI' and row['status'] == 'OK' and row['http_status'] == 200
    assert row['n_records'] == len(GEO_ARTICLES)
    assert json.loads(ctx.db.read_raw(fid)) == geo_payload()
    assert TEST_KEY not in json.dumps(row) and TEST_KEY not in json.dumps(out)
    files = [p for p in (offline / 'data').rglob('*') if p.is_file()]
    assert any(p.name.endswith('.json.gz') for p in files)
    for path in files:
        data = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
        assert TEST_KEY.encode() not in data


def test_news_identical_request_is_reused_without_spending_budget(monkeypatch):
    monkeypatch.setenv('NEWSAPI_KEY', TEST_KEY)
    ctx = NewsCtx()
    first = news.build(ctx, tickers=['AAA'], http_get=http_for()).as_dict()

    def no_call(*a, **k):
        raise AssertionError('a stored identical request must be reused')

    second = news.build(ctx, tickers=['AAA'], http_get=no_call).as_dict()
    assert [c['statement'] for c in first['conclusions']] == [c['statement'] for c in second['conclusions']]
    assert table(second, 'Geopolitical news — query and coverage')['rows'][0][-1] == 'yes'
    assert any('requests made by this section: 0; stored identical requests reused: 2' in n for n in second['notes'])


def test_news_company_query_relevance_and_complete_window(monkeypatch):
    monkeypatch.setenv('NEWSAPI_KEY', TEST_KEY)
    # report generated >= T_c + 26 h and every result returned: no PARTIAL_COVERAGE, still UNCERTAIN
    ctx = NewsCtx(cutoff='2026-10-02T12:00:00+00:00', generated='2026-10-03T12:00:00+00:00',
                  universe=('AAA', 'BBB'))
    assert ctx.tm.news_complete() and ctx.tm.cutoff == '2026-10-02T05:00:00+00:00'
    http = http_for()
    out = news.build(ctx, include_global=False, http_get=http).as_dict()
    assert [c['params']['q'] for c in http.calls] == ['"Acme Robotics"']          # BBB has no configured name
    assert any(u['scope'] == 'BBB' and 'bare-ticker' in u['reason'] for u in out['unavailable'])
    t = table(out, 'AAA — news story clusters (aggregator)')
    assert len(t['rows']) == 1 and t['rows'][0][4] == 2                            # one story, 2 outlets
    summary = next(c for c in out['conclusions'] if c['statement'].startswith('AAA ("Acme Robotics")'))
    assert '2 relevant article(s) in 1 story cluster(s) from 2 outlet(s)' in summary['statement']
    assert summary['level'] == UNCERTAIN and summary['reason_codes'] == ['AGGREGATOR_ONLY']
    story = next(c for c in out['conclusions'] if 'story AAA-1' in c['statement'])
    assert 'reported by 2 outlets (aggregator)' in story['statement']
    assert 'Reuters 2026-10-01T10:00:00+00:00; Bloomberg 2026-10-01T11:00:00+00:00' in story['statement']
    assert '"Acme Robotics wins contract"' in story['statement']
    assert {e['fact'].split(':')[0] for e in story['evidence']} == {'Reuters', 'Bloomberg'}
    cov = table(out, 'Company news queries — coverage')
    assert dict(zip(cov['columns'], cov['rows'][0]))['coverage'] == '100.0%'
    assert not any(t['question'] == 4 and 'query and coverage' in t['title'] for t in out['tables'])


def test_news_every_company_story_is_stated_with_its_outlet_count_up_to_the_cap(monkeypatch):
    monkeypatch.setenv('NEWSAPI_KEY', TEST_KEY)
    monkeypatch.setattr(news, 'MAX_COMPANY_STORY_CONCLUSIONS', 2)
    payload = {'status': 'ok', 'totalResults': 3, 'articles': [
        art('Acme Robotics opens plant', 'Reuters', '2026-10-01T10:00:00Z', 'https://reuters.com/p'),
        art('Acme Robotics shares jump as plant opens', 'Biztoc.com', '2026-10-02T10:00:00Z', 'https://biztoc.com/x/1'),
        art('Acme Robotics names new CFO', 'AP', '2026-10-03T10:00:00Z', 'https://ap.org/cfo')]}
    out = news.build(NewsCtx(), include_global=False, http_get=http_for(company=payload)).as_dict()
    stories = [c for c in out['conclusions'] if 'story AAA-' in c['statement']]
    assert len(stories) == 2                                              # cap 2 of 3 clusters
    assert all('reported by 1 outlet (aggregator)' in c['statement'] for c in stories)
    assert all(c['kind'] == 'aggregator' and c['level'] == UNCERTAIN for c in stories)
    assert '"Acme Robotics opens plant"' in stories[0]['statement']         # earliest first among equals
    assert 'headline not quoted' in stories[1]['statement'] and 'jump' not in stories[1]['statement']
    assert len(table(out, 'AAA — news story clusters (aggregator)')['rows']) == 3      # table stays complete
    assert any('1 further story cluster(s)' in n for n in out['notes'])
    assert_no_causal_wording(out)


def test_news_missing_key_http_error_and_blocked_network(monkeypatch):
    ctx = NewsCtx()                                       # conftest removed NEWSAPI_KEY
    out = news.build(ctx, http_get=http_for()).as_dict()
    assert not out['conclusions']
    reasons = [u['reason'] for u in out['unavailable']]
    assert sum('NEWSAPI_KEY not set: no NewsAPI request made' in r for r in reasons) == 2

    monkeypatch.setenv('NEWSAPI_KEY', TEST_KEY)
    err = {'status': 'error', 'code': 'maximumResultsReached',
           'message': 'Developer accounts are limited to a max of 100 results.'}
    http = FakeHTTP({news.GEO_QUERY: err, '"Acme Robotics"': err}, status=426)
    out = news.build(NewsCtx(), http_get=http).as_dict()
    assert not out['conclusions'] and len(http.calls) == 2
    geo = next(u for u in out['unavailable'] if u['question'] == 4 and 'geopolitical news' in u['item'])
    assert 'NewsAPI HTTP 426 (maximumResultsReached' in geo['reason']
    logged = NewsCtx().db.latest_fetch('NewsAPI', news.endpoint_for(news.request_params(ctx.tm, news.GEO_QUERY)))
    assert logged is None                                 # failed calls are logged but never reused

    out = news.build(NewsCtx(), tickers=['AAA']).as_dict()          # default requests.get: blocked offline
    assert not out['conclusions']
    blocked = [u['reason'] for u in out['unavailable'] if 'NewsAPI query unavailable' in u['reason']]
    assert len(blocked) == 2 and all('network disabled in tests' in r for r in blocked)
    assert TEST_KEY not in json.dumps(out)


def test_news_failed_call_is_logged_as_unavailable(monkeypatch):
    monkeypatch.setenv('NEWSAPI_KEY', TEST_KEY)
    ctx = NewsCtx()
    http = FakeHTTP({news.GEO_QUERY: {'status': 'error', 'code': 'parameterInvalid', 'message': 'too far back'}},
                    status=426)
    news.build(ctx, tickers=[], http_get=http)
    with ctx.db.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM source_fetches WHERE source='NewsAPI'")]
    assert len(rows) == 1 and rows[0]['status'] == UNAVAILABLE and rows[0]['http_status'] == 426
    assert 'parameterInvalid' in rows[0]['error'] and TEST_KEY not in json.dumps(rows)


def test_news_only_after_cutoff_or_irrelevant_articles_is_unavailable(monkeypatch):
    monkeypatch.setenv('NEWSAPI_KEY', TEST_KEY)
    late = {'status': 'ok', 'totalResults': 2, 'articles': [
        art('Acme Robotics recalls robots', 'Reuters', '2026-10-07T09:00:00Z', 'https://reuters.com/late'),
        art('Robots everywhere', 'Wired', '2026-10-03T09:00:00Z', 'https://wired.com/x')]}
    out = news.build(NewsCtx(), include_global=False, http_get=http_for(company=late)).as_dict()
    assert not out['conclusions']
    u = next(u for u in out['unavailable'] if u['scope'] == 'AAA')
    assert 'no relevant article published in the window' in u['reason'] and 'not established' in u['reason']
    assert 'recalls' not in json.dumps(out['tables'])


def test_news_look_ahead_article_evidence_raises():
    ctx = NewsCtx()
    a = {'published_at': '2026-10-07T09:00:00+00:00', 'title': 't', 'outlet': 'o', 'url': 'u'}
    with pytest.raises(LookAheadError):
        news.article_evidence(ctx, a, {'fetch_id': 1, 'retrieved_at': RETRIEVED})


def test_news_same_generic_title_keeps_topic_membership_per_article(monkeypatch):
    monkeypatch.setenv('NEWSAPI_KEY', TEST_KEY)
    payload = {'status': 'ok', 'totalResults': 2, 'articles': [
        art('Letters to the editor', 'Daily A', '2026-10-01T10:00:00Z', 'https://a.com/letters/1',
            'Readers write about the coming elections.'),
        art('Letters to the editor', 'Gazette B', '2026-10-01T11:00:00Z', 'https://b.com/letters/2',
            'Readers write about new sanctions.')]}
    unique, stats = news.select_articles(NewsCtx().tm, payload, [(l, st) for l, _, st in news.GEO_TOPICS])
    assert len(unique) == 1 and stats['duplicates'] == 1                 # identical headline: folded (counted once)
    assert unique[0]['topics'] == ['elections']                          # the copy's topic is not lent to it
    assert unique[0]['copies'][0]['topics'] == ['sanctions']
    out = news.build(NewsCtx(), tickers=[], http_get=http_for(geo=payload)).as_dict()
    sanctions = next(c for c in out['conclusions'] if "topic 'sanctions'" in c['statement'])
    assert [e['fact'] for e in sanctions['evidence']] == ['Gazette B: "Letters to the editor" (https://b.com/letters/2)']
    assert sanctions['evidence'][0]['published_at'] == '2026-10-01T11:00:00+00:00'
    elections = next(c for c in out['conclusions'] if "topic 'elections'" in c['statement'])
    assert [e['fact'].split(':')[0] for e in elections['evidence']] == ['Daily A']
    topics = {r[0]: r for r in table(out, 'Geopolitical news — pre-declared topics')['rows']}
    assert topics['sanctions'][3] == 1 and topics['sanctions'][6] == 1 and topics['elections'][3] == 1


def test_news_same_canonical_url_with_different_titles_is_not_a_duplicate():
    tm = NewsCtx().tm
    terms = [('Acme Robotics', ('Acme Robotics',))]
    payload = {'articles': [   # consent-wall URLs: one path, the query identifies the article
        art('Acme Robotics shares rally while tech slides', 'Yahoo Entertainment', '2026-10-01T10:00:00Z',
            'https://consent.yahoo.com/v2/collectConsent?sessionId=3_cc-session_aaa'),
        art('Acme Robotics names new CFO', 'Yahoo Entertainment', '2026-10-01T11:00:00Z',
            'https://consent.yahoo.com/v2/collectConsent?sessionId=3_cc-session_bbb'),
        art('Show HN: Acme Robotics arm kit', 'Ycombinator.com', '2026-10-01T12:00:00Z',
            'https://news.ycombinator.com/item?id=1'),
        art('Ask HN: is Acme Robotics hiring?', 'Ycombinator.com', '2026-10-01T13:00:00Z',
            'https://news.ycombinator.com/item?id=2')]}
    unique, stats = news.select_articles(tm, payload, terms)
    assert stats['kept'] == 4 and stats['duplicates'] == 0
    # same canonical URL and a similar (updated) headline: one article
    payload = {'articles': [
        art('Acme Robotics wins contract', 'Reuters', '2026-10-01T10:00:00Z', 'https://reuters.com/a'),
        art('Acme Robotics wins Navy contract', 'Reuters', '2026-10-01T11:00:00Z', 'https://reuters.com/a?upd=1'),
        # syndicated copy of the UPDATED headline at another URL: recognised through the registered title
        art('Acme Robotics wins Navy contract', 'Yahoo Finance', '2026-10-01T12:00:00Z', 'https://finance.yahoo.com/x')]}
    unique, stats = news.select_articles(tm, payload, terms)
    assert stats['kept'] == 1 and stats['duplicates'] == 2
    clusters = news.cluster(unique, 'AAA-')
    assert [(c['id'], c['outlets']) for c in clusters] == [('AAA-1', ['Reuters'])]
    assert [cp['outlet'] for cp in clusters[0]['copies']] == ['Reuters', 'Yahoo Finance']


def test_news_complete_window_with_truncated_results_is_partial(monkeypatch):
    monkeypatch.setenv('NEWSAPI_KEY', TEST_KEY)
    ctx = NewsCtx(cutoff='2026-10-02T12:00:00+00:00', generated='2026-10-03T12:00:00+00:00')
    assert ctx.tm.news_complete()
    out = news.build(ctx, include_global=False, http_get=http_for(company=company_payload(total=10))).as_dict()
    assert out['conclusions']
    for c in out['conclusions']:
        assert 'PARTIAL_COVERAGE' in c['reason_codes'] and c['level'] == UNCERTAIN
    cov = table(out, 'Company news queries — coverage')
    assert dict(zip(cov['columns'], cov['rows'][0]))['coverage'] == '40.0%'


class Clock:
    """Controls the completion time the database records for a fetch (offline reuse tests)."""

    def __init__(self, monkeypatch):
        self.now = None
        monkeypatch.setattr(database_module, 'utc_now_iso', lambda: self.now)


@pytest.mark.parametrize('stored_at, generated, reused', [
    ('2026-10-08T01:00:00+00:00', '2026-10-08T08:00:00+00:00', False),   # window complete; fetch made before T_c + 26 h
    ('2026-10-08T07:30:00+00:00', '2026-10-08T08:00:00+00:00', True),    # window complete; fetch made after T_c + 26 h
    ('2026-10-07T07:00:00+00:00', '2026-10-07T20:00:00+00:00', False),   # window incomplete; fetch 13 h old
    ('2026-10-07T09:00:00+00:00', '2026-10-07T20:00:00+00:00', True),    # window incomplete; fetch 11 h old
    ('2026-10-07T04:00:00+00:00', '2026-10-07T12:00:00+00:00', False),   # fetch made before the cutoff T_c
])
def test_news_stored_fetch_reuse_age_bounds(monkeypatch, stored_at, generated, reused):
    monkeypatch.setenv('NEWSAPI_KEY', TEST_KEY)
    clock = Clock(monkeypatch)
    clock.now = stored_at
    store = NewsCtx(generated=stored_at)
    assert news.fetch_query(store, news.GEO_QUERY, http_for())['status'] == 'OK'

    clock.now = generated
    ctx = NewsCtx(generated=generated)
    assert ctx.tm.cutoff == '2026-10-07T05:00:00+00:00'
    http = http_for()
    out = news.build(ctx, tickers=[], http_get=http).as_dict()
    cov = table(out, 'Geopolitical news — query and coverage')
    row = dict(zip(cov['columns'], cov['rows'][0]))
    assert len(http.calls) == (0 if reused else 1)
    assert row['reused stored fetch'] == ('yes' if reused else 'no')
    assert row['retrieved at'] == (stored_at if reused else generated)


def test_news_helpers():
    assert news.canonical_url('https://www.Reuters.com/a/1/?utm=x#f') == 'reuters.com/a/1'
    assert news.canonical_url('https://slashdot.org/firehose.pl?op=view&amp;id=5') == 'slashdot.org/firehose.pl?id=5&op=view'
    assert news.canonical_url('https://slashdot.org/firehose.pl?id=6&op=view') != \
        news.canonical_url('https://slashdot.org/firehose.pl?op=view&id=5')
    assert news.normalized_title('Chips: US widens curbs - Reuters', 'Reuters') == 'chips us widens curbs'
    assert news.jaccard({'a', 'b', 'c'}, {'a', 'b', 'd'}) == pytest.approx(0.5)
    assert news.code_host('https://gist.github.com/x', 'X') and news.code_host('https://a.b/c', 'Pypi.org')
    assert not news.quotable('Shares fall as tariffs bite') and not news.quotable('Prices rose due to tariffs')
    assert not news.quotable('Deal boosts backlog') and not news.quotable('Imports pushed the deficit higher')
    assert news.quotable('Parliament sets snap elections')
    assert not news.quotable('BlackBerry Advances 5% on Continued QNX Momentum; Palo Alto Networks Gains 4%, '
                             'CrowdStrike Edges Up 2%')
    assert not news.quotable('Stock declines 4% after earnings')
    assert not news.quotable('Shares 3% higher on deal') and not news.quotable('Acme edges lower amid selloff')
    assert not news.quotable('Acme rebounds after guidance') and not news.quotable('Acme dips following report')
    assert news.quotable('Acme Robotics names new CFO') and news.quotable('US expands export controls on chips')
