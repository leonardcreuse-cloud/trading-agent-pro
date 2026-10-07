"""Weekly report sections 'catalysts' (Q9) and 'quant' (Q10, Q11) - offline tests on a fake context.

All prices, filings, FRED calendars, XBRL values, Form 4 rows, daily-run files and walk-forward results
below are SYNTHETIC: they exist only to check calculation, point-in-time and evidence-level logic and
never reach a report.
"""

import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.common import end_of_us_trading_day_utc, to_utc_iso
from src.database import Database, freshness
from src.insider_tracker import FORM4_METRIC, form4_xml_url, insider_score
from src.price_technical import PriceTechnical
from src.scoring_fundamentals import ScoringFundamentals
from src.scoring_signal_fixed import ScoringSignalFixed
from src.weekly.core import STRONG, UNAVAILABLE, UNCERTAIN, LookAheadError, TimeModel
from src.weekly.sections import catalysts, quant
from tests.conftest import FakeResponse

ALL_SESSIONS = [d.date().isoformat() for d in pd.bdate_range(end='2026-10-09', periods=900)]
CUTOFF = '2026-10-07T12:00:00+00:00'          # s_0 = 2026-10-06, T_c = 2026-10-07T05:00Z, T_p = 2026-09-30T05:00Z
GENERATED = '2026-10-07T13:00:00+00:00'
T_C, T_P = '2026-10-07T05:00:00+00:00', '2026-09-30T05:00:00+00:00'
RETRIEVED = '2026-10-07T13:00:00+00:00'       # fake fetches made after the cutoff
CIK = '0000000042'
WEEKLY = {'benchmark': 'SPY', 'thresholds_version': 'test-v1', 'thresholds': {'abs_excess_return_z': 2.0}}
CAUSAL = ('because', 'due to', 'drove', 'driven by', 'on the back of', 'caused')


# ---------------------------------------------------------------- fakes

class FakeDB:
    def __init__(self, events=None, stored_urls=()):
        self._events = events or {}
        self.stored_urls = set(stored_urls)

    def events(self, entity, metric, published_from=None, published_to=None, source=None):
        lo, hi = to_utc_iso(published_from), to_utc_iso(published_to)
        rows = [r for r in self._events.get((entity, metric), [])
                if (lo is None or r['available_at'] > lo) and (hi is None or r['available_at'] <= hi)]
        return sorted(rows, key=lambda r: r['available_at'])

    def latest_fetch(self, source, endpoint, since=None):
        return {'fetch_id': 99, 'retrieved_at': RETRIEVED} if endpoint in self.stored_urls else None


class FakeSEC:
    def __init__(self, db, versions=None):
        self.db = db
        self.versions = versions or {}
        self.calls = []

    def get_cik(self, ticker):
        return CIK

    def fundamentals(self, ticker, known_at=None):
        self.calls.append((ticker, to_utc_iso(known_at)))
        known = [v for pub, v in self.versions.get(ticker, []) if pub <= to_utc_iso(known_at)]
        if not known:
            return {'status': UNAVAILABLE, 'revenue': None, 'revenue_growth_pct': None, 'debt_to_equity': None,
                    'fetch': None, 'reason': 'SEC XBRL company facts unavailable: test'}
        return dict(known[-1], status='OK', fetch={'fetch_id': 9, 'retrieved_at': RETRIEVED})


class FakeCtx:
    def __init__(self, prices=None, filings=None, sec=None, db=None, universe=('AAA',), weekly=None):
        self.tm = TimeModel(ALL_SESSIONS, CUTOFF, GENERATED)
        self._prices = prices or {}
        self._filings = filings or {}
        self.db = db if db is not None else FakeDB()
        self.sec = sec or FakeSEC(self.db)
        self.universe = list(universe)
        self.weekly = weekly or json.loads(json.dumps(WEEKLY))

    def prices(self, ticker):
        return self._prices.get(ticker) or {'status': UNAVAILABLE, 'frame': None, 'fetch': None,
                                            'reason': 'yfinance returned no data'}

    def filings(self, ticker):
        return self._filings.get(ticker) or {'status': UNAVAILABLE, 'filings': [], 'fetch': None,
                                             'reason': 'CIK not found for test'}

    def freshness(self, as_of, cadence):
        return freshness(as_of, cadence, now=datetime.fromisoformat(self.tm.cutoff))


def price_frame(seed=1, after=1e6):
    """Random-walk adjusted closes up to s_0, then absurd bars AFTER s_0 (look-ahead bait)."""
    n = ALL_SESSIONS.index('2026-10-06') + 1
    rng = np.random.default_rng(seed)
    closes = list(100 * np.exp(np.cumsum(rng.normal(0, 0.02, n))))
    closes += [after] * (len(ALL_SESSIONS) - n)
    idx = pd.to_datetime(ALL_SESSIONS)
    return pd.DataFrame({'close': closes, 'close_raw': closes, 'volume': 1e6}, index=idx)


def ok_prices(frame):
    return {'status': 'OK', 'frame': frame, 'fetch': {'fetch_id': 1, 'retrieved_at': RETRIEVED}, 'reason': None}


def filing(form, filing_date, report_date=None, accession=None, items=(), published_at=None, doc='doc.xml'):
    return {'form': form, 'filing_date': filing_date, 'report_date': report_date,
            'accession_number': accession or f'{form}-{filing_date}',
            'primary_document': doc, 'items': list(items),
            'published_at': published_at or to_utc_iso(f'{filing_date}T21:00:00+00:00'),
            'published_at_basis': 'test acceptance time', 'acceptance_utc': None}


def feed(rows, retrieved=RETRIEVED):
    return {'status': 'OK', 'filings': rows, 'fetch': {'fetch_id': 5, 'retrieved_at': retrieved}, 'reason': None,
            'retrieved_after_cutoff': retrieved > T_C}


PERIODIC = [filing('10-K', '2025-03-10', '2025-01-31'), filing('10-Q', '2025-06-03', '2025-04-30'),
            filing('10-Q', '2025-08-27', '2025-07-31'), filing('10-Q', '2025-12-02', '2025-10-31'),
            filing('8-K', '2025-12-02', '2025-12-02', items=['2.02', '9.01']),
            filing('10-K', '2026-03-10', '2026-01-31'), filing('10-Q', '2026-06-02', '2026-04-30'),
            filing('10-Q', '2026-08-27', '2026-07-31')]


def form4(day, accession):
    return filing('4', day, day, accession=accession, doc='xslF345X05/form4.xml')


def txn_event(day, code, owner, published, plan=False):
    return {'as_of_date': day, 'available_at': published,
            'value_text': json.dumps({'accession': f'acc-{day}-{owner}', 'code': code, 'owners': [owner],
                                      'rule_10b5_1': plan, 'value_usd': 1000.0, 'date': day})}


def fund_version(rev, growth, de, pub):
    return {'revenue': rev, 'revenue_growth_pct': growth, 'debt_to_equity': de, 'revenue_period_end': '2026-07-31',
            'balance_sheet_date': '2026-07-31', 'revenue_published_at': pub, 'reason': None}


def quant_ctx(news_entry=None, extra_filings=(), missing_doc=False, versions=None, prices=True, **kw):
    """One ticker AAA with all inputs available; a buy at T_c window only, sales in both windows."""
    f4 = [form4('2026-09-02', 'f4-a'), form4('2026-09-25', 'f4-b'), form4('2026-10-02', 'f4-c'),
          form4('2026-10-08', 'f4-late')]                          # f4-late: accepted after T_c
    rows = PERIODIC + f4 + list(extra_filings)
    stored = {form4_xml_url(CIK, f['accession_number'], f['primary_document']) for f in f4}
    if missing_doc:
        stored.discard(form4_xml_url(CIK, 'f4-c', 'xslF345X05/form4.xml'))
    ev = [txn_event('2026-09-02', 'S', 'Alice', '2026-09-02T21:00:00+00:00'),
          txn_event('2026-09-25', 'S', 'Bob', '2026-09-25T21:00:00+00:00'),
          txn_event('2026-10-02', 'P', 'Carol', '2026-10-02T21:00:00+00:00'),
          txn_event('2026-10-08', 'P', 'Dan', '2026-10-08T21:00:00+00:00')]   # after T_c: never counted
    db = FakeDB(events={('AAA', FORM4_METRIC): ev}, stored_urls=stored)
    sec = FakeSEC(db, versions if versions is not None else {'AAA': [
        ('2026-06-02T21:00:00+00:00', fund_version(9e8, 12.0, 0.8, '2026-06-02T21:00:00+00:00')),
        ('2026-10-01T21:00:00+00:00', fund_version(1.2e9, 35.0, 0.4, '2026-10-01T21:00:00+00:00')),   # in the week
        ('2026-10-08T21:00:00+00:00', fund_version(1e8, -50.0, 5.0, '2026-10-08T21:00:00+00:00'))]})
    ctx = FakeCtx(prices={'AAA': ok_prices(price_frame())} if prices else {}, filings={'AAA': feed(rows)},
                  sec=sec, db=db, **kw)
    return ctx


def write_json(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def wf_payload(computed_at, ic5=0.0115, t5=0.79, ic20=0.0198, t20=0.8):
    def horizon(ic, t):
        return {'ic_pooled': {c: {'ic': 0.0, 'significant': False} for c in ('technical', 'combined')},
                'ic_cross_sectional': {'combined': {'mean_ic': ic, 't_stat': t, 'significant': abs(t) >= 2}},
                'folds_with_positive_ic': '4/10'}
    return {'computed_at': computed_at, 'status': 'OK', 'method': 'walk_forward_heuristic_v1',
            'universe': [f'T{i}' for i in range(40)],
            'protocol': {'excluded': {'news': 'no history'}, 'components': ['technical', 'fundamentals', 'insider',
                                                                           'combined']},
            'metrics': {'5d': horizon(ic5, t5), '20d': horizon(ic20, t20)}, 'model': {}}


def research_payload(computed_at, n=205):
    return {'stage': 1, 'computed_at': computed_at, 'universe': {'n_stocks_with_data': 148},
            'feature_tests': [{'significant_bh': False, 'significant_bonferroni': False}] * n}


def run_quant(ctx, tmp_path, wf_at='2026-10-06T09:00:00+00:00', analysis=None, research_at=None, **kw):
    wf = write_json(tmp_path, 'wf.json', wf_payload(wf_at, **kw)) if wf_at else tmp_path / 'missing_wf.json'
    research = {1: write_json(tmp_path, 'r1.json', research_payload(research_at)) if research_at
                else tmp_path / 'none1.json', 2: tmp_path / 'none2.json'}
    a = write_json(tmp_path, 'analysis.json', analysis) if analysis is not None else tmp_path / 'none.json'
    return quant.build(ctx, analysis_path=a, walk_forward_path=wf, research_paths=research).as_dict()


def table(out, title):
    return next(t for t in out['tables'] if t['title'] == title)


def rows_by_first(t):
    return {r[0]: dict(zip(t['columns'], r)) for r in t['rows']}


def expected_scores(ctx, session, at):
    close = ctx.prices('AAA')['frame']['close']
    close = close[[d.date().isoformat() <= session for d in close.index]]
    tech = PriceTechnical().score_closes(close.to_numpy())['technical_score']
    fund, _ = ScoringFundamentals(ctx.sec).score_inputs(ctx.sec.fundamentals('AAA', known_at=at))
    return tech, fund


def all_statements(out):
    return [c['statement'] for c in out['conclusions']] + [u['reason'] for u in out['unavailable']]


# ---------------------------------------------------------------- quant (Q10)

def test_quant_values_match_production_code_point_in_time(tmp_path):
    ctx = quant_ctx()
    out = run_quant(ctx, tmp_path)
    assert out['name'] == 'quant' and out['questions'] == [10, 11]
    sig = ScoringSignalFixed()
    tech_c, fund_c = expected_scores(ctx, '2026-10-06', T_C)
    tech_p, fund_p = expected_scores(ctx, '2026-09-29', T_P)
    assert fund_c == ScoringFundamentals(None).score_inputs(fund_version(1.2e9, 35.0, 0.4, None))[0]  # not the 10-08 version
    assert fund_p == ScoringFundamentals(None).score_inputs(fund_version(9e8, 12.0, 0.8, None))[0]
    # insider: T_c window has Carol's purchase (Dan's 10-08 purchase is after T_c); T_p window: sales only
    ins_c = insider_score({'distinct_buyers': 1, 'discretionary_sellers': 2})
    ins_p = insider_score({'distinct_buyers': 0, 'discretionary_sellers': 1})
    assert (ins_c, ins_p) == (60, 45)
    s_c = sig.combine_scores({'technical': tech_c, 'fundamentals': fund_c, 'insider': ins_c})
    s_p = sig.combine_scores({'technical': tech_p, 'fundamentals': fund_p, 'insider': ins_p})

    comps = rows_by_first(table(out, 'AAA — components and contributions (renormalized weights)'))
    assert comps['technical']['score T_c'] == pytest.approx(tech_c)
    assert comps['technical']['score T_p'] == pytest.approx(tech_p)
    assert comps['fundamentals']['score T_c'] == pytest.approx(fund_c)
    assert comps['insider']['score T_c'] == ins_c and comps['insider']['score T_p'] == ins_p
    assert comps['news']['score T_c'] is None and comps['news']['score T_p'] is None   # never a neutral 50
    w = {k: sig.WEIGHTS[k] / 0.80 for k in ('technical', 'fundamentals', 'insider')}
    assert comps['fundamentals']['ex-news weight T_c'] == pytest.approx(round(w['fundamentals'], 4))
    total = sum(comps[k]['ex-news contribution T_c'] for k in ('technical', 'fundamentals', 'insider'))
    assert total == pytest.approx(s_c, abs=0.01)

    sig_table = table(out, 'AAA — heuristic signal at T_p and T_c (ex-news variant first)')
    ex = dict(zip(sig_table['columns'], sig_table['rows'][0]))
    assert sig_table['rows'][0][0].startswith('ex-news')                      # ex-news shown first
    assert ex['S(T_c)'] == s_c and ex['S(T_p)'] == s_p
    assert ex['label T_c'] == sig.generate_final_signal(s_c)
    assert ex['coverage T_c'] == '3/3'
    thr = 65 if abs(s_c - 65) <= abs(s_c - 40) else 40
    assert ex['nearest threshold at T_c'] == thr and ex['distance to it (points)'] == pytest.approx(round(s_c - thr, 2))
    assert ex['borderline (no pre-declared band)'] is None                    # no band in config: not assessed

    dec = [r for r in table(out, 'AAA — delta decomposition S(T_c) - S(T_p)')['rows'] if r[0] == 'ex-news']
    effects = {r[1]: r[4] for r in dec}
    assert effects['total delta S'] == pytest.approx(s_c - s_p, abs=0.01)
    assert effects['coverage effect (components present at one cutoff only)'] == pytest.approx(0, abs=1e-9)
    assert sum(v for k, v in effects.items() if k.startswith('score effect')) == pytest.approx(s_c - s_p, abs=0.01)
    assert effects['score effect: insider'] == pytest.approx(0.15 / 0.80 * (60 - 45), abs=1e-3)

    # all fundamentals reads were point-in-time at T_c or T_p
    assert {k for _, k in ctx.sec.calls} <= {T_C, T_P}


def test_quant_levels_and_kinds(tmp_path):
    out = run_quant(quant_ctx(), tmp_path)
    aaa = [c for c in out['conclusions'] if c['scope'] == 'AAA' and c['question'] == 10]
    ex = next(c for c in aaa if 'ex-news variant' in c['statement'] and c['kind'] == 'system_output')
    assert ex['level'] == STRONG and ex['reason_codes'] == []                 # statement about the system
    live = next(c for c in aaa if 'live variant' in c['statement'])
    assert live['kind'] == 'system_output' and live['level'] == UNCERTAIN
    assert live['reason_codes'] == ['PARTIAL_COVERAGE'] and 'identical to the ex-news variant' in live['statement']
    model = next(c for c in aaa if c['kind'] == 'model_output')
    assert model['level'] == UNCERTAIN and {'MODEL_NOT_VALIDATED', 'HEURISTIC_THRESHOLD'} <= set(model['reason_codes'])
    assert 'not a probability' in model['statement']
    assert all(c['kind'] != 'system_output' or 'the stock' in c['statement'] or c['scope'] == 'overall'
               or 'data reliability' in c['statement'] for c in out['conclusions'])
    for s in all_statements(out):
        assert not any(w in s.lower() for w in CAUSAL), s
        assert 'P(up)' not in s and 'probability of' not in s.lower()
    # evidence: technical from yfinance (rank 2), fundamentals / insider SEC (rank 1); nothing after T_c
    assert {e['source'] for e in ex['evidence']} == {'yfinance', 'SEC EDGAR'}
    assert all(e['published_at'] <= T_C for c in out['conclusions'] for e in c['evidence'])


def test_quant_news_only_from_daily_run_at_or_before_cutoff(tmp_path):
    late = [{'ticker': 'AAA', 'timestamp': '2026-10-07T09:30:00+00:00',
             'modules': {'news': {'news_score': 70.0, 'newest_article_published_at': '2026-10-06T05:00:00Z'}}}]
    out = run_quant(quant_ctx(), tmp_path, analysis=late)
    comps = rows_by_first(table(out, 'AAA — components and contributions (renormalized weights)'))
    assert comps['news']['score T_c'] is None and 'after the cutoff' in comps['news']['T_c inputs']

    early = [{'ticker': 'AAA', 'timestamp': '2026-10-07T04:00:00+00:00',
              'modules': {'news': {'news_score': 70.0, 'articles_count': 50,
                                   'newest_article_published_at': '2026-10-06T05:00:00Z',
                                   'provenance': {'fetch_id': 3, 'retrieved_at': '2026-10-07T03:59:00+00:00'}}}}]
    ctx = quant_ctx()
    out = run_quant(ctx, tmp_path, analysis=early)
    comps = rows_by_first(table(out, 'AAA — components and contributions (renormalized weights)'))
    assert comps['news']['score T_c'] == 70.0 and comps['news']['score T_p'] is None
    sig_rows = table(out, 'AAA — heuristic signal at T_p and T_c (ex-news variant first)')['rows']
    ex, live = (dict(zip(table(out, 'AAA — heuristic signal at T_p and T_c (ex-news variant first)')['columns'], r))
                for r in sig_rows)
    tech_c, fund_c = expected_scores(ctx, '2026-10-06', T_C)
    sig = ScoringSignalFixed()
    assert live['S(T_c)'] == sig.combine_scores({'technical': tech_c, 'fundamentals': fund_c, 'news': 70.0,
                                                 'insider': 60})
    assert live['coverage T_c'] == '4/4' and ex['coverage T_c'] == '3/3'
    assert ex['S(T_c)'] == sig.combine_scores({'technical': tech_c, 'fundamentals': fund_c, 'insider': 60})
    dec = {r[1]: r[4] for r in table(out, 'AAA — delta decomposition S(T_c) - S(T_p)')['rows'] if r[0] == 'live'}
    assert dec['coverage effect (components present at one cutoff only)'] != pytest.approx(0)   # news only at T_c
    news_ev = [e for c in out['conclusions'] for e in c['evidence'] if e['source'] == 'NewsAPI']
    assert news_ev and all(e['rank'] == 3 for e in news_ev)


def test_quant_insider_unavailable_when_a_form4_document_is_not_stored(tmp_path):
    out = run_quant(quant_ctx(missing_doc=True), tmp_path)
    comps = rows_by_first(table(out, 'AAA — components and contributions (renormalized weights)'))
    assert comps['insider']['score T_c'] is None                             # not a neutral 50
    assert 'no stored document' in comps['insider']['T_c inputs']
    assert comps['insider']['score T_p'] == 45                                # T_p window is fully stored


def test_quant_insufficient_data_and_missing_inputs(tmp_path):
    out = run_quant(quant_ctx(prices=False, versions={}), tmp_path)
    items = {(u['scope'], u['item']): u['reason'] for u in out['unavailable']}
    assert 'INSUFFICIENT DATA' in items[('AAA', 'ex-news heuristic signal at T_c')]
    assert 'yfinance prices unavailable' in items[('AAA', 'ex-news heuristic signal at T_c')]
    sig_row = table(out, 'AAA — heuristic signal at T_p and T_c (ex-news variant first)')['rows'][0]
    assert sig_row[4] is None and sig_row[5] == 'INSUFFICIENT DATA'
    overall = next(c for c in out['conclusions'] if c['scope'] == 'overall' and c['question'] == 10)
    assert '1 INSUFFICIENT DATA' in overall['statement'] and 'PARTIAL_COVERAGE' in overall['reason_codes']


def test_quant_look_ahead_input_is_an_audit_failure(tmp_path):
    bad = {'AAA': [('2026-08-27T21:00:00+00:00', fund_version(1.2e9, 35.0, 0.4, '2026-10-08T21:00:00+00:00'))]}
    with pytest.raises(LookAheadError):
        run_quant(quant_ctx(versions=bad), tmp_path)


# ---------------------------------------------------------------- quant (Q11)

def test_validation_banner_strong_when_admissible_and_not_demonstrated(tmp_path):
    out = run_quant(quant_ctx(), tmp_path, research_at='2026-10-06T12:00:00+00:00')
    banner = [c for c in out['conclusions'] if c.get('banner')]
    assert len(banner) == 1
    b = banner[0]
    assert b['question'] == 11 and b['kind'] == 'system_output' and b['level'] == STRONG
    assert 'NOT demonstrated statistically significant predictive power' in b['statement']
    assert 'WITHOUT news' in b['statement'] and 'news component (weight 0.20)' in b['statement']
    assert 'research stage 1 (148 stocks' in b['statement'] and 'Stage 2 holdout results: DATA UNAVAILABLE' in b['statement']
    t = table(out, 'Walk-forward validation of the ex-news combined score (cross-sectional IC)')
    r5 = dict(zip(t['columns'], t['rows'][0]))
    assert r5['horizon'] == '5d' and r5['significant after correction'] == 'no'
    assert r5['required p (0.05 / k)'] == 0.025
    lo, hi = 0.0115 - 1.96 * 0.0115 / 0.79, 0.0115 + 1.96 * 0.0115 / 0.79
    assert r5['approx. 95% interval (IC +/- 1.96 IC/t)'] == f'[{lo:+.4f}, {hi:+.4f}]'
    interp = [c for c in out['conclusions'] if c['kind'] == 'interpretation' and c['question'] == 11]
    assert interp and all(c['level'] == UNCERTAIN for c in interp)
    items = {u['item']: u['reason'] for u in out['unavailable'] if u['question'] == 11}
    for field in ('model_prediction', 'prediction_confidence', 'risk_score'):
        assert items[field].startswith('NOT IMPLEMENTED')
    assert 'research stage 2 results' in items and 'per-company signal reliability' in items
    rel = next(c for c in out['conclusions'] if c['scope'] == 'AAA' and c['question'] == 11)
    assert 'data reliability' in rel['statement'] and rel['kind'] == 'system_output'
    assert 'PARTIAL_COVERAGE' in rel['reason_codes']                         # news missing: 3/4


def test_validation_run_after_cutoff_is_not_admissible(tmp_path):
    out = run_quant(quant_ctx(), tmp_path, wf_at='2026-10-07T09:15:00+00:00',
                    research_at='2026-10-07T12:15:00+00:00')
    b = next(c for c in out['conclusions'] if c.get('banner'))
    assert b['level'] == STRONG and b['evidence'] == []
    assert 'No walk-forward validation is available' in b['statement']
    assert 'research stage 1' not in b['statement']                          # computed after T_c: excluded
    items = {u['item']: u['reason'] for u in out['unavailable']}
    assert 'computed after' in items['walk-forward validation run admissible at the cutoff']
    assert 'after the cutoff' in items['research stage 1 results at the cutoff']
    t = table(out, 'Walk-forward validation of the ex-news combined score (cross-sectional IC)')
    assert any('computed after the cutoff' in r[0] for r in t['rows'])        # shown, labelled
    assert not [c for c in out['conclusions'] if c['kind'] == 'interpretation' and c['question'] == 11]


def test_validation_stale_run_is_uncertain(tmp_path):
    out = run_quant(quant_ctx(), tmp_path, wf_at='2026-09-20T09:00:00+00:00')
    b = next(c for c in out['conclusions'] if c.get('banner'))
    assert b['level'] == UNCERTAIN and 'STALE_AT_CUTOFF' in b['reason_codes']
    assert 'stale' in b['statement'].lower()


# ---------------------------------------------------------------- catalysts (Q9)

def fred_payload(dates):
    return {'realtime_start': '2026-10-06', 'realtime_end': '9999-12-31', 'count': len(dates),
            'release_dates': [{'release_id': 0, 'date': d} for d in dates]}


CALENDARS = {10: ['2026-10-14', '2026-11-10'], 50: ['2026-11-06'], 54: ['2026-10-29'], 53: ['2026-10-29'],
             9: ['2026-10-15', '2026-11-17'], 180: ['2026-10-08', '2026-10-15', '2026-10-22'],
             326: ['2026-12-09']}


class FredHTTP:
    def __init__(self, calendars=CALENDARS, status=200):
        self.calls, self.calendars, self.status = [], calendars, status

    def __call__(self, url, params=None, timeout=None):
        self.calls.append(dict(params))
        if self.status != 200:
            return FakeResponse({'error_code': self.status, 'error_message': 'Bad Request.'}, self.status)
        return FakeResponse(fred_payload(self.calendars[params['release_id']]))


def store_calendar(db, release_id, start, dates, completed_at):
    endpoint = catalysts.calendar_endpoint(release_id, start)
    fetch = db.record_fetch('FRED', endpoint, params={'release_id': release_id}, requested_at=completed_at,
                            status='OK', raw=fred_payload(dates), n_records=len(dates))
    with db.connect() as conn:
        conn.execute('UPDATE source_fetches SET requested_at=?, completed_at=? WHERE fetch_id=?',
                     (completed_at, completed_at, fetch['fetch_id']))
    return fetch['fetch_id']


def cat_ctx(filings=None, db=None):
    db = db or Database()
    return FakeCtx(db=db, filings={'AAA': feed(filings if filings is not None else PERIODIC)})


def no_calendar(_t):
    return {}


def run_cat(ctx, http=None, calendar_fn=no_calendar):
    return catalysts.build(ctx, http_get=http or FredHTTP(), calendar_fn=calendar_fn).as_dict()


def macro_rows(out):
    t = next(t for t in out['tables'] if t['title'].startswith('Macro release calendar'))
    return {r[1]: dict(zip(t['columns'], r)) for r in t['rows']}


def test_catalysts_calendar_retrieved_after_cutoff_is_logged_but_not_admissible(monkeypatch):
    monkeypatch.setenv('FRED_API_KEY', 'testkey-abcdef123')
    db = Database()
    http = FredHTTP()
    out = run_cat(cat_ctx(db=db), http)
    assert out['name'] == 'catalysts' and out['questions'] == [9]
    assert len(http.calls) == len(catalysts.RELEASES) == 7
    assert all(c['realtime_start'] == '2026-10-06' and c['include_release_dates_with_no_data'] == 'true'
               for c in http.calls)
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM source_fetches WHERE source='FRED'")]
    assert len(rows) == 7 and all(r['status'] == 'OK' and r['raw_path'] for r in rows)
    assert all('testkey-abcdef123' not in json.dumps(r) for r in rows)        # key never stored
    assert 'testkey-abcdef123' not in json.dumps(out)
    m = macro_rows(out)
    assert m[10]['dates in horizon as retrieved at G (after the cutoff, information only)'] == '2026-10-14 (Wed)'
    assert m[180]['dates in horizon as retrieved at G (after the cutoff, information only)'] == \
        '2026-10-08 (Thu), 2026-10-15 (Thu)'                                  # 10-22 is after s_0 + 15 days
    assert m[10]['dates in horizon (as known at T_c)'] is None and m[10]['status at T_c'] == UNAVAILABLE
    assert not [c for c in out['conclusions'] if c['question'] == 9 and c['kind'] == 'official_fact']
    reasons = {u['item']: u['reason'] for u in out['unavailable']}
    assert 'no FRED release calendar stored at or before the cutoff' in \
        reasons['Consumer Price Index (FRED release 10): schedule as known at the cutoff']
    assert 'federalreserve.gov' in reasons['FOMC meetings without a Summary of Economic Projections']
    assert 'not observed' in reasons['exchange session calendar for the 10 sessions after s_0']
    # an identical request stored < 12 h before G is reused: no new request
    http2 = FredHTTP()
    run_cat(cat_ctx(db=db), http2)
    assert http2.calls == []


def test_catalysts_scheduled_from_calendar_stored_before_cutoff(monkeypatch):
    monkeypatch.setenv('FRED_API_KEY', 'testkey-abcdef123')
    db = Database()
    pit = dict(CALENDARS)
    pit[9] = ['2026-11-17']                                                    # retail 10-15 added after T_c
    for rid, dates in pit.items():
        store_calendar(db, rid, '2026-10-06', dates, '2026-10-06T12:00:00+00:00')
    store_calendar(db, 10, '2026-09-29', ['2026-10-13', '2026-11-10'], '2026-09-29T12:00:00+00:00')  # T_p calendar
    store_calendar(db, 50, '2026-10-06', ['2026-10-09'], '2026-10-07T06:00:00+00:00')   # after T_c: never used
    out = run_cat(cat_ctx(db=db))
    by = {c['statement'].split(' (FRED release')[0]: c for c in out['conclusions'] if c['kind'] == 'official_fact'
          and 'differs from the one known at T_p' not in c['statement']}
    cpi = by['Consumer Price Index']
    assert cpi['level'] == STRONG and 'SCHEDULED on 2026-10-14' in cpi['statement']
    assert 'time of day not provided' in cpi['statement']
    assert cpi['evidence'][0]['rank'] == 1 and cpi['evidence'][0]['retrieved_at'] <= T_C
    claims = by['Unemployment Insurance Weekly Claims Report']
    assert 'SCHEDULED on 2026-10-08, 2026-10-15' in claims['statement']
    emp = by['Employment Situation']
    assert 'no date in the horizon' in emp['statement'] and 'next scheduled date 2026-11-06' in emp['statement']
    retail = by['Advance Monthly Sales for Retail and Food Services']
    assert 'next scheduled date 2026-11-17' in retail['statement']             # G-only date never concluded
    m = macro_rows(out)
    assert m[9]['change T_c -> G'] == 'added 2026-10-15'
    assert m[10]['change T_p -> T_c'] == 'added 2026-10-14; removed 2026-10-13'
    change = next(c for c in out['conclusions'] if 'differs from the one known at T_p' in c['statement'])
    assert change['level'] == STRONG and len(change['evidence']) == 2
    fomc = next(c for c in out['conclusions'] if 'Summary of Economic Projections' in c['statement']
                and c['kind'] == 'official_fact')
    assert 'next scheduled date 2026-12-09' in fomc['statement']
    for s in all_statements(out):
        assert not any(w in s.lower() for w in CAUSAL), s


def test_catalysts_stale_stored_calendar_is_uncertain(monkeypatch):
    monkeypatch.setenv('FRED_API_KEY', 'testkey-abcdef123')
    db = Database()
    store_calendar(db, 10, '2026-09-10', ['2026-10-14'], '2026-09-10T12:00:00+00:00')   # 27 days before T_c
    out = run_cat(cat_ctx(db=db))
    cpi = next(c for c in out['conclusions'] if c['statement'].startswith('Consumer Price Index'))
    assert cpi['level'] == UNCERTAIN and 'STALE_AT_CUTOFF' in cpi['reason_codes']


def test_catalysts_without_key_or_with_http_error(monkeypatch):
    http = FredHTTP()
    out = run_cat(cat_ctx(), http)
    assert http.calls == []                                                    # FRED_API_KEY not set
    m = macro_rows(out)
    assert 'FRED_API_KEY not set' in m[10]['fetch at G']
    monkeypatch.setenv('FRED_API_KEY', 'testkey-abcdef123')
    db = Database()
    out = run_cat(cat_ctx(db=db), FredHTTP(status=400))
    assert 'FRED HTTP 400: Bad Request.' in macro_rows(out)[10]['fetch at G']
    with db.connect() as conn:
        failed = conn.execute("SELECT COUNT(*) FROM source_fetches WHERE source='FRED' AND status=?",
                              (UNAVAILABLE,)).fetchone()[0]
    assert failed == 7


def test_catalysts_earnings_calendar_empty_or_failing_is_unavailable(monkeypatch):
    out = run_cat(cat_ctx(), calendar_fn=no_calendar)
    r = {u['item']: u['reason'] for u in out['unavailable'] if u['scope'] == 'AAA'}
    assert 'empty result' in r['next earnings date'] and 'not as "none"' in r['next earnings date']

    def boom(_t):
        raise ConnectionError('crumb host blocked')
    out = run_cat(cat_ctx(), calendar_fn=boom)
    r = {u['item']: u['reason'] for u in out['unavailable'] if u['scope'] == 'AAA'}
    assert 'ConnectionError' in r['next earnings date']
    out = run_cat(cat_ctx(), calendar_fn=lambda _t: {'Earnings Date': [date(2026, 10, 20)]})
    t = next(t for t in out['tables'] if t['title'].startswith('AAA — company catalysts'))
    row = next(r for r in t['rows'] if r[0] == 'next earnings date')
    assert row[1].startswith('REPORTED') and row[3] == '2026-10-20'
    r = {u['item']: u['reason'] for u in out['unavailable'] if u['scope'] == 'AAA'}
    assert 'retrieved after the cutoff' in r['next earnings date (as known at the cutoff)']
    assert not [c for c in out['conclusions'] if c['scope'] == 'AAA' and 'earnings date' in c['statement'].lower()]


def test_catalysts_pattern_row_is_an_interpretation_not_a_forecast():
    late = filing('10-Q', '2026-10-08', '2026-08-31', published_at='2026-10-08T21:00:00+00:00')  # after T_c
    out = run_cat(cat_ctx(filings=PERIODIC + [late]))
    p = next(c for c in out['conclusions'] if c['scope'] == 'AAA')
    assert p['kind'] == 'interpretation' and p['level'] == UNCERTAIN
    assert {'ESTIMATE', 'INTERPRETIVE'} <= set(p['reason_codes'])
    assert p['statement'].startswith('AAA: pattern, not a forecast')
    assert 'latest 10-Q, period 2026-07-31' in p['statement']                 # the post-cutoff 10-Q is ignored
    assert 'the 10-Q for the period ended 2025-10-31, filed on 2025-12-02' in p['statement']
    assert '8-K item 2.02 (results of operations) filed on 2025-12-02' in p['statement']
    assert 'fall outside the horizon (2026-10-06, 2026-10-21]' in p['statement']
    assert all(e['source'] == 'SEC EDGAR' and e['rank'] == 1 for e in p['evidence'])

    inside = [f for f in PERIODIC if f['report_date'] != '2025-10-31'] + [filing('10-Q', '2025-10-15', '2025-09-30')]
    out = run_cat(cat_ctx(filings=inside))
    p = next(c for c in out['conclusions'] if c['scope'] == 'AAA')
    assert 'filed on 2025-10-15' in p['statement'] and 'fall inside the horizon' in p['statement']
    assert 'no 8-K item 2.02 found' in p['statement']


def test_catalysts_pattern_unavailable_without_year_earlier_filing():
    out = run_cat(cat_ctx(filings=[filing('10-Q', '2026-08-27', '2026-07-31')]))
    r = {u['item']: u['reason'] for u in out['unavailable'] if u['scope'] == 'AAA'}
    assert 'one year before 2026-07-31' in r['periodic filing pattern (same filing one year earlier)']
    out = run_cat(FakeCtx(db=Database()))                                       # no submissions feed
    r = {u['item']: u['reason'] for u in out['unavailable'] if u['scope'] == 'AAA'}
    assert 'SEC submissions feed unavailable' in r['periodic filing pattern']


def test_catalysts_horizon_uses_calendar_dates():
    tm = TimeModel(ALL_SESSIONS, CUTOFF, GENERATED)
    assert catalysts.horizon(tm) == (date(2026, 10, 6), date(2026, 10, 21))
    assert not catalysts.in_horizon(tm, '2026-10-06') and catalysts.in_horizon(tm, '2026-10-07')
    assert catalysts.in_horizon(tm, '2026-10-21') and not catalysts.in_horizon(tm, '2026-10-22')
