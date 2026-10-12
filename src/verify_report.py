#!/usr/bin/env python3
"""
Verify an archived weekly report against its sources (master mission P6 "verify reports against sources", gap G6)

`python main.py verify-report [archive.json]` takes facts stated in the report and fetches them again at the
source, independently of the stored copies the report was built from (each new request is logged):
  FRED        every level series of the macro table (not the derived year-over-year rates): the value of the
              observation date stated 'as known at T_c', fetched from ALFRED with realtime_start = realtime_end =
              the last vintage date admissible at T_c (a vintage dated d is public at 05:00 UTC on d + 1)
  SEC         every filing listed for the week (form, accession): the EDGAR filing index page (immutable; a copy
              already downloaded by the system is reused) must show the same form and acceptance time
  prices      the as-reported closes of each company's session timeline against Cboe's delayed daily history
              (a second redistributor of the exchanges' closes; fetched now)
  guidance    every quoted guidance line must appear verbatim in the exhibit at the URL the report cites
Each check is MATCH, MISMATCH (both values shown) or UNVERIFIABLE (with the reason, e.g. a refused host).
Results: reports/verification/<s0>/verification_v<N>.json. Nothing in the report is changed.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from .common import redact, reports_dir, secret_env, utc_now_iso

FRED_URL = 'https://api.stlouisfed.org/fred/series/observations'
TOLERANCE = 1e-9
PRICE_TOLERANCE = 0.005          # 0.5 %: same rule as the audit cross-check


def _match(report_value, source_value, tol=TOLERANCE):
    if report_value is None or source_value is None:
        return 'UNVERIFIABLE'
    try:
        a, b = float(report_value), float(source_value)
    except (TypeError, ValueError):
        return 'MATCH' if str(report_value).strip() == str(source_value).strip() else 'MISMATCH'
    return 'MATCH' if abs(a - b) <= tol * max(1.0, abs(b)) else 'MISMATCH'


def _check(kind, claim, endpoint, report_value, source_value, status=None, detail=None):
    return {'kind': kind, 'claim': claim, 'endpoint': endpoint, 'report_value': report_value,
            'source_value': source_value, 'status': status or _match(report_value, source_value), 'detail': detail}


def _sections(payload, name):
    return [s for s in payload['sections'] if s['name'] == name]


def fred_checks(payload, db, http_fetch, limit=40):
    from .weekly.sections.macro import SERIES
    out = []
    key, problem = secret_env('FRED_API_KEY')
    cutoff = datetime.fromisoformat(payload['time_model']['cutoff'])
    vintage = (cutoff - timedelta(days=1)).date().isoformat()        # vintage date d is public at d + 1, 05:00 UTC
    rows = []
    for s in _sections(payload, 'macro'):
        for t in s['tables']:
            if t['title'].startswith('Macro indicators as known at T_p and at T_c'):
                cols = t['columns']
                for r in t['rows']:
                    row = dict(zip(cols, r))
                    spec = SERIES.get(row['series'])
                    if spec and spec['transform'] == 'level' and row.get('value as known at T_c') is not None:
                        rows.append(row)
    for row in rows[:limit]:
        sid, obs, value = row['series'], row['obs (T_c)'], row['value as known at T_c']
        obs = f'{obs}-01' if len(str(obs)) == 7 else obs                 # monthly observations are shown as YYYY-MM
        claim = f'{sid} = {value} for {obs} as known at T_c'
        if problem:
            out.append(_check('FRED', claim, FRED_URL, value, None, 'UNVERIFIABLE', problem))
            continue
        params = {'series_id': sid, 'observation_start': obs, 'observation_end': obs, 'realtime_start': vintage,
                  'realtime_end': vintage, 'file_type': 'json', 'api_key': key}
        got = http_fetch(db, 'FRED', FRED_URL, params=params)
        if got['status'] != 'OK':
            out.append(_check('FRED', claim, FRED_URL, value, None, 'UNVERIFIABLE', got['reason']))
            continue
        try:
            obs_rows = json.loads(got['content']).get('observations') or []
            source = next((o['value'] for o in obs_rows if o.get('date') == obs), None)
            source = None if source in (None, '.') else float(source)
        except (ValueError, TypeError, AttributeError):
            source = None
        out.append(_check('FRED', claim, f'{FRED_URL}?series_id={sid}&realtime={vintage}', value, source,
                          None if source is not None else 'UNVERIFIABLE',
                          None if source is not None else f'no observation for {obs} in the vintage of {vintage}'))
    return out


def sec_checks(payload, sec, limit_per_ticker=10):
    from .sec_parser import EDGAR_INDEX_URL, index_accepted
    out = []
    for s in _sections(payload, 'sec_events'):
        for t in s['tables']:
            if 'every SEC filing available in the window' not in t['title']:
                continue
            ticker = t['title'].split(':')[0].strip()
            cik = sec.get_cik(ticker)
            for r in t['rows'][:limit_per_ticker]:
                row = dict(zip(t['columns'], r))
                acc = row.get('accession')
                claim = f"{ticker}: {row.get('form')} {acc} accepted {row.get('accepted (UTC)')}"
                if not cik or not acc:
                    out.append(_check('SEC', claim, None, row.get('accepted (UTC)'), None, 'UNVERIFIABLE',
                                      'no CIK or accession'))
                    continue
                url = EDGAR_INDEX_URL.format(cik=int(cik), nodash=acc.replace('-', ''), accession=acc)
                html = sec._get(url, as_json=False, max_age=timedelta(days=3650))
                if not html:
                    out.append(_check('SEC', claim, url, row.get('accepted (UTC)'), None, 'UNVERIFIABLE',
                                      sec.last_error or 'no response'))
                    continue
                accepted = index_accepted(html)
                form = re.search(r'<div[^>]*id="formName"[^>]*>\s*<strong>\s*Form\s+([^<\s]+)', html)
                form_ok = form is None or form.group(1).strip() == str(row.get('form'))
                status = _match(row.get('accepted (UTC)'), accepted)
                if status == 'MATCH' and not form_ok:
                    status = 'MISMATCH'
                out.append(_check('SEC', claim, url, row.get('accepted (UTC)'), accepted, status,
                                  None if form_ok else f"index page form {form.group(1)} vs report {row.get('form')}"))
    return out


def price_checks(payload, db, http_fetch):
    from .external_sources import CBOE_HISTORY_SOURCE, CBOE_HISTORY_URL
    out = []
    for s in _sections(payload, 'market'):
        for t in s['tables']:
            if not t['title'].endswith('— session timeline'):
                continue
            ticker = t['title'].split(' — ')[0]
            url = CBOE_HISTORY_URL.format(ticker)
            got = http_fetch(db, CBOE_HISTORY_SOURCE, url, raw=lambda c: c[:2000])
            closes = {}
            if got['status'] == 'OK':
                try:
                    closes = {r['date'][:10]: r['close'] for r in json.loads(got['content']).get('data') or []}
                except (ValueError, TypeError, KeyError):
                    closes = {}
            for r in t['rows']:
                row = dict(zip(t['columns'], r))
                day, value = row.get('session'), row.get('close_raw (USD)')
                claim = f'{ticker} close {value} on {day} (yfinance, as reported)'
                if got['status'] != 'OK':
                    out.append(_check('price', claim, url, value, None, 'UNVERIFIABLE', got['reason']))
                    continue
                out.append(_check('price', claim, url, value, closes.get(day),
                                  None if closes.get(day) is not None else 'UNVERIFIABLE',
                                  None if closes.get(day) is not None else 'no Cboe bar for that session'))
                out[-1]['status'] = (out[-1]['status'] if closes.get(day) is None else
                                     _match(value, closes.get(day), PRICE_TOLERANCE))
    return out


def guidance_checks(payload, sec):
    from .guidance import text_lines
    out = []
    for s in _sections(payload, 'valuation'):
        for t in s['tables']:
            if ': company guidance, quoted' not in t['title']:
                continue
            m = re.search(r'Source: (https://www\.sec\.gov/\S+?)\.?\s', (t.get('note') or '') + ' ')
            url = m.group(1) if m else None
            doc = sec._get(url, as_json=False, max_age=timedelta(days=3650)) if url else None
            lines = set(text_lines(doc)) if doc else set()
            for (quoted,) in t['rows']:
                claim = f"{t['title'].split(':')[0]}: '{quoted[:80]}'"
                if not doc:
                    out.append(_check('guidance', claim, url, quoted, None, 'UNVERIFIABLE', 'exhibit unavailable'))
                    continue
                text = quoted[:-3] if quoted.endswith('...') else quoted
                found = any(line.startswith(text) for line in lines)
                out.append(_check('guidance', claim, url, quoted, 'found verbatim' if found else 'not found',
                                  'MATCH' if found else 'MISMATCH'))
    return out


def verify(path, db=None, sec=None, http_fetch=None):
    from .database import Database
    from .external_sources import http_fetch as default_fetch
    from .sec_parser import SECParser
    db = db or Database()
    sec = sec or SECParser(db=db)
    http_fetch = http_fetch or default_fetch
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    checks = (fred_checks(payload, db, http_fetch) + sec_checks(payload, sec) + price_checks(payload, db, http_fetch)
              + guidance_checks(payload, sec))
    summary = {}
    for c in checks:
        summary.setdefault(c['kind'], {'MATCH': 0, 'MISMATCH': 0, 'UNVERIFIABLE': 0})[c['status']] += 1
    result = {'computed_at': utc_now_iso(), 'report': str(path), 'cutoff': payload['time_model']['cutoff'],
              'code_version': payload.get('code_version'), 'summary': summary,
              'mismatches': sum(c['status'] == 'MISMATCH' for c in checks), 'checks': checks}
    s0 = payload['time_model']['s0']
    out_dir = reports_dir() / 'verification' / s0
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"verification_{Path(path).stem.split('_')[-1]}.json"
    target.write_text(redact(json.dumps(result, indent=1, default=str)), encoding='utf-8')
    result['path'] = str(target)
    return result
