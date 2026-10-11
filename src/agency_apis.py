#!/usr/bin/env python3
"""
Keyed APIs of U.S. statistical agencies (phase P4.1): BLS Public Data API v2, BEA NIPA tables
(apps.bea.gov) and EIA Open Data API v2. `python main.py collect` runs them with the P4.0 collectors
(external_sources.collect_all). Each needs its key (BLS_API_KEY, BEA_API_KEY, EIA_API_KEY); without
it the collector is DATA UNAVAILABLE and no call is made.

Every call goes through external_sources.http_fetch (logged, raw payload kept with the key redacted:
BEA echoes the UserID in every response, BLS echoes the key in its error messages) and every value
through upsert_observations, as published (no transformation), entity '<AGENCY>:<series id>', metric
'value':

  source (rank)  data                                          published_at (basis)
  BLS (1)        CPI-U (headline and core SA / NSA, shelter,    unknown (retrieval time): the API returns
                 energy, food, services less energy), PPI final  the current revision without a date and
                 demand, unemployment and participation rates,   the BLS schedule pages list future releases
                 payrolls, hourly earnings (nominal, real),      only; a revised value is a new version
                 JOLTS openings                                  dated by its retrieval
  BEA (1)        real GDP and real PCE growth (Table 1.1.1),    end of day New York of the table's
                 PCE and core PCE price indexes (Table 2.8.4),  "LastRevised" date (every value of that
                 personal income, PCE, saving rate (Table 2.6)  table version was public by then); a value
                                                                 equal to the stored version keeps its date
  EIA (1)        WTI, Brent and Henry Hub spot prices (daily),  unknown (retrieval time): the API gives no
                 weekly petroleum stocks, crude production,     publication date
                 refinery utilisation, retail gasoline and
                 diesel prices, natural gas storage

BLS footnotes (P = preliminary) stay in the raw payload. Public data of U.S. federal agencies.
"""

import json
import re
from datetime import date, datetime
from urllib.parse import urlencode

from .common import DATA_UNAVAILABLE, end_of_us_trading_day_utc, redact, secret_env
from .external_sources import _num, _result, http_fetch

# ---------------------------------------------------------------- BLS Public Data API v2

BLS_SOURCE = 'BLS'
BLS_API_URL = 'https://api.bls.gov/publicAPI/v2/timeseries/data/'
BLS_MAX_SERIES = 50                     # series per request with a registered key
BLS_SERIES = {                          # series id: (label, unit); monthly series only
    'CUSR0000SA0': ('CPI-U all items, SA', 'index'),
    'CUUR0000SA0': ('CPI-U all items, NSA', 'index'),
    'CUSR0000SA0L1E': ('CPI-U all items less food and energy, SA', 'index'),
    'CUUR0000SA0L1E': ('CPI-U all items less food and energy, NSA', 'index'),
    'CUSR0000SAH1': ('CPI-U shelter, SA', 'index'),
    'CUSR0000SA0E': ('CPI-U energy, SA', 'index'),
    'CUSR0000SAF1': ('CPI-U food, SA', 'index'),
    'CUSR0000SASLE': ('CPI-U services less energy services, SA', 'index'),
    'WPSFD4': ('PPI final demand, SA', 'index'),
    'LNS14000000': ('Unemployment rate, SA', '%'),
    'LNS11300000': ('Labor force participation rate, SA', '%'),
    'CES0000000001': ('All employees, total nonfarm, SA', 'thousands of persons'),
    'CES0500000003': ('Average hourly earnings, total private, SA', 'USD per hour'),
    'CES0500000013': ('Average hourly earnings, total private, 1982-84 dollars, SA', '1982-84 USD per hour'),
    'JTS000000000000000JOL': ('JOLTS job openings, total nonfarm, SA', 'thousands'),
}
BLS_BASIS = ('BLS API returns the current revision without a publication date (schedule pages list future '
             'releases only): retrieval time')
BLS_MONTH = re.compile(r'M(0[1-9]|1[0-2])')     # M13 = annual average, not stored


def bls_rows(payload):
    """(rows, series ids with at least one value) from a BLS v2 response; months dated the 1st."""
    rows, seen = [], set()
    for s in (payload.get('Results') or {}).get('series') or []:
        sid = s.get('seriesID')
        if sid not in BLS_SERIES:
            continue
        for d in s.get('data') or []:
            period, value = d.get('period') or '', _num(d.get('value'))
            if not BLS_MONTH.fullmatch(period) or value is None:
                continue
            rows.append({'entity': f'BLS:{sid}', 'metric': 'value',
                         'as_of_date': date(int(d['year']), int(period[1:]), 1).isoformat(), 'value': value,
                         'unit': BLS_SERIES[sid][1], 'published_at': None, 'published_at_basis': BLS_BASIS})
            seen.add(sid)
    return rows, seen


def collect_bls_api(db, start_year, end_year):
    key, problem = secret_env('BLS_API_KEY')
    if problem:
        return _result('bls_api', DATA_UNAVAILABLE, 0, problem)
    stored, problems = 0, []
    ids = list(BLS_SERIES)
    for i in range(0, len(ids), BLS_MAX_SERIES):
        chunk = ids[i:i + BLS_MAX_SERIES]
        body = {'seriesid': chunk, 'startyear': str(start_year), 'endyear': str(end_year),
                'registrationkey': key}
        got = http_fetch(db, BLS_SOURCE, BLS_API_URL, body=body)
        if got['status'] != 'OK':
            problems.append(got['reason'])
            continue
        try:
            payload = json.loads(got['content'])
        except ValueError:
            problems.append('response is not JSON')
            continue
        if payload.get('status') != 'REQUEST_SUCCEEDED':      # BLS answers HTTP 200 with an error status
            problems.append(redact(f"{payload.get('status')}: {'; '.join(payload.get('message') or [])}"))
            continue
        rows, seen = bls_rows(payload)
        missing = [s for s in chunk if s not in seen]
        if missing:
            problems.append(f'no monthly value returned for {", ".join(missing)}')
        stored += db.upsert_observations(got['fetch'], rows)
    return _result('bls_api', 'OK' if not problems else DATA_UNAVAILABLE, stored, '; '.join(problems) or None)


# ---------------------------------------------------------------- BEA NIPA tables

BEA_SOURCE = 'BEA'
BEA_API_URL = 'https://apps.bea.gov/api/data'
BEA_TABLES = {      # NIPA table: (frequency, {series code: (label, unit, expected UNIT_MULT)})
    'T10101': ('Q', {'A191RL': ('Real GDP, percent change from preceding quarter', '% (annual rate, SA)', '0'),
                     'DPCERL': ('Real PCE, percent change from preceding quarter', '% (annual rate, SA)', '0')}),
    'T20804': ('M', {'DPCERG': ('PCE price index', 'index 2017 = 100 (SA)', '0'),
                     'DPCCRG': ('PCE price index excluding food and energy', 'index 2017 = 100 (SA)', '0')}),
    'T20600': ('M', {'A065RC': ('Personal income', 'USD millions (SAAR)', '6'),
                     'DPCERC': ('Personal consumption expenditures', 'USD millions (SAAR)', '6'),
                     'A072RC': ('Personal saving rate', '% of disposable personal income', '0')}),
}
BEA_REVISED = re.compile(r'LastRevised:\s*([A-Z][a-z]+ \d{1,2}, \d{4})')
BEA_PERIOD = re.compile(r'(\d{4})(?:Q([1-4])|M(0[1-9]|1[0-2]))')


def bea_period(text):
    """'2026Q2' -> 2026-04-01, '2026M08' -> 2026-08-01 (first day of the period), else None."""
    m = BEA_PERIOD.fullmatch(text or '')
    if not m:
        return None
    month = 3 * int(m.group(2)) - 2 if m.group(2) else int(m.group(3))
    return date(int(m.group(1)), month, 1).isoformat()


def bea_error(payload):
    api = payload.get('BEAAPI') or {}
    results = api.get('Results')
    err = api.get('Error') or (results.get('Error') if isinstance(results, dict) else None)
    if not err:
        return None
    detail = (err.get('ErrorDetail') or {}).get('Description')
    return f"BEA error {err.get('APIErrorCode')}: {err.get('APIErrorDescription')}" + (f' ({detail})' if detail else '')


def bea_rows(table, payload):
    """(rows, LastRevised date or None, problems) for the declared series of one NIPA table response."""
    results = (payload.get('BEAAPI') or {}).get('Results') or {}
    note = next((n.get('NoteText') or '' for n in results.get('Notes') or [] if n.get('NoteRef') == table), '')
    m = BEA_REVISED.search(note)
    revised = datetime.strptime(m.group(1), '%B %d, %Y').date() if m else None
    pub = end_of_us_trading_day_utc(revised) if revised else None
    basis = (f'BEA table note "LastRevised: {revised.isoformat()}", end of day New York (conservative)' if revised
             else 'BEA table note without a LastRevised date: retrieval time')
    wanted = BEA_TABLES[table][1]
    rows, problems, seen = [], [], set()
    for d in results.get('Data') or []:
        code = d.get('SeriesCode')
        if code not in wanted:
            continue
        unit, mult = wanted[code][1:]
        if (d.get('UNIT_MULT') or '0') != mult:
            problem = f'{code}: UNIT_MULT {d.get("UNIT_MULT")} instead of {mult} (units changed?)'
            if problem not in problems:
                problems.append(problem)
            continue
        as_of, value = bea_period(d.get('TimePeriod')), _num((d.get('DataValue') or '').replace(',', ''))
        if as_of is None or value is None:
            continue
        rows.append({'entity': f'BEA:{code}', 'metric': 'value', 'as_of_date': as_of, 'value': value, 'unit': unit,
                     'published_at': pub, 'published_at_basis': basis})
        seen.add(code)
    missing = [c for c in wanted if c not in seen and not any(p.startswith(f'{c}:') for p in problems)]
    if missing:
        problems.append(f'no value returned for {", ".join(missing)}')
    return rows, revised, problems


def keep_unchanged_publication(db, source, rows):
    """
    A value equal to the latest stored version of the same observation keeps that version's publication
    time and basis (a newer table date only shows it was still current), so it is not stored again.
    """
    stored = {}
    for r in rows:
        key = (r['entity'], r['metric'])
        if key not in stored:
            stored[key] = dict(db.series(r['entity'], r['metric'], source=source))
        prev = stored[key].get(r['as_of_date'])
        if prev is not None and prev['value'] == r['value']:
            r['published_at'], r['published_at_basis'] = prev['published_at'], prev['published_at_basis']
    return rows


def collect_bea(db, years):
    key, problem = secret_env('BEA_API_KEY')
    if problem:
        return _result('bea_nipa', DATA_UNAVAILABLE, 0, problem)
    stored, problems, revised = 0, [], {}
    for table, (freq, _) in BEA_TABLES.items():
        params = {'UserID': key, 'method': 'GetData', 'DataSetName': 'NIPA', 'TableName': table,
                  'Frequency': freq, 'Year': ','.join(str(y) for y in years), 'ResultFormat': 'JSON'}
        got = http_fetch(db, BEA_SOURCE, BEA_API_URL, params=params)
        if got['status'] != 'OK':
            problems.append(f'{table}: {got["reason"]}')
            continue
        try:
            payload = json.loads(got['content'])
        except ValueError:
            problems.append(f'{table}: response is not JSON')
            continue
        error = bea_error(payload)
        if error:
            problems.append(f'{table}: {error}')
            continue
        rows, revised[table], table_problems = bea_rows(table, payload)
        problems += [f'{table}: {p}' for p in table_problems]
        stored += db.upsert_observations(got['fetch'], keep_unchanged_publication(db, BEA_SOURCE, rows))
    return _result('bea_nipa', 'OK' if not problems else DATA_UNAVAILABLE, stored, '; '.join(problems) or None,
                   last_revised={t: d and d.isoformat() for t, d in revised.items()})


# ---------------------------------------------------------------- EIA Open Data API v2

EIA_SOURCE = 'EIA'
EIA_API_URL = 'https://api.eia.gov/v2/{}/data/'
EIA_MAX_ROWS = 5000                     # per response (JSON)
EIA_ROUTES = {      # route: (frequency, {series: label}); units come with each row
    'petroleum/pri/spt': ('daily', {'RWTC': 'WTI crude oil spot price, Cushing OK (FOB)',
                                    'RBRTE': 'Brent crude oil spot price (FOB)'}),
    'natural-gas/pri/fut': ('daily', {'RNGWHHD': 'Henry Hub natural gas spot price'}),
    'petroleum/sum/sndw': ('weekly', {'WCESTUS1': 'U.S. crude oil ending stocks excluding SPR',
                                      'WCSSTUS1': 'U.S. crude oil stocks in the SPR',
                                      'WGTSTUS1': 'U.S. total gasoline ending stocks',
                                      'WDISTUS1': 'U.S. distillate fuel oil ending stocks',
                                      'WCRFPUS2': 'U.S. field production of crude oil'}),
    'petroleum/pnp/wiup': ('weekly', {'WPULEUS3': 'U.S. refinery utilisation of operable capacity'}),
    'petroleum/pri/gnd': ('weekly', {'EMM_EPMR_PTE_NUS_DPG': 'U.S. regular gasoline retail price',
                                     'EMD_EPD2D_PTE_NUS_DPG': 'U.S. No. 2 diesel retail price'}),
    'natural-gas/stor/wkly': ('weekly', {'NW2_EPG0_SWO_R48_BCF': 'Lower 48 working gas in underground storage'}),
}
EIA_BASIS = 'EIA API gives no publication date: retrieval time'
ISO_DAY = re.compile(r'\d{4}-\d{2}-\d{2}')


def eia_rows(payload, wanted):
    """(rows, series with at least one value) from an EIA v2 data response."""
    rows, seen = [], set()
    for d in (payload.get('response') or {}).get('data') or []:
        series, period, value = d.get('series'), d.get('period') or '', _num(d.get('value'))
        if series not in wanted or value is None or not ISO_DAY.fullmatch(period):
            continue
        rows.append({'entity': f'EIA:{series}', 'metric': 'value', 'as_of_date': period, 'value': value,
                     'unit': d.get('units'), 'published_at': None, 'published_at_basis': EIA_BASIS})
        seen.add(series)
    return rows, seen


def collect_eia(db, since):
    key, problem = secret_env('EIA_API_KEY')
    if problem:
        return _result('eia_energy', DATA_UNAVAILABLE, 0, problem)
    stored, problems = 0, []
    for route, (freq, wanted) in EIA_ROUTES.items():
        query = ([('api_key', key), ('frequency', freq), ('data[0]', 'value')]
                 + [('facets[series][]', s) for s in wanted]
                 + [('start', since.isoformat()), ('sort[0][column]', 'period'), ('sort[0][direction]', 'desc'),
                    ('length', EIA_MAX_ROWS)])
        got = http_fetch(db, EIA_SOURCE, EIA_API_URL.format(route) + '?' + urlencode(query))
        if got['status'] != 'OK':
            problems.append(f'{route}: {got["reason"]}')
            continue
        try:
            payload = json.loads(got['content'])
        except ValueError:
            problems.append(f'{route}: response is not JSON')
            continue
        response = payload.get('response') or {}
        total, n = _num(response.get('total')), len(response.get('data') or [])
        if total is not None and total > n:
            problems.append(f'{route}: {n} of {int(total)} rows returned; the oldest were not stored')
        rows, seen = eia_rows(payload, wanted)
        missing = [s for s in wanted if s not in seen]
        if missing:
            problems.append(f'{route}: no value returned for {", ".join(missing)}')
        stored += db.upsert_observations(got['fetch'], rows)
    return _result('eia_energy', 'OK' if not problems else DATA_UNAVAILABLE, stored, '; '.join(problems) or None)
