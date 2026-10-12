"""
Master mission P1: extended fundamentals, valuation ratios, intrinsic-value scenarios, commodities and event analysis.

All company figures below are SYNTHETIC facts written to an isolated database (logic tests only, never a report).
"""

import json
import math
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

PUB = '2026-08-01T20:00:00+00:00'


# ---------------------------------------------------------------- frozen definitions (stage 3)

def test_frozen_signal_definitions_are_unchanged():
    """The heuristic recorded by stage 3 (protocol stage3-v1) reads revenue, growth and debt / equity through these
    definitions: a change here changes the recorded signal (docs/research/STAGE3_PREREGISTRATION.md)."""
    from src import sec_xbrl as x
    assert x.REVENUE_TAGS == ('Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
                              'RevenueFromContractWithCustomerIncludingAssessedTax', 'SalesRevenueNet')
    assert x.EQUITY_TAGS == ('StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest')
    assert x.SHORT_TERM_TAGS == ('ShortTermBorrowings', 'CommercialPaper')
    assert [d[0] for d in x.DEBT_DEFINITIONS] == ['combined_total', 'long_term_debt_total', 'long_term_debt_split',
                                                  'debt_and_finance_leases', 'notes_and_loans', 'convertible']
    assert not set(x.EXT_INSTANT_TAGS + x.EXT_DURATION_TAGS) & set(x.REVENUE_TAGS + x.EQUITY_TAGS + x.DEBT_TAGS)


# ---------------------------------------------------------------- XBRL helpers

def test_quarter_from_fact_or_derived_at_year_end():
    from src.fundamentals_ext import quarter_at
    d = {3: {'2026-06-30': {'value': 30.0, 'value_text': '2026-04-01'}},
         9: {'2025-09-30': {'value': 90.0, 'value_text': '2025-01-01'}},
         12: {'2025-12-31': {'value': 125.0, 'value_text': '2025-01-01'}}}
    assert quarter_at(d, '2026-06-30')['value'] == 30.0
    q4 = quarter_at(d, '2025-12-31')
    assert q4['value'] == 35.0 and 'derived' in q4['method']
    d[9]['2025-09-30']['value_text'] = '2024-10-01'                 # another fiscal year: not combined
    assert quarter_at(d, '2025-12-31') is None


def test_cover_page_shares_single_classes_and_ambiguous():
    from src.sec_xbrl import shares_outstanding_observations
    def fact(val, accn, end='2026-07-25'):
        return {'val': val, 'end': end, 'accn': accn, 'form': '10-Q', 'filed': '2026-07-30'}
    facts = {'facts': {'dei': {'EntityCommonStockSharesOutstanding': {'units': {'shares': [
        fact(100, 'a-1'), fact(60, 'a-2'), fact(40, 'a-2'), fact(5, 'a-3'), fact(5, 'a-3')]}}}}}
    rows = {r['value_text'] or 'single': r for r in shares_outstanding_observations('AAA', facts, {'a-1': (PUB, 'acc')})}
    assert rows['single']['value'] == 100 and rows['single']['published_at'] == PUB
    assert rows['sum of 2 values (share classes)']['value'] == 100           # two distinct class counts
    assert len(rows) == 2                                                     # repeated values (a-3): skipped


# ---------------------------------------------------------------- extended fundamentals on stored facts

def _store_company(db):
    """SYNTHETIC facts of a company with fiscal years = calendar years."""
    rows = []

    def flow(tag, months, end, value, start, unit='USD'):
        rows.append({'entity': 'AAA', 'metric': f'xbrl:{tag}:{months}M', 'as_of_date': end, 'value': value,
                     'value_text': start, 'unit': unit, 'published_at': PUB, 'published_at_basis': 'test'})

    def inst(tag, end, value, unit='USD'):
        rows.append({'entity': 'AAA', 'metric': f'xbrl:{tag}', 'as_of_date': end, 'value': value, 'unit': unit,
                     'published_at': PUB, 'published_at_basis': 'test'})
    for year, rev in ((2022, 700.0), (2023, 800.0), (2024, 900.0), (2025, 1000.0)):
        flow('Revenues', 12, f'{year}-12-31', rev, f'{year}-01-01')
        flow('NetIncomeLoss', 12, f'{year}-12-31', rev * 0.1, f'{year}-01-01')
        flow('OperatingIncomeLoss', 12, f'{year}-12-31', rev * 0.15, f'{year}-01-01')
        flow('GrossProfit', 12, f'{year}-12-31', rev * 0.5, f'{year}-01-01')
        flow('NetCashProvidedByUsedInOperatingActivities', 12, f'{year}-12-31', rev * 0.2, f'{year}-01-01')
        flow('PaymentsToAcquirePropertyPlantAndEquipment', 12, f'{year}-12-31', rev * 0.05, f'{year}-01-01')
        flow('DepreciationDepletionAndAmortization', 12, f'{year}-12-31', rev * 0.04, f'{year}-01-01')
        flow('EarningsPerShareDiluted', 12, f'{year}-12-31', rev * 0.1 / 100, f'{year}-01-01', 'USD/shares')
    for year, ytd, q in ((2024, 430.0, 220.0), (2025, 480.0, 250.0), (2026, 540.0, 280.0)):
        flow('Revenues', 6, f'{year}-06-30', ytd, f'{year}-01-01')
        flow('Revenues', 3, f'{year}-06-30', q, f'{year}-04-01')
        for tag, share in (('NetIncomeLoss', 0.1), ('OperatingIncomeLoss', 0.15), ('GrossProfit', 0.55 if year == 2026 else 0.5),
                           ('NetCashProvidedByUsedInOperatingActivities', 0.2),
                           ('PaymentsToAcquirePropertyPlantAndEquipment', 0.05),
                           ('DepreciationDepletionAndAmortization', 0.04)):
            flow(tag, 6, f'{year}-06-30', ytd * share, f'{year}-01-01')
        flow('EarningsPerShareDiluted', 6, f'{year}-06-30', ytd * 0.1 / 100, f'{year}-01-01', 'USD/shares')
        flow('WeightedAverageNumberOfDilutedSharesOutstanding', 3, f'{year}-06-30', 100.0, f'{year}-04-01', 'shares')
        inst('StockholdersEquity', f'{year}-06-30', 400.0 if year == 2025 else 500.0)
        inst('LongTermDebt', f'{year}-06-30', 300.0)
        inst('CashAndCashEquivalentsAtCarryingValue', f'{year}-06-30', 120.0)
        inst('ShortTermInvestments', f'{year}-06-30', 30.0)
        inst('AssetsCurrent', f'{year}-06-30', 400.0)
        inst('LiabilitiesCurrent', f'{year}-06-30', 200.0)
        rows.append({'entity': 'AAA', 'metric': 'dei:SharesOutstanding', 'as_of_date': f'{year}-07-25', 'value': 100.0,
                     'unit': 'shares', 'published_at': PUB.replace('2026', str(year)), 'published_at_basis': 'test'})
    fetch = db.record_fetch('SEC EDGAR', 'test:companyfacts/AAA', status='OK')
    db.upsert_observations(fetch, rows)
    return fetch


@pytest.fixture
def sec(monkeypatch):
    from src.database import Database
    from src.sec_parser import SECParser
    db = Database()
    fetch = _store_company(db)
    parser = SECParser(db=db)
    monkeypatch.setattr(parser, 'ingest_company_facts', lambda t: fetch)
    return parser


def test_extended_fundamentals_formulas(sec):
    from src.fundamentals_ext import extended, revenue_years_ago
    X = extended(sec, 'AAA', '2026-09-01T00:00:00+00:00')
    assert X['revenue'] == 1060.0                                   # 1000 + 540 - 480
    assert X['revenue_q'] == 280.0 and X['revenue_q_yoy_pct'] == 12.0
    assert X['gross_margin_pct'] == pytest.approx(52.55, abs=0.01)
    assert X['gross_margin_pct_change_pts'] == pytest.approx(2.55, abs=0.01)   # vs FY 2025 (50%)
    assert X['eps_diluted_ttm'] == pytest.approx(1.06) and X['eps_method'].startswith('approximate (FY')
    assert X['cash'] == 120.0 and X['short_term_investments'] == 30.0 and X['net_debt'] == 150.0
    assert X['current_ratio'] == 2.0 and X['equity_prior_year'] == 400.0
    assert X['ebitda_ttm'] == pytest.approx(1060 * 0.15 + 1060 * 0.04)
    assert X['cash_conversion'] == 2.0 and X['cash_runway_years'] is None
    assert X['shares_outstanding'] == 100.0 and X['shares_outstanding_change_pct'] == 0.0
    assert X['guidance'] is None and X['guidance_status'].startswith('NOT IMPLEMENTED')
    assert revenue_years_ago(sec, 'AAA', X, 3) is None              # 2023-06 TTM not computable (no 6M 2023)
    assert extended(sec, 'AAA', '2026-07-01T00:00:00+00:00')['revenue'] is None   # facts published 2026-08-01


# ---------------------------------------------------------------- valuation ratios

def test_valuation_ratios_formulas_and_guards(sec):
    from src.fundamentals_ext import extended
    from src.valuation import ratios
    X = extended(sec, 'AAA', '2026-09-01T00:00:00+00:00')
    R = ratios(X, 20.0, '2026-09-01')
    assert R['market_cap']['value'] == 2000 and 'cover-page' in R['shares_basis']
    assert R['enterprise_value']['value'] == 2000 + 300 - 150
    assert R['pe']['value'] == pytest.approx(20 / 1.06, abs=0.01)
    assert R['pb']['value'] == 4.0 and R['roe_pct']['value'] == pytest.approx(106 / 450 * 100, abs=0.01)
    assert R['ev_sales']['value'] == pytest.approx(2150 / 1060, abs=0.01)
    assert R['fcf_yield_pct']['value'] == pytest.approx(1060 * 0.15 / 2000 * 100, abs=0.01)
    tiny = dict(X, eps_diluted_ttm=0.1, ebitda_ttm=-5.0, debt=None)
    T = ratios(tiny, 20.0, '2026-09-01')
    assert T['pe']['value'] is None and 'below 2.0%' in T['pe']['reason']          # 0.1 x 100 shares < 2% of 1060
    assert T['enterprise_value']['value'] is None and 'debt unavailable' in T['enterprise_value']['reason']
    old = ratios(dict(X, shares_outstanding_date='2025-07-25'), 20.0, '2026-09-01')
    assert old['shares'] == 100.0 and old['flags'][0].startswith('approximation: diluted weighted-average')
    split = ratios(dict(X, shares_outstanding_change_pct=300.0), 20.0, '2026-09-01')
    assert 'possible split' in split['flags'][0]
    assert ratios(X, None, '2026-09-01')['market_cap']['value'] is None


def test_history_stops_at_a_suspected_split():
    from src.valuation import history_points, percentile
    closes = {(date(2026, 9, 1) - timedelta(days=d)).isoformat(): 10.0 + d / 100 for d in range(0, 1900, 1)}

    def ext(sec, ticker, known):
        day = known[:10]
        shares = 100.0 if day >= '2025-01-01' else 25.0                       # 4:1 split during 2025
        return {'shares_outstanding': shares, 'shares_outstanding_date': day, 'revenue': 50.0, 'debt': None,
                'equity': 40.0, 'net_income_ttm': 5.0, 'eps_diluted_ttm': 0.05}
    points, note = history_points(None, ext, 'AAA', closes, '2026-09-01', known_at_fn=lambda d: d + 'T21:00:00+00:00')
    assert points[0]['date'] >= '2025-01-01' and note.startswith('history stops at')
    assert percentile(points, 'ps', 50.0)[0] is None or len(points) >= 8


def test_percentile_needs_eight_points():
    from src.valuation import percentile
    pts = [{'ps': v} for v in range(1, 8)]
    assert percentile(pts, 'ps', 5)[0] is None
    assert percentile(pts + [{'ps': 8}], 'ps', 5) == (56.2, 8)


# ---------------------------------------------------------------- intrinsic value

def test_present_value_and_implied_growth():
    from src.intrinsic import implied_growth, present_value
    value, pv, pv_tv, flows = present_value(100.0, 0.10, 0.02, 0.09, 2)
    g1, g2 = 0.10, 0.10 + (0.02 - 0.10) * 1 / 2
    f1, f2 = 100 * (1 + g1), 100 * (1 + g1) * (1 + g2)
    expected_tv = f2 * 1.02 / (0.09 - 0.02) / 1.09 ** 2
    assert flows == pytest.approx([f1, f2]) and pv_tv == pytest.approx(expected_tv)
    assert value == pytest.approx(f1 / 1.09 + f2 / 1.09 ** 2 + expected_tv)
    g = implied_growth(100.0, 3000.0, 0.09, 0.02, 5)
    assert present_value(100.0, g / 100, 0.02, 0.09, 5)[0] == pytest.approx(3000.0, rel=1e-4)
    assert implied_growth(-5.0, 3000.0, 0.09, 0.02, 5) is None


def test_beta_from_weekly_returns():
    from src.intrinsic import beta
    days = pd.bdate_range('2024-01-01', periods=600)
    market, stock, m, s = {}, {}, 100.0, 50.0
    for i, d in enumerate(days):
        r = 0.01 * math.sin(i / 3.0)
        m *= 1 + r
        s *= 1 + 2 * r
        market[d.date().isoformat()], stock[d.date().isoformat()] = m, s
    b, n = beta(stock, market, 104)
    assert n == 104 and b == pytest.approx(2.0, abs=0.1)
    assert beta(dict(list(stock.items())[:100]), market, 104)[0] is None


def test_dcf_reliability_rules():
    from src.intrinsic import dcf
    X = {'free_cash_flow_ttm': 100.0, 'revenue': 1000.0, 'fcf_margin_pct_change_pts': 2.0}
    D = dcf(X, 50.0, 4.0, 1.0, 800.0, {}, 100.0, 'test shares')
    assert D['reliability'] in ('LOW', 'ASSUMPTION-DRIVEN') and set(D['scenarios']) == {'bear', 'base', 'bull'}
    assert D['assumptions']['cost_of_equity_pct'] == 9.0 and 'CAGR' in D['assumptions']['growth_basis']
    assert D['scenarios']['bear']['per_share'] < D['scenarios']['base']['per_share'] < D['scenarios']['bull']['per_share']
    assert len(D['sensitivity']) == 3 and D['implied_growth_pct'] is not None
    assert 'equity_risk_premium_pct' in D['defaulted_settings']
    assert dcf(dict(X, free_cash_flow_ttm=-1.0), 50.0, 4.0, 1.0, 800.0, {}, 100.0, 's')['reliability'] == 'NOT RELIABLE'
    no_rf = dcf(X, 50.0, None, 1.0, 800.0, {}, 100.0, 's')
    assert no_rf['scenarios'] == {} and 'risk-free' in no_rf['reasons'][0]
    flagged = dcf(dict(X, fcf_margin_pct_change_pts=25.0), 50.0, 4.0, 1.0, None, {}, 100.0, 's')
    assert flagged['reliability'] == 'LOW' and any('default' in f for f in flagged['flags'])


# ---------------------------------------------------------------- commodities section

class CommodityCtx:
    def __init__(self, universe=('MP', 'FCX')):
        from src.weekly.core import TimeModel
        sessions = [d.date().isoformat() for d in pd.bdate_range(end='2026-10-09', periods=300)]
        self.tm = TimeModel(sessions, '2026-10-10T12:00:00+00:00', '2026-10-10T12:00:00+00:00')
        self.universe = list(universe)

    def fred(self, sid):
        return {'status': 'OK', 'fetch': {'fetch_id': 1, 'retrieved_at': '2026-10-10T06:00:00+00:00'}}

    def series_at(self, sid, instant):
        months = pd.date_range(end='2026-07-01', periods=24, freq='MS')
        return [(d.date().isoformat(), 100.0 + i) for i, d in enumerate(months)]

    def value_at(self, sid, instant):
        return ('2026-07-01', 123.0, '2026-08-05T05:00:00+00:00')

    def prices(self, ticker):
        idx = pd.bdate_range(end='2026-10-09', periods=300)
        return {'status': 'OK', 'frame': pd.DataFrame({'close': [50.0 + i * 0.1 for i in range(300)]}, index=idx),
                'fetch': {'fetch_id': 2, 'retrieved_at': '2026-10-10T06:00:00+00:00'}}

    def freshness(self, as_of, cadence, at=None):
        from src.database import freshness
        return freshness(as_of, cadence, now=datetime.fromisoformat(at or self.tm.cutoff))


def test_commodities_section_facts_sources_and_exposure():
    from src.weekly.sections import commodities
    out = commodities.build(CommodityCtx(), series=['PCOPPUSDM', 'GC=F', 'HG=F']).as_dict()
    texts = [c['statement'] for c in out['conclusions']]
    assert any(t.startswith('Copper (IMF): 123.00 USD/metric ton (2026-07-01') for t in texts)
    gold = next(c for c in out['conclusions'] if c['statement'].startswith('Gold'))
    assert gold['kind'] == 'market_fact' and 'contract roll' in gold['statement']
    fcx = next(c for c in out['conclusions'] if c['scope'] == 'FCX')
    assert fcx['kind'] == 'interpretation' and 'not estimated' in fcx['statement']
    items = {u['item'] for u in out['unavailable']}
    assert 'rare earth prices (NdPr oxide and others)' in items and 'lithium prices (carbonate / hydroxide)' in items
    assert any(u['scope'] == 'MP' and 'no allowed price source' in u['reason'] for u in out['unavailable'])


# ---------------------------------------------------------------- geopolitical event analysis

def test_event_themes_from_titles():
    from src.weekly.sections.geopolitics import themes_of
    assert themes_of('Additions to the Entity List') == [('semiconductor export controls', ['entity list'])]
    assert [t for t, _ in themes_of("Continuation of Actions: China's Acts Related to Technology Transfer")] == \
        ['China trade measures']
    assert themes_of('National Manufacturing Day, 2026') == []
    assert themes_of('Emergency Tax Relief on Diesel Fuel') == [('energy policy', ['diesel', 'fuel'])]
    assert themes_of('Spacecraft procurement') == []                     # word boundaries: 'space' not in 'spacecraft'


def test_event_analysis_table_and_company_link():
    from src import external_sources as ex
    from src.database import Database
    from src.weekly.sections import geopolitics
    from tests.test_weekly_geopolitics import AFTER, Ctx, fr_search
    db = Database()
    doc = {'publication_date': '2026-10-08', 'type': 'Rule', 'document_number': '2026-99999',
           'title': 'Revisions to the Export Administration Regulations: Advanced Computing Items',
           'action': 'Final rule.', 'html_url': 'https://www.federalregister.gov/d/2026-99999'}
    fr_search(db, 'industry-and-security-bureau', '2026-10-01', [doc])
    ctx = Ctx(db)
    ctx.universe = ['NVDA', 'CRWD']
    out = geopolitics.build(ctx).as_dict()
    table = next(t for t in out['tables'] if t['title'].startswith('Event analysis'))
    row = table['rows'][0]
    assert row[3] == doc['title'] and row[4] == '2026-99999'
    assert 'semiconductor export controls' in row[6] and 'NVDA' in row[8]
    assert row[10] == geopolitics.HORIZON_BY_TYPE['Rule'] and row[11] == geopolitics.EVENT_UNCERTAINTIES
    nvda = next(c for c in out['conclusions'] if c['scope'] == 'NVDA')
    assert nvda['kind'] == 'interpretation' and nvda['level'] == 'UNCERTAIN'
    assert not any(c['scope'] == 'CRWD' for c in out['conclusions'])
