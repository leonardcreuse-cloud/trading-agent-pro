#!/usr/bin/env python3
"""
Pipeline audit (phase P1.5) - automated validation of stored data and of the no-look-ahead rule

`python main.py audit [TICKER ...]` (default: validation universe) writes
reports/pipeline_audit.json. Every check is PASS / WARN / FAIL with its evidence:
FAIL = a rule of docs/DATA_POLICY.md is broken (the run must not be trusted);
WARN = data that looks suspicious or is unavailable and needs a human look.

Checks
  storage     observations published after retrieval (schema rule); SHA-256 of a sample of raw
              payloads; stored raw payloads containing a configured secret.
  prices      non-positive closes (FAIL); gaps > 7 calendar days; |daily return| > 40 %
              (possible unadjusted split); last session older than 5 days.
  sec         point-in-time: fundamentals known one second before the latest 10-K/10-Q
              acceptance must not use that filing's period (FAIL), and one hour after must;
              TTM revenue vs the sum of the last four reported quarters (> 2 % apart: WARN);
              |revenue growth| > 200 %; D/E > 20; reason of every unavailable D/E.
  insider     Form 4 documents in the 90-day window not parsed; P/S transactions without price.
  walk-forward  every sample: known_at = session close of its date, entry after the signal
              date, exit after entry (FAIL otherwise).
"""

import json
import os
import random
from datetime import datetime, timedelta, timezone

from .common import DATA_UNAVAILABLE, SECRET_ENV_VARS, redact, reports_dir, utc_now_iso, validation_universe
from .database import Database
from .insider_tracker import FORM4_METRIC, InsiderTracker
from .market_data import PriceFeed, session_close_utc
from .sec_parser import SEC_SOURCE, SECParser

PASS, WARN, FAIL = 'PASS', 'WARN', 'FAIL'
MAX_DAILY_MOVE = 0.40
MAX_GAP_DAYS = 7
RAW_SAMPLE = 60


def check(name, status, detail, evidence=None):
    return {'check': name, 'status': status, 'detail': detail, 'evidence': evidence or []}


class PipelineAudit:
    def __init__(self, db=None):
        self.db = db or Database()
        self.sec = SECParser(db=self.db)
        self.prices = PriceFeed(db=self.db, lookback_days=1825)
        self.insider = InsiderTracker(sec_parser=self.sec)

    # ------------------------------------------------------------------ storage

    def storage_checks(self):
        out = []
        with self.db.connect() as conn:
            bad = conn.execute('SELECT COUNT(*) FROM observations WHERE published_at > retrieved_at'
                               ).fetchone()[0]
            ids = [r[0] for r in conn.execute(
                "SELECT fetch_id FROM source_fetches WHERE status='OK' AND raw_path IS NOT NULL")]
        out.append(check('observations published after retrieval', FAIL if bad else PASS,
                         f'{bad} rows'))
        sample = random.Random(0).sample(ids, min(RAW_SAMPLE, len(ids)))
        broken, leaked = [], []
        secrets = [os.getenv(n, '').strip() for n in SECRET_ENV_VARS]
        secrets = [s for s in secrets if len(s) >= 6]
        for fetch_id in sample:
            try:
                text = self.db.read_raw(fetch_id)
            except Exception as e:  # noqa: BLE001 - reported
                broken.append(f'fetch {fetch_id}: {type(e).__name__}')
                continue
            if any(s in (text or '') for s in secrets):
                leaked.append(f'fetch {fetch_id}')
        out.append(check(f'raw payload SHA-256 ({len(sample)} sampled)', FAIL if broken else PASS,
                         f'{len(broken)} unreadable / mismatched', broken[:10]))
        out.append(check('secrets in raw payloads (sample)', FAIL if leaked else PASS,
                         f'{len(leaked)} payloads', leaked[:10]))
        return out

    # ------------------------------------------------------------------ prices

    def price_checks(self, ticker):
        prices = self.prices.get(ticker)
        if prices['status'] != 'OK':
            return [check('prices available', WARN, prices['reason'])]
        close = prices['close']
        out = [check('prices available', PASS, f'{len(close)} sessions '
                     f'{close.index[0].date()} -> {close.index[-1].date()}')]
        nonpos = [str(d.date()) for d, v in close.items() if v <= 0]
        out.append(check('non-positive closes', FAIL if nonpos else PASS, f'{len(nonpos)}', nonpos[:10]))
        gaps = [f'{a.date()} -> {b.date()}' for a, b in zip(close.index[:-1], close.index[1:])
                if (b - a).days > MAX_GAP_DAYS]
        out.append(check(f'gaps > {MAX_GAP_DAYS} days', WARN if gaps else PASS, f'{len(gaps)}', gaps[:10]))
        moves = close.pct_change().dropna()
        big = [f'{d.date()}: {v:+.1%}' for d, v in moves.items() if abs(v) > MAX_DAILY_MOVE]
        out.append(check(f'|daily return| > {MAX_DAILY_MOVE:.0%}', WARN if big else PASS,
                         f'{len(big)} (check for unadjusted splits)', big[:10]))
        age = (datetime.now(timezone.utc).date() - close.index[-1].date()).days
        out.append(check('last session age', WARN if age > 5 else PASS, f'{age} days'))
        return out

    # ------------------------------------------------------------------ SEC

    def _quarter_sum(self, ticker, tag, end):
        """Sum of the four 3-month facts ending at `end` and the three previous quarters, or None."""
        q = dict(self.db.series(ticker, f'xbrl:{tag}:3M', source=SEC_SOURCE))
        ends = sorted(q)
        if end not in q:
            return None
        i = ends.index(end)
        if i < 3:
            return None
        window = ends[i - 3:i + 1]
        span = (datetime.fromisoformat(window[-1]) - datetime.fromisoformat(window[0])).days
        if not 255 <= span <= 290:           # four consecutive quarters
            return None
        return sum(q[e]['value'] for e in window)

    def sec_checks(self, ticker):
        fin = self.sec.fundamentals(ticker)
        if fin['fetch'] is None:
            return [check('SEC company facts', WARN, fin['reason'])]
        out = []
        latest = self.sec.fetch_latest_periodic_filing(ticker)
        if latest and latest.get('report_date') and latest.get('published_at'):
            pub = datetime.fromisoformat(latest['published_at'])
            before = self.sec.fundamentals(ticker, known_at=pub - timedelta(seconds=1))
            after = self.sec.fundamentals(ticker, known_at=pub + timedelta(hours=1))
            leak = (before.get('revenue_period_end') or '') >= latest['report_date'] or \
                (before.get('balance_sheet_date') or '') >= latest['report_date']
            out.append(check('no look-ahead at latest 10-K/10-Q acceptance', FAIL if leak else PASS,
                             f"{latest['form']} period {latest['report_date']} accepted {latest['published_at']}: "
                             f"before -> revenue {before.get('revenue_period_end')}, balance "
                             f"{before.get('balance_sheet_date')}; after -> revenue "
                             f"{after.get('revenue_period_end')}, balance {after.get('balance_sheet_date')}"))
            if after.get('revenue_period_end') not in (latest['report_date'], None) and \
                    fin.get('revenue_period_end') == latest['report_date']:
                out.append(check('latest filing used once public', WARN,
                                 'revenue for the latest period appears only later than its acceptance'))
        if fin['revenue'] is None:
            out.append(check('revenue TTM', WARN, fin['reason']))
        else:
            qsum = self._quarter_sum(ticker, fin['revenue_tag'], fin['revenue_period_end'])
            if qsum is None:
                out.append(check('revenue TTM vs 4 reported quarters', PASS,
                                 f"{fin['revenue'] / 1e9:.2f} B ({fin['revenue_method']}); "
                                 'four 3-month facts not all reported (Q4 is usually annual only)'))
            else:
                gap = abs(fin['revenue'] / qsum - 1)
                out.append(check('revenue TTM vs 4 reported quarters', WARN if gap > 0.02 else PASS,
                                 f"TTM {fin['revenue'] / 1e9:.3f} B vs quarters {qsum / 1e9:.3f} B "
                                 f"({gap:.2%} apart)"))
        g = fin.get('revenue_growth_pct')
        if g is not None and abs(g) > 200:
            out.append(check('revenue growth plausibility', WARN, f'{g} % YoY'))
        de = fin.get('debt_to_equity')
        if de is None:
            out.append(check('debt / equity', WARN, fin['reason'] or DATA_UNAVAILABLE))
        else:
            out.append(check('debt / equity', WARN if de > 20 else PASS,
                             f"{de} ({fin['debt_definition']}, balance sheet {fin['balance_sheet_date']}"
                             + (', incl. finance leases' if fin.get('debt_includes_finance_leases') else '')
                             + (', equity incl. NCI' if fin.get('equity_tag') != 'StockholdersEquity' else '')
                             + ')'))
        return out

    # ------------------------------------------------------------------ insider

    def insider_checks(self, ticker):
        ingested = self.insider.ingest(ticker)
        if ingested is None:
            return [check('Form 4 window', WARN, f'SEC unavailable: {self.sec.last_error}')]
        n, parsed, failures = ingested
        out = [check('Form 4 documents parsed (90 d)', WARN if failures else PASS,
                     f'{parsed}/{n}', [f"{f['accession']}: {f['reason']}" for f in failures[:5]])]
        events = self.db.events(ticker, FORM4_METRIC, source=SEC_SOURCE)
        txns = [json.loads(e['value_text']) for e in events]
        no_price = [t['accession'] for t in txns if t.get('code') in ('P', 'S') and not t.get('price')]
        out.append(check('open-market transactions without price', WARN if no_price else PASS,
                         f'{len(no_price)} of {sum(t.get("code") in ("P", "S") for t in txns)} stored',
                         no_price[:5]))
        return out

    # ------------------------------------------------------------------ walk-forward

    @staticmethod
    def walk_forward_checks():
        path = reports_dir() / 'walk_forward.json'
        if not path.exists():
            return [check('walk-forward samples', WARN, 'no walk_forward.json')]
        samples = json.loads(path.read_text(encoding='utf-8')).get('samples', [])
        bad = []
        for s in samples:
            ok = s['known_at'] == session_close_utc(s['date']) and s['entry_date'] > s['date']
            for key in [k for k in s if k.startswith('exit_')]:
                ok = ok and (s[key] is None or s[key] > s['entry_date'])
            if not ok:
                bad.append(f"{s['ticker']} {s['date']}")
        return [check(f'walk-forward timing ({len(samples)} samples)', FAIL if bad else PASS,
                      f'{len(bad)} samples with entry/exit not after the signal', bad[:10])]

    # ------------------------------------------------------------------ run

    def run(self, universe=None):
        universe = universe or validation_universe()
        print(f"\n[PIPELINE AUDIT] {len(universe)} tickers")
        report = {'computed_at': utc_now_iso(), 'universe': universe,
                  'global': self.storage_checks() + self.walk_forward_checks(), 'tickers': {}}
        for n, ticker in enumerate(universe, 1):
            checks = []
            for name, func in (('prices', self.price_checks), ('sec', self.sec_checks),
                               ('insider', self.insider_checks)):
                try:
                    checks += [dict(c, group=name) for c in func(ticker)]
                except Exception as e:  # noqa: BLE001 - an audit crash is itself a failure
                    checks.append(check(f'{name} audit', FAIL, redact(f'{type(e).__name__}: {e}')))
            report['tickers'][ticker] = checks
            worst = [c for c in checks if c['status'] != PASS]
            print(f"  {ticker:6} ({n}/{len(universe)}) " + (', '.join(
                f"{c['status']}: {c['check']}" for c in worst) or 'all PASS'))
        every = report['global'] + [c for cs in report['tickers'].values() for c in cs]
        report['summary'] = {s: sum(c['status'] == s for c in every) for s in (PASS, WARN, FAIL)}
        report['status'] = FAIL if report['summary'][FAIL] else WARN if report['summary'][WARN] else PASS
        for c in report['global']:
            print(f"  [global] {c['status']}: {c['check']} - {c['detail']}")
        print(f"\n  Audit status: {report['status']} {report['summary']}")
        path = reports_dir() / 'pipeline_audit.json'
        path.write_text(redact(json.dumps(report, indent=1, default=str)), encoding='utf-8')
        print(f"  Results: {path}")
        return report


if __name__ == "__main__":
    PipelineAudit().run()
