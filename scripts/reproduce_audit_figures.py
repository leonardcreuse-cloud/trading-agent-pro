#!/usr/bin/env python3
"""
Phase 0.2 (consigne of 2026-10-14): recompute three figures of the reliability audit from STORED RAW FILES only.
No download, no database observation table.

1. Agreement of closes yfinance / Cboe (audit: 100%).
2. Agreement of opens yfinance / Cboe (audit: 39%).
3. Stage 1 IC of accruals at 252 sessions (audit: +0.054).

Raw files are the payloads logged in source_fetches (data/raw/...).
- yfinance: the CSV saved by PriceFeed, with columns close_raw / open_raw (as reported by Yahoo, split-adjusted).
- Cboe: the delayed daily history excerpt (open / high / low / close as traded).
All successful fetches of each source are merged, the latest value of each session winning.

Agreement = the share of common sessions (2025-10-01 to 2026-10-09) with |yfinance / Cboe − 1| < 0.01% (exact to
rounding). It is reported with and without HON: Yahoo's "raw" prices are split-adjusted (a 2:1 adjustment for HON),
and Cboe's are as traded.

Usage: python scripts/reproduce_audit_figures.py [--json path]
"""

import argparse
import csv
import gzip
import io
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common import data_dir, utc_now_iso  # noqa: E402

START, END = '2025-10-01', '2026-10-09'
EXACT = 1e-4                    # 0.01%: equal to rounding
SPLIT_ADJUSTED_ONLY_IN_YAHOO = ('HON',)


def read(path):
    raw = (data_dir() / path).read_bytes()
    return gzip.decompress(raw).decode() if path.endswith('.gz') else raw.decode()


def raw_files(conn, source, like):
    """(endpoint, raw_path) of every successful fetch, oldest first: later files override earlier ones date by date
    (the Cboe collector stores an excerpt of the recent days only, so every file is needed)."""
    return conn.execute(
        "SELECT endpoint, raw_path FROM source_fetches WHERE source=? AND status='OK' AND raw_path IS NOT NULL "
        "AND endpoint LIKE ? ORDER BY completed_at, fetch_id", (source, like)).fetchall()


def yfinance_raw(conn):
    data = {}
    for endpoint, path in raw_files(conn, 'yfinance', 'yfinance.download(%'):
        ticker = endpoint[len('yfinance.download('):-1]
        rows = csv.DictReader(io.StringIO(read(path)))
        data.setdefault(ticker, {}).update({r['date'][:10]: r for r in rows})
    return data


def cboe_raw(conn):
    data = {}
    for endpoint, path in raw_files(conn, 'Cboe delayed quotes', '%/historical/%'):
        ticker = endpoint.rsplit('/', 1)[1].replace('.json', '')
        try:
            payload = json.loads(read(path))
        except ValueError:
            continue
        data.setdefault(ticker, {}).update({str(r.get('date'))[:10]: r for r in payload.get('data') or []})
    return data


def agreement(yf, cb, field, exclude=()):
    n = exact = above_05 = 0
    worst = 0.0
    for ticker, days in cb.items():
        if ticker in exclude or ticker not in yf:
            continue
        for day, bar in days.items():
            y = (yf[ticker].get(day) or {}).get(f'{field}_raw')
            x = bar.get(field)
            if not (START <= day <= END) or y in (None, '') or not x:
                continue
            rel = abs(float(y) / float(x) - 1)
            n += 1
            exact += rel < EXACT
            above_05 += rel > 0.005
            worst = max(worst, rel)
    return {'sessions': n, 'exact_pct': round(100 * exact / n, 1) if n else None,
            'above_0.5pct_pct': round(100 * above_05 / n, 2) if n else None, 'max_gap_pct': round(100 * worst, 2)}


def stage1_accruals():
    report = json.loads((ROOT / 'reports' / 'research_stage1.json').read_text())
    row = next(t for t in report['feature_tests'] if t['feature'] == 'accruals' and t['horizon'] == 252)
    cache = data_dir() / 'research' / 'panel_stage1.pkl'
    return {'stored_result': {k: row[k] for k in ('mean', 'se', 't_stat', 'n_dates', 'n_observations', 'period')},
            'stage1_computed_at': report['computed_at'], 'panel_cache_present': cache.exists(),
            'recomputed': None,
            'reason': ('not reproducible from stored files: the stage 1 panel cache and its raw inputs (prices of '
                       '148 stocks 2016-2026, SEC facts) were produced in an earlier environment on '
                       f"{report['computed_at'][:10]}; the current database starts on 2026-10-11 and holds prices "
                       'for only a few of the stage 1 tickers') if not cache.exists() else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', default=None)
    args = parser.parse_args()
    conn = sqlite3.connect(data_dir() / 'trading_pro.db')
    yf, cb = yfinance_raw(conn), cboe_raw(conn)
    result = {'computed_at': utc_now_iso(), 'period': [START, END], 'tickers_cboe': len(cb),
              'tickers_both': len(set(cb) & set(yf)),
              'close': {'all': agreement(yf, cb, 'close'),
                        'excluding_HON': agreement(yf, cb, 'close', SPLIT_ADJUSTED_ONLY_IN_YAHOO)},
              'open': {'all': agreement(yf, cb, 'open'),
                       'excluding_HON': agreement(yf, cb, 'open', SPLIT_ADJUSTED_ONLY_IN_YAHOO)},
              'low': {'excluding_HON': agreement(yf, cb, 'low', SPLIT_ADJUSTED_ONLY_IN_YAHOO)},
              'stage1_accruals_252': stage1_accruals()}
    text = json.dumps(result, indent=1)
    print(text)
    if args.json:
        Path(args.json).write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
