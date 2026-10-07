"""
Phase P0.3 - SEC XBRL fundamentals and Form 4 insider transactions (offline).

Payloads are small synthetic SEC documents shaped like the real endpoints; they only
check parsing and calculation logic and never reach a report outside tmp_path.
"""

from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import FakeResponse

CIK = '0001801368'


def fact(val, end, start=None, form='10-Q', filed='2026-08-07', accn='acc-q2'):
    row = {'val': val, 'end': end, 'form': form, 'filed': filed, 'accn': accn}
    if start:
        row['start'] = start
    return row


REVENUE = 'RevenueFromContractWithCustomerExcludingAssessedTax'


def companyfacts(revenue=None, equity=None, extra=None):
    gaap = {
        REVENUE: {'units': {'USD': revenue if revenue is not None else [
            fact(118_203_000, '2025-06-30', '2025-01-01', filed='2025-08-08', accn='acc-q2-25'),
            fact(224_441_000, '2025-12-31', '2025-01-01', form='10-K', filed='2026-02-26', accn='acc-k-25'),
            fact(180_000_000, '2024-12-31', '2024-01-01', form='10-K', filed='2025-02-20', accn='acc-k-24'),
            fact(100_000_000, '2024-06-30', '2024-01-01', filed='2024-08-08', accn='acc-q2-24'),
            fact(199_139_000, '2026-06-30', '2026-01-01'),
            fact(108_490_000, '2026-06-30', '2026-04-01'),
            fact(118_203_000, '2025-06-30', '2025-01-01'),          # comparative in the 2026 10-Q
            fact(999, '2026-06-30', '2026-01-01', form='8-K'),       # not a periodic form: ignored
        ]}},
        'StockholdersEquity': {'units': {'USD': equity if equity is not None else [
            fact(1_900_000_000, '2025-12-31', form='10-K', filed='2026-02-26', accn='acc-k-25'),
            fact(1_957_336_000, '2026-06-30')]}},
        'LongTermDebt': {'units': {'USD': [
            fact(930_000_000, '2025-12-31', form='10-K', filed='2026-02-26', accn='acc-k-25'),
            fact(934_583_000, '2026-06-30')]}},
    }
    gaap.update(extra or {})
    return {'cik': int(CIK), 'facts': {'us-gaap': gaap}}


def iso_z(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')


def submissions(form4s=()):
    """Submissions feed: the 10-Q acc-q2 plus Form 4 filings [(accession, days_ago, document)]."""
    forms, filed, report, accn, accepted, docs = ['10-Q'], ['2026-08-07'], ['2026-06-30'], \
        ['acc-q2'], ['2026-08-06T22:15:49.000Z'], ['mp-20260630.htm']
    now = datetime.now(timezone.utc)
    for accession, days_ago, document in form4s:
        when = now - timedelta(days=days_ago)
        forms.append('4')
        filed.append(when.strftime('%Y-%m-%d'))
        report.append('')
        accn.append(accession)
        accepted.append(iso_z(when))
        docs.append(f'xslF345X06/{document}')
    return {'filings': {'recent': {'form': forms, 'filingDate': filed, 'reportDate': report,
                                   'accessionNumber': accn, 'acceptanceDateTime': accepted,
                                   'primaryDocument': docs}}}


def form4_xml(transactions, plan=True, owner='Doe Jane', officer=True):
    rows = ''.join(f"""
        <nonDerivativeTransaction>
            <securityTitle><value>Common Stock</value></securityTitle>
            <transactionDate><value>{date}</value></transactionDate>
            <transactionCoding><transactionFormType>4</transactionFormType>
                <transactionCode>{code}</transactionCode></transactionCoding>
            <transactionAmounts>
                <transactionShares><value>{shares}</value></transactionShares>
                <transactionPricePerShare><value>{price}</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>{'A' if code in 'PAM' else 'D'}</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>""" for code, date, shares, price in transactions)
    plan_xml = '' if plan is None else f'<aff10b5One>{1 if plan else 0}</aff10b5One>'
    return f"""<?xml version="1.0"?>
<ownershipDocument>
    <documentType>4</documentType>
    <issuer><issuerCik>{CIK}</issuerCik><issuerTradingSymbol>MP</issuerTradingSymbol></issuer>
    <reportingOwner>
        <reportingOwnerId><rptOwnerCik>0000000001</rptOwnerCik><rptOwnerName>{owner}</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><isDirector>false</isDirector><isOfficer>{str(officer).lower()}</isOfficer>
            <officerTitle>CFO</officerTitle></reportingOwnerRelationship>
    </reportingOwner>
    {plan_xml}
    <nonDerivativeTable>{rows}</nonDerivativeTable>
</ownershipDocument>"""


class FakeTextResponse(FakeResponse):
    @property
    def text(self):
        return self._payload

    @property
    def content(self):
        return self._payload.encode('utf-8')


@pytest.fixture
def sec(monkeypatch):
    """Fake SEC endpoints; returns (payloads dict, list of requested URLs)."""
    monkeypatch.setenv('SEC_USER_AGENT', 'TestAgent test@example.com')
    monkeypatch.setattr('src.sec_parser.time.sleep', lambda s: None)
    payloads = {
        'company_tickers.json': {'0': {'cik_str': int(CIK), 'ticker': 'MP', 'title': 'MP Materials'}},
        f'submissions/CIK{CIK}.json': submissions(),
        f'companyfacts/CIK{CIK}.json': companyfacts(),
    }
    calls = []

    def fake_get(self, url, timeout=None):
        calls.append(url)
        for key, payload in payloads.items():
            if url.endswith(key):
                return FakeTextResponse(payload) if isinstance(payload, str) else FakeResponse(payload)
        return FakeResponse({}, 404)

    monkeypatch.setattr('requests.Session.get', fake_get)
    return payloads, calls


# ---------------------------------------------------------------- XBRL helpers

def test_duration_months_classifies_quarters_ytd_and_years():
    from src.sec_xbrl import duration_months
    assert duration_months('2026-04-01', '2026-06-30') == 3
    assert duration_months('2026-01-01', '2026-06-30') == 6
    assert duration_months('2025-02-01', '2026-01-31') == 12
    assert duration_months('2025-02-03', '2026-02-01') == 12      # 52/53-week year
    assert duration_months('2026-01-01', '2026-01-31') is None


def test_facts_to_observations_filters_forms_and_uses_acceptance_time():
    from src.sec_xbrl import facts_to_observations
    rows = facts_to_observations('MP', companyfacts(),
                                 {'acc-q2': ('2026-08-07T02:15:49+00:00', 'acceptance')})
    assert all(r['value'] != 999 for r in rows)                    # 8-K fact ignored
    q2 = [r for r in rows if r['metric'] == f'xbrl:{REVENUE}:3M']
    assert q2[0]['published_at'] == '2026-08-07T02:15:49+00:00'
    k25 = next(r for r in rows if r['metric'] == f'xbrl:{REVENUE}:12M' and r['as_of_date'] == '2025-12-31')
    assert k25['published_at'] == '2026-02-27T05:00:00+00:00'      # end of filed date
    assert 'conservative' in k25['published_at_basis']
    assert any(r['metric'] == 'xbrl:StockholdersEquity' and r['value_text'] is None for r in rows)


def test_ttm_from_fiscal_year_plus_ytd_minus_prior_ytd():
    from src.sec_xbrl import ttm_at

    def row(v, start):
        return {'value': v, 'value_text': start}
    durations = {12: {'2025-12-31': row(224_441_000, '2025-01-01')},
                 6: {'2026-06-30': row(199_139_000, '2026-01-01'),
                     '2025-06-30': row(118_203_000, '2025-01-01')}}
    ttm = ttm_at(durations, '2026-06-30')
    assert ttm['value'] == 224_441_000 + 199_139_000 - 118_203_000
    assert ttm_at(durations, '2025-12-31')['value'] == 224_441_000   # annual fact used as is
    del durations[6]['2025-06-30']
    assert ttm_at(durations, '2026-06-30') is None                  # never guessed


def test_debt_uses_first_reported_definition_and_never_defaults_to_zero():
    from src.sec_xbrl import debt_at
    d = '2026-06-30'
    instants = {'ConvertibleDebtNoncurrent': {d: {'value': 2_000.0}},
                'ConvertibleDebtCurrent': {d: {'value': 1_000.0}}}
    assert debt_at(instants, d) == {'value': 3_000.0,
                                    'tags': ['ConvertibleDebtNoncurrent', 'ConvertibleDebtCurrent']}
    instants['LongTermDebt'] = {d: {'value': 500.0}}
    assert debt_at(instants, d)['tags'] == ['LongTermDebt']
    assert debt_at({}, d) is None


# ---------------------------------------------------------------- SECParser.fundamentals

def test_fundamentals_from_company_facts(sec):
    from src.sec_parser import SECParser
    result = SECParser().run('MP')
    assert result['revenue'] == 305_377_000
    assert result['revenue_ttm_period_end'] == '2026-06-30'
    # prior TTM at 2025-06-30 = FY2024 180M + 6M 2025 118.203M - 6M 2024 100M
    assert result['revenue_growth_pct'] == round((305_377_000 / 198_203_000 - 1) * 100, 2)
    assert result['debt_to_equity'] == round(934_583_000 / 1_957_336_000, 3)
    assert result['debt_tags'] == ['LongTermDebt']
    assert result['financials_status']['status'] == 'OK'
    assert result['financials_provenance']['source'] == 'SEC EDGAR'


def test_fundamentals_are_point_in_time(sec):
    from src.sec_parser import SECParser
    parser = SECParser()
    before_q2 = parser.fundamentals('MP', known_at='2026-08-01T00:00:00+00:00')
    assert before_q2['revenue_period_end'] == '2025-12-31'          # 10-Q not public yet
    assert before_q2['revenue'] == 224_441_000
    assert before_q2['balance_sheet_date'] == '2025-12-31'
    assert parser.fundamentals('MP', known_at='2024-01-01T00:00:00+00:00')['revenue'] is None


def test_restated_fact_is_a_new_version_and_old_value_stays_point_in_time(sec):
    from src.sec_parser import SECParser
    payloads, _ = sec
    first = SECParser()
    first.fundamentals('MP')
    facts = companyfacts()
    facts['facts']['us-gaap'][REVENUE]['units']['USD'].append(
        fact(230_000_000, '2025-12-31', '2025-01-01', form='10-K/A', filed='2026-09-15', accn='acc-ka'))
    payloads[f'companyfacts/CIK{CIK}.json'] = facts
    second = SECParser(db=first.db)
    second.db.latest_fetch = lambda *a, **k: None                 # force a new download
    second.fundamentals('MP')
    metric = f'xbrl:{REVENUE}:12M'
    latest = dict(second.db.series('MP', metric, source='SEC EDGAR'))
    assert latest['2025-12-31']['value'] == 230_000_000
    before = dict(second.db.series('MP', metric, source='SEC EDGAR',
                                   known_at='2026-09-01T00:00:00+00:00'))
    assert before['2025-12-31']['value'] == 224_441_000            # original 10-K version kept


def test_negative_equity_gives_no_debt_to_equity(sec):
    from src.sec_parser import SECParser
    payloads, _ = sec
    payloads[f'companyfacts/CIK{CIK}.json'] = companyfacts(equity=[fact(-5_000_000, '2026-06-30')])
    fin = SECParser().fundamentals('MP')
    assert fin['debt_to_equity'] is None
    assert 'not meaningful' in fin['reason']
    assert fin['revenue'] == 305_377_000


def test_company_facts_unavailable_is_explicit(sec):
    from src.sec_parser import SECParser
    payloads, _ = sec
    del payloads[f'companyfacts/CIK{CIK}.json']
    from src.scoring_fundamentals import ScoringFundamentals
    result = ScoringFundamentals(SECParser()).analyze('MP')
    assert result['fundamental_score'] is None and result['status'] == 'DATA UNAVAILABLE'
    assert 'company facts unavailable' in result['reason']


def test_company_facts_are_reused_within_12_hours(sec):
    from src.sec_parser import SECParser
    _, calls = sec
    first = SECParser()
    first.fundamentals('MP')
    second = SECParser(db=first.db)
    fin = second.fundamentals('MP')
    assert fin['revenue'] == 305_377_000
    assert sum('companyfacts' in u for u in calls) == 1
    assert fin['fetch']['reused'] is True


def test_fundamental_score_uses_three_components(sec):
    from src.scoring_fundamentals import ScoringFundamentals
    from src.sec_parser import SECParser
    result = ScoringFundamentals(SECParser()).analyze('MP')
    assert result['coverage'] == '3/3'
    assert result['components'] == {'revenue_scale': 60, 'revenue_growth': 85, 'leverage': 90}
    assert result['status'] == 'OK'


# ---------------------------------------------------------------- Form 4

def test_parse_form4_reads_owner_plan_flag_and_transactions():
    from src.insider_tracker import parse_form4
    doc = parse_form4(form4_xml([('S', '2026-09-01', 100, 25.5), ('M', '2026-09-01', 50, 0)]))
    assert doc['rule_10b5_1'] is True
    assert doc['owners'][0]['name'] == 'Doe Jane' and 'officer' in doc['owners'][0]['roles']
    sale, exercise = doc['transactions']
    assert sale == {'date': '2026-09-01', 'code': 'S', 'acquired_disposed': 'D', 'shares': 100.0,
                    'price': 25.5, 'value_usd': 2550.0, 'security': 'Common Stock'}
    assert exercise['value_usd'] is None                          # zero price: no value invented
    assert parse_form4(form4_xml([], plan=None))['rule_10b5_1'] is None


def test_form4_xml_url_points_to_raw_document():
    from src.insider_tracker import form4_xml_url
    assert form4_xml_url('0001801368', '0001801368-26-000052', 'xslF345X06/wk-form4_1.xml') == \
        'https://www.sec.gov/Archives/edgar/data/1801368/000180136826000052/wk-form4_1.xml'


def add_form4(payloads, filings):
    """filings: [(accession, days_ago, xml)]"""
    payloads[f'submissions/CIK{CIK}.json'] = submissions(
        [(a, d, f'f4-{a}.xml') for a, d, _ in filings])
    for accession, _, xml in filings:
        payloads[f"{accession.replace('-', '')}/f4-{accession}.xml"] = xml


def test_insider_buys_by_two_insiders_score_bullish(sec):
    from src.insider_tracker import InsiderTracker
    payloads, _ = sec
    add_form4(payloads, [
        ('a-1', 5, form4_xml([('P', '2026-09-01', 1000, 20.0)], plan=False, owner='A')),
        ('a-2', 10, form4_xml([('P', '2026-08-25', 500, 21.0)], plan=False, owner='B')),
        ('a-3', 200, form4_xml([('S', '2026-03-01', 9999, 20.0)], plan=False, owner='C')),  # outside window
    ])
    result = InsiderTracker().run('MP')
    assert result['status'] == 'OK'
    assert result['form4_filings_window'] == 2
    assert result['insider_buys'] == 2 and result['distinct_buyers'] == 2
    assert result['buy_value_usd'] == 30_500.0 and result['insider_sells'] == 0
    assert result['insider_score'] == 70 and result['signal'] == 'POSITIVE'


def test_planned_sales_are_neutral_and_discretionary_sales_bearish(sec):
    from src.insider_tracker import InsiderTracker
    payloads, _ = sec
    add_form4(payloads, [('p-1', 5, form4_xml([('S', '2026-09-01', 100, 20.0)], plan=True))])
    planned = InsiderTracker().run('MP')
    assert planned['planned_sell_value_usd'] == 2000.0 and planned['insider_score'] == 50

    add_form4(payloads, [('d-1', 5, form4_xml([('S', '2026-09-01', 100, 20.0)], plan=None))])
    discretionary = InsiderTracker().run('MP')                     # unknown plan status
    assert discretionary['discretionary_sell_value_usd'] == 2000.0
    assert discretionary['insider_score'] == 45


def test_grants_and_exercises_are_not_scored(sec):
    from src.insider_tracker import InsiderTracker
    payloads, _ = sec
    add_form4(payloads, [('g-1', 5, form4_xml([('A', '2026-09-01', 5000, 0), ('F', '2026-09-01', 900, 20.0)]))])
    result = InsiderTracker().run('MP')
    assert result['insider_buys'] == 0 and result['insider_sells'] == 0
    assert result['other_transaction_codes'] == {'A': 1, 'F': 1}
    assert result['insider_score'] == 50


def test_form4_documents_downloaded_once_and_transactions_not_duplicated(sec):
    from src.insider_tracker import InsiderTracker
    payloads, calls = sec
    add_form4(payloads, [('o-1', 5, form4_xml([('P', '2026-09-01', 10, 20.0)]))])
    tracker = InsiderTracker()
    tracker.run('MP')
    again = InsiderTracker(sec_parser=type(tracker.sec)(db=tracker.db)).run('MP')
    assert sum(u.endswith('f4-o-1.xml') for u in calls) == 1
    assert again['insider_buys'] == 1


def test_insider_window_is_point_in_time(sec):
    from src.insider_tracker import InsiderTracker
    payloads, _ = sec
    add_form4(payloads, [('t-1', 5, form4_xml([('P', '2026-09-01', 10, 20.0)]))])
    tracker = InsiderTracker()
    tracker.run('MP')
    earlier = datetime.now(timezone.utc) - timedelta(days=10)
    assert tracker.summarize('MP', known_at=earlier)['insider_buys'] == 0


def test_unreadable_form4_documents_make_insider_unavailable(sec):
    from src.insider_tracker import InsiderTracker
    payloads, _ = sec
    payloads[f'submissions/CIK{CIK}.json'] = submissions([('x-1', 5, 'missing.xml')])
    result = InsiderTracker().run('MP')
    assert result['status'] == 'DATA UNAVAILABLE'
    assert result['insider_score'] is None and result['signal'] is None


def test_partial_form4_failures_are_provisional(sec):
    from src.insider_tracker import InsiderTracker
    payloads, _ = sec
    add_form4(payloads, [('ok-1', 5, form4_xml([('P', '2026-09-01', 10, 20.0)]))])
    payloads[f'submissions/CIK{CIK}.json'] = submissions(
        [('ok-1', 5, 'f4-ok-1.xml'), ('ko-1', 6, 'missing.xml')])
    result = InsiderTracker().run('MP')
    assert result['status'] == 'PROVISIONAL' and result['warning']
    assert result['insider_buys'] == 1


# ---------------------------------------------------------------- combined signal

def test_signal_includes_insider_component():
    from src.scoring_signal_fixed import ScoringSignalFixed
    result = ScoringSignalFixed().analyze('MP', {'technical_score': 60}, {'fundamental_score': 70},
                                          {'news_score': 50}, {'insider_score': 40})
    assert result['coverage'] == '4/4'
    assert result['signal_strength'] == round(60 * .25 + 70 * .40 + 50 * .20 + 40 * .15, 2)
