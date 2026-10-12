#!/usr/bin/env python3
"""
Source registry and live probe (master mission 6.3: "for each provider, verify the actual endpoint used, HTTP
status, authentication, data availability, update frequency, licensing and terms of use, rate limits").

REGISTRY lists every provider the production code calls (integrated=True) and the official alternatives that are
not integrated because they were unreachable from the cloud environment (integrated=False). `python main.py sources`
sends one small GET to each probe URL and writes reports/source_check.json: HTTP status, bytes, elapsed time and
error. A reachable endpoint is not proof that the API works for our use (the collectors check payloads); an
unreachable one is reported with its error, never worked around.

Ranks follow docs/DATA_POLICY.md (1 official, 2 secondary, 3 aggregator or third-party compilation). Terms and
rate limits are as documented by each provider; where we have not verified a figure the entry says
'not verified here' instead of guessing. Keys come from .env and never appear in output (redact()).
"""

import json
import time

import requests

from .common import redact, reports_dir, secret_env, utc_now_iso

OFFICIAL, SECONDARY, AGGREGATOR = 1, 2, 3

REGISTRY = [
    # ---------------------------------------------------------------- integrated, official (rank 1)
    {'name': 'SEC EDGAR (submissions, XBRL company facts, filings, Form 4)', 'rank': OFFICIAL, 'integrated': True,
     'probe': 'https://data.sec.gov/submissions/CIK0000320193.json', 'client': 'sec', 'auth': 'none; User-Agent with contact '
     'required (SEC_USER_AGENT)', 'frequency': 'as filed (acceptance time)',
     'terms': 'public; SEC fair-access policy', 'rate_limit': '10 requests per second (SEC fair access)',
     'used_for': 'fundamentals, filings, insider transactions'},
    {'name': 'FRED / ALFRED API (St. Louis Fed)', 'rank': OFFICIAL, 'integrated': True,
     'probe': 'https://api.stlouisfed.org/fred/series?series_id=GDP&file_type=json&api_key={FRED_API_KEY}',
     'client': 'requests',
     'auth': 'API key (FRED_API_KEY)', 'frequency': 'per series (daily to annual), vintages kept',
     'terms': 'FRED terms of use; some series carry third-party copyright (e.g. ICE BofA, S&P)',
     'rate_limit': '120 requests per minute per key', 'used_for': 'macro, rates, spreads, VIX, commodities'},
    {'name': 'BLS Public Data API v2', 'rank': OFFICIAL, 'integrated': True,
     'probe': 'https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0', 'auth': 'API key (BLS_API_KEY) '
     'for v2 limits', 'frequency': 'monthly releases', 'terms': 'public domain (US government)',
     'rate_limit': '500 queries per day, 50 series per query (registered v2)', 'used_for': 'CPI, PPI, jobs'},
    {'name': 'BLS release schedules (web pages)', 'rank': OFFICIAL, 'integrated': True,
     'probe': 'https://www.bls.gov/schedule/', 'auth': 'none', 'frequency': 'yearly schedule, monthly pages',
     'terms': 'public domain (US government)', 'rate_limit': 'not verified here', 'used_for': 'catalyst calendar'},
    {'name': 'BEA API (NIPA)', 'rank': OFFICIAL, 'integrated': True,
     'probe': 'https://apps.bea.gov/api/data?UserID={BEA_API_KEY}&method=GETDATASETLIST&ResultFormat=JSON',
     'auth': 'API key (BEA_API_KEY)', 'frequency': 'monthly / quarterly releases',
     'terms': 'public domain (US government)', 'rate_limit': '100 requests and 100 MB per minute, 30 errors per '
     'minute', 'used_for': 'GDP, PCE, income'},
    {'name': 'EIA API v2', 'rank': OFFICIAL, 'integrated': True,
     'probe': 'https://api.eia.gov/v2/petroleum/pri/spt/data/?api_key={EIA_API_KEY}&frequency=daily&data[0]=value'
              '&facets[series][]=RWTC&length=1&sort[0][column]=period&sort[0][direction]=desc',
     'auth': 'API key (EIA_API_KEY)', 'frequency': 'daily / weekly / monthly', 'terms': 'public domain (US '
     'government)', 'rate_limit': 'not verified here', 'used_for': 'oil, gas, inventories'},
    {'name': 'Federal Reserve FOMC calendar (web page)', 'rank': OFFICIAL, 'integrated': True,
     'probe': 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm', 'auth': 'none',
     'frequency': 'as scheduled', 'terms': 'public domain (US government)', 'rate_limit': 'not verified here',
     'used_for': 'catalyst calendar'},
    {'name': 'CFTC Commitments of Traders (Socrata API)', 'rank': OFFICIAL, 'integrated': True,
     'probe': 'https://publicreporting.cftc.gov/resource/gpe5-46if.json?$limit=1', 'auth': 'none (app token '
     'optional)', 'frequency': 'weekly (Tuesday positions, released Friday)', 'terms': 'public domain (US '
     'government)', 'rate_limit': 'Socrata throttling of anonymous requests (not verified here)',
     'used_for': 'futures positioning'},
    {'name': 'FINRA API (consolidated short interest)', 'rank': OFFICIAL, 'integrated': True,
     'probe': 'https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest', 'auth': 'none for this '
     'public dataset', 'frequency': 'twice a month (settlement dates), published ~8 business days later',
     'terms': 'FINRA terms of use', 'rate_limit': 'not verified here', 'used_for': 'short interest, days to cover'},
    {'name': 'Federal Register API', 'rank': OFFICIAL, 'integrated': True,
     'probe': 'https://www.federalregister.gov/api/v1/documents.json?per_page=1', 'auth': 'none',
     'frequency': 'daily (business days)', 'terms': 'public domain (US government)',
     'rate_limit': 'not verified here', 'used_for': 'sanctions, export controls, tariffs, executive actions'},
    # ---------------------------------------------------------------- integrated, secondary (rank 2)
    {'name': 'Yahoo Finance via yfinance (unofficial)', 'rank': SECONDARY, 'integrated': True,
     'probe': 'yfinance: Ticker(SPY).history(period=5d)', 'client': 'yfinance', 'auth': 'none',
     'frequency': 'daily bars, delayed quotes', 'terms': 'Yahoo terms (personal use); unofficial API, may change '
     'without notice', 'rate_limit': 'undocumented; HTTP 429 observed', 'used_for': 'prices, volumes, splits, '
     'dividends, options chains, earnings dates'},
    {'name': 'Cboe delayed quotes (daily history, website data feed)', 'rank': SECONDARY, 'integrated': True,
     'probe': 'https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/SPY.json', 'auth': 'none',
     'frequency': 'daily bars (split-adjusted), delayed', 'terms': 'Cboe website terms of use (not for '
     'redistribution)', 'rate_limit': 'not verified here', 'used_for': 'second price source (cross-check of '
     'yfinance closes)'},
    {'name': 'Cboe put/call statistics (web page)', 'rank': OFFICIAL, 'integrated': True,
     'probe': 'https://www.cboe.com/markets/us/options/market-statistics/daily', 'auth': 'none',
     'frequency': 'daily', 'terms': 'Cboe website terms of use', 'rate_limit': 'not verified here',
     'used_for': 'put/call ratios (Cboe-listed volume only)'},
    {'name': 'GDELT event files', 'rank': AGGREGATOR, 'integrated': True,
     'probe': 'http://data.gdeltproject.org/events/index.html', 'auth': 'none', 'frequency': 'daily files',
     'terms': 'open (attribution requested)', 'rate_limit': 'HTTP 429 observed on the DOC API',
     'used_for': 'conflict / tension event counts'},
    {'name': 'Geopolitical Risk index (Caldara & Iacoviello)', 'rank': SECONDARY, 'integrated': True,
     'probe': 'https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls', 'auth': 'none',
     'frequency': 'daily index, updated irregularly', 'terms': 'academic dataset, cite the authors',
     'rate_limit': 'not verified here', 'used_for': 'geopolitical risk level'},
    {'name': 'S&P 500 constituents list (datasets on GitHub)', 'rank': AGGREGATOR, 'integrated': True,
     'probe': 'https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv',
     'auth': 'none', 'frequency': 'irregular', 'terms': 'third-party compiled list (see the repository licence)',
     'rate_limit': 'not verified here', 'used_for': 'completed stage 1 / 2 research universes only'},
    # ---------------------------------------------------------------- integrated, aggregator (rank 3)
    {'name': 'NewsAPI (news aggregator)', 'rank': AGGREGATOR, 'integrated': True,
     'probe': 'https://newsapi.org/v2/everything?q=Nvidia&pageSize=1&apiKey={NEWSAPI_KEY}', 'client': 'requests',
     'auth': 'API key (NEWSAPI_KEY)', 'frequency': 'continuous; developer plan delays articles ~24 h, one month '
     'of history', 'terms': 'developer plan: development use only', 'rate_limit': '100 requests per day '
     '(developer plan)', 'used_for': 'news events (never sufficient proof alone)'},
    # ---------------------------------------------------------------- official alternatives, not integrated
    {'name': 'World Bank Indicators API', 'rank': OFFICIAL, 'integrated': False,
     'probe': 'https://api.worldbank.org/v2/country/US/indicator/NY.GDP.MKTP.CD?format=json&per_page=1',
     'auth': 'none', 'frequency': 'annual', 'terms': 'CC BY 4.0', 'rate_limit': 'not verified here',
     'used_for': 'would add: international GDP and commodity prices (Pink Sheet)'},
    {'name': 'ECB Data Portal API', 'rank': OFFICIAL, 'integrated': False,
     'probe': 'https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV?lastNObservations=1'
              '&format=jsondata', 'auth': 'none', 'frequency': 'daily / monthly', 'terms': 'ECB reuse policy',
     'rate_limit': 'not verified here', 'used_for': 'would add: euro-area rates and inflation (FRED ECBDFR used)'},
    {'name': 'US Treasury FiscalData API', 'rank': OFFICIAL, 'integrated': False,
     'probe': 'https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts/mts_table_1'
              '?page%5Bsize%5D=1', 'auth': 'none', 'frequency': 'daily / monthly', 'terms': 'public domain',
     'rate_limit': 'not verified here', 'used_for': 'would add: Treasury statement detail (FRED MTSDS133FMS used)'},
    {'name': 'US Census Bureau API (retail sales)', 'rank': OFFICIAL, 'integrated': False,
     'probe': 'https://api.census.gov/data/timeseries/eits/marts?get=cell_value&time=2026',
     'auth': 'key optional', 'frequency': 'monthly', 'terms': 'public domain',
     'rate_limit': '500 queries per day without a key', 'used_for': 'would add: retail sales detail (FRED RSAFS '
     'used)'},
    {'name': 'New York Fed Markets API', 'rank': OFFICIAL, 'integrated': False,
     'probe': 'https://markets.newyorkfed.org/api/rates/all/latest.json', 'auth': 'none', 'frequency': 'daily',
     'terms': 'NY Fed terms of use', 'rate_limit': 'not verified here', 'used_for': 'would add: SOFR, EFFR, '
                                                                                 'repo operations'},
    {'name': 'OFR Financial Stress Index API', 'rank': OFFICIAL, 'integrated': False,
     'probe': 'https://data.financialresearch.gov/v1/series/timeseries?mnemonic=FSI-OFR_FSI', 'auth': 'none',
     'frequency': 'daily', 'terms': 'public', 'rate_limit': 'not verified here',
     'used_for': 'would add: financial stress index'},
    {'name': 'IMF data API (primary commodity prices)', 'rank': OFFICIAL, 'integrated': False,
     'probe': 'https://api.imf.org/external/sdmx/2.1/data/PCPS/M.W00.PCOPP.USD', 'auth': 'none',
     'frequency': 'monthly', 'terms': 'IMF terms of use', 'rate_limit': 'not verified here',
     'used_for': 'would add: commodity prices directly (the FRED copies are used)'},
    {'name': 'University of Michigan consumer survey files', 'rank': OFFICIAL, 'integrated': False,
     'probe': 'https://www.sca.isr.umich.edu/files/tbmics.csv', 'auth': 'none', 'frequency': 'monthly',
     'terms': 'University of Michigan terms', 'rate_limit': 'not verified here',
     'used_for': 'would add: sentiment components (FRED UMCSENT used)'},
    {'name': 'USGS mineral commodity statistics', 'rank': OFFICIAL, 'integrated': False,
     'probe': 'https://www.usgs.gov/centers/national-minerals-information-center/rare-earths-statistics-and-'
              'information', 'auth': 'none', 'frequency': 'annual', 'terms': 'public domain',
     'rate_limit': 'not verified here', 'used_for': 'would add: rare-earth production and annual prices'},
    {'name': 'Stooq daily prices', 'rank': SECONDARY, 'integrated': False,
     'probe': 'https://stooq.com/q/d/l/?s=spy.us&i=d', 'auth': 'none', 'frequency': 'daily',
     'terms': 'Stooq terms', 'rate_limit': 'not verified here', 'used_for': 'would add: a third price source'},
]


def probe_url(entry):
    """(url, missing key or None): the probe URL with keys from .env inserted."""
    url = entry['probe']
    for name in ('FRED_API_KEY', 'BEA_API_KEY', 'EIA_API_KEY', 'NEWSAPI_KEY'):
        token = '{' + name + '}'
        if token in url:
            value, problem = secret_env(name)
            if problem:
                return None, problem
            url = url.replace(token, value)
    return url, None


def _headers(client):
    """The User-Agent the production client sends (the probe mirrors the real call)."""
    import os
    if client == 'sec':
        return {'User-Agent': os.getenv('SEC_USER_AGENT', '').strip()}
    if client == 'requests':
        return {}                                               # requests' default, as macro_fred / news_processor
    from .external_sources import user_agent
    return {'User-Agent': user_agent()}                         # the collectors' helper


def _probe_yfinance(out):
    import yfinance as yf
    start = time.monotonic()
    try:
        bars = yf.Ticker('SPY').history(period='5d')
        out.update(http_status=200 if len(bars) else None, bytes=int(bars.memory_usage().sum()) if len(bars) else 0,
                   error=None if len(bars) else 'yfinance returned no bars')
    except Exception as e:  # noqa: BLE001 - reported
        out['error'] = redact(f'{type(e).__name__}: {e}')[:300]
    out['elapsed_s'] = round(time.monotonic() - start, 2)
    return out


def probe(entry, session=None, timeout=20):
    """One GET; {'http_status', 'bytes', 'elapsed_s', 'error', 'checked_at'} (no retry, never a workaround)."""
    out = {'checked_at': utc_now_iso(), 'http_status': None, 'bytes': None, 'elapsed_s': None, 'error': None}
    client = entry.get('client', 'collector')
    if client == 'yfinance':
        return _probe_yfinance(out)
    url, missing = probe_url(entry)
    if url is None:
        out['error'] = f'not probed: {missing}'
        return out
    session = session or requests.Session()
    start = time.monotonic()
    try:
        r = session.get(url, headers=_headers(client), timeout=timeout)
        out.update(http_status=r.status_code, bytes=len(r.content))
        if r.status_code >= 400:
            out['error'] = redact(f'HTTP {r.status_code}: {r.text[:160]}')
    except requests.RequestException as e:
        out['error'] = redact(f'{type(e).__name__}: {e}')[:300]
    out['elapsed_s'] = round(time.monotonic() - start, 2)
    return out


def run(session=None, write=True):
    rows = []
    for entry in REGISTRY:
        result = probe(entry, session)
        reachable = result['http_status'] is not None and result['http_status'] < 400
        rows.append({**{k: v for k, v in entry.items() if k not in ('probe', 'client')},
                     'endpoint': entry['probe'].split('?')[0], **result, 'reachable': reachable})
    report = {'computed_at': utc_now_iso(), 'sources': rows,
              'summary': {'integrated_reachable': sum(r['reachable'] for r in rows if r['integrated']),
                          'integrated_total': sum(r['integrated'] for r in rows),
                          'alternatives_reachable': [r['name'] for r in rows if not r['integrated'] and r['reachable']]}}
    if write:
        path = reports_dir() / 'source_check.json'
        path.write_text(redact(json.dumps(report, indent=1)), encoding='utf-8')
        report['path'] = str(path)
    return report


def print_report(report):
    print(f"\n[SOURCES] {report['computed_at']}")
    for r in report['sources']:
        state = f"HTTP {r['http_status']}" if r['http_status'] is not None else 'UNREACHABLE'
        tag = 'integrated ' if r['integrated'] else 'alternative'
        print(f"  {tag} rank {r['rank']}  {state:12} {r['name']}" + (f"  - {r['error'][:90]}" if r['error'] else ''))
    s = report['summary']
    print(f"  Integrated sources reachable: {s['integrated_reachable']} / {s['integrated_total']}")
    print('  Alternatives reachable here (not integrated): ' + (', '.join(s['alternatives_reachable']) or 'none'))
    if report.get('path'):
        print(f"  Results: {report['path']}")
