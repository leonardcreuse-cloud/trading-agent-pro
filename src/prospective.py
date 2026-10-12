#!/usr/bin/env python3
"""
Stage 3 - prospective weekly record of the heuristic signal (paper only)

Protocol: docs/research/STAGE3_PREREGISTRATION.md (committed before the first record). The
constants below fix it in code; changing one that alters the scores or the test starts a new
series (new PROTOCOL, dated amendment).

record    `python main.py prospective record`, from scripts/daily_run.py on Saturdays and Sundays.
          s0 = last SPY session with EOD(s0) <= now (the weekly report's rule); T = 21:00 UTC on s0.
          Per ticker of the frozen UNIVERSE: technical, fundamentals and insider scores, ex-news
          combined score and label at T, computed by WalkForward.score_at (the walk-forward code).
          Made only once the week of s0 is over (now >= 05:00 UTC on the Saturday) and before the
          earliest possible open of the entry session (13:30 UTC on the Monday). One file per s0,
          records/record_<s0>.json, created once and never overwritten; its SHA-256 (canonical JSON)
          is appended to the hash-chained ledger.jsonl.
evaluate  `python main.py prospective evaluate`: realised returns from the close of s1 (first SPY
          session after s0) to the close H sessions later, H in HORIZONS, prices read now; validity
          of each record (integrity, timing, weekly spacing, cross-section); weekly cross-sectional
          Spearman IC. P1 (20 sessions) and P2 (5 sessions) are tested ONCE each, on the first
          MIN_RECORDS valid evaluated records (Bonferroni over 2); the result is frozen in
          confirmatory_<H>d.json. Before that, interim figures only (no t, no p, no conclusion).
          Writes evaluation.json and history/evaluation_<computed_at>.json (the weekly report reads
          the latest one computed at or before its cutoff).
Nothing is traded; a signal is not a trade recommendation and not a probability.
"""

import hashlib
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from .common import (DATA_UNAVAILABLE, end_of_us_trading_day_utc, redact, reports_dir, stamp, to_utc_iso,
                     utc_now_iso)
from .database import Database
from .insider_tracker import INGEST_MARGIN_DAYS, LOOKBACK_DAYS
from .market_data import PriceFeed, session_close_utc
from .scoring_signal_fixed import VALIDATION_ALPHA, ScoringSignalFixed, two_sided_p
from .walk_forward import MIN_HISTORY, WalkForward, class_stats, cross_sectional_ic, spearman

PROTOCOL = 'stage3-v1'
PREREGISTRATION = 'docs/research/STAGE3_PREREGISTRATION.md'
# frozen at the pre-registration (scheduler_config.json validation_universe on 2026-10-12)
UNIVERSE = ('CRWD', 'NET', 'RKLB', 'MP', 'MSFT', 'ORCL', 'ADBE', 'CRM', 'NOW', 'PANW', 'DDOG', 'ZS', 'NVDA',
            'AMD', 'QCOM', 'MU', 'INTC', 'AMZN', 'GOOGL', 'META', 'NFLX', 'UBER', 'BA', 'LMT', 'GE', 'CAT',
            'HON', 'DE', 'FCX', 'ALB', 'NUE', 'TSLA', 'NKE', 'HD', 'COST', 'LLY', 'JNJ', 'ISRG', 'XOM', 'CVX')
HYPOTHESES = {'P1': 20, 'P2': 5}            # confirmatory: horizon in sessions, expected IC > 0
HORIZONS = tuple(HYPOTHESES.values())
ALPHA = VALIDATION_ALPHA                    # 0.05, Bonferroni over the hypotheses
MIN_RECORDS = 52
MIN_TICKERS = 10
STEP = 5                                    # weekly records: overlap adjustment n_eff = n * min(1, STEP / H)
COMPONENTS = ('technical', 'fundamentals', 'insider')
CALENDAR_TICKER = 'SPY'
PRICE_LOOKBACK_DAYS = 400                   # >= MIN_HISTORY sessions before s0
INSIDER_INGEST_DAYS = LOOKBACK_DAYS + INGEST_MARGIN_DAYS
EARLIEST_OPEN_UTC = time(13, 30)            # 09:30 New York in summer time
GENESIS = '0' * 64


# ---------------------------------------------------------------- storage

def _root(base=None):
    return Path(base) if base else reports_dir() / 'prospective'


def prospective_dir(base=None):
    """Stage 3 directory, created (writers only; readers use _root and never create anything)."""
    path = _root(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def sha256(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def _clean(obj):
    """JSON-safe copy: non-finite floats become None (canonical JSON refuses NaN)."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _record_path(base, s0):
    return base / 'records' / f'record_{s0}.json'


def load_records(base=None):
    """{s0: (record, sha256)} of every record file present (in the ledger or not)."""
    base = _root(base)
    out = {}
    for path in sorted((base / 'records').glob('record_*.json')):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            out[record['s0']] = (record, sha256(record))
        except (ValueError, KeyError):
            out[path.stem.split('_', 1)[1]] = (None, None)
    return out


def verify_ledger(base=None):
    """
    Walk ledger.jsonl: each entry's hash and link to the previous entry, and the SHA-256 of the
    record file it names. 'verified' = {s0: entry} of the entries whose chain and file both check.
    """
    base = _root(base)
    path = base / 'ledger.jsonl'
    lines = [x for x in path.read_text(encoding='utf-8').splitlines() if x.strip()] if path.exists() else []
    prev, verified, problems, chain_ok = GENESIS, {}, [], True
    for n, line in enumerate(lines, 1):
        try:
            entry = json.loads(line)
            body = {k: v for k, v in entry.items() if k != 'hash'}
            linked = entry['prev'] == prev and entry['hash'] == sha256(body)
        except (ValueError, KeyError, TypeError):
            entry, linked = {}, False
        if not linked:
            problems.append(f"ledger line {n} ({entry.get('s0')}): hash chain broken; later entries not verified")
            chain_ok = False
            break
        prev = entry['hash']
        record_file = base / entry['record']
        if not record_file.exists():
            problems.append(f"record {entry['s0']}: file missing")
            continue
        try:
            actual = sha256(json.loads(record_file.read_text(encoding='utf-8')))
        except ValueError:
            actual = None
        if actual != entry['record_sha256']:
            problems.append(f"record {entry['s0']}: content differs from its ledger entry")
            continue
        verified[entry['s0']] = entry
    return {'n_entries': len(lines), 'chain_ok': chain_ok, 'head': prev, 'verified': verified,
            'problems': problems}


def _append_ledger(base, record, rel_path):
    ledger = verify_ledger(base)
    if not ledger['chain_ok']:
        raise RuntimeError('ledger hash chain broken: not appending (' + '; '.join(ledger['problems']) + ')')
    body = {'n': ledger['n_entries'] + 1, 's0': record['s0'], 'record': rel_path, 'record_sha256': sha256(record),
            'generated_at': record['generated_at'], 'protocol': record['protocol'], 'prev': ledger['head']}
    entry = {**body, 'hash': sha256(body)}
    with open(base / 'ledger.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, sort_keys=True) + '\n')
    return entry


# ---------------------------------------------------------------- calendar

def _dates(close):
    return [d.date().isoformat() for d in close.index]


def signal_session(sessions, now):
    """Last session whose end of day (05:00 UTC the next day) is at or before `now`; None if none."""
    done = [s for s in sessions if end_of_us_trading_day_utc(s) <= now]
    return done[-1] if done else None


def week_bounds(s0):
    """(end of the week of s0 = 05:00 UTC on its Saturday, earliest open of the next Monday 13:30 UTC)."""
    day = date.fromisoformat(s0)
    friday = day + timedelta(days=4 - day.weekday())
    monday = friday + timedelta(days=3)
    return (end_of_us_trading_day_utc(friday),
            to_utc_iso(datetime.combine(monday, EARLIEST_OPEN_UTC, tzinfo=timezone.utc)))


def entry_open_bound(s1):
    """Records must be generated before this instant (13:30 UTC on the entry session)."""
    return to_utc_iso(datetime.combine(date.fromisoformat(s1), EARLIEST_OPEN_UTC, tzinfo=timezone.utc))


def iso_week(day):
    return tuple(date.fromisoformat(day).isocalendar()[:2])


# ---------------------------------------------------------------- record

class Recorder:
    """Weekly signal record of the frozen universe at T = close of s0 (see module docstring)."""

    def __init__(self, db=None, price_feed=None, sec_parser=None, walk_forward=None, base=None):
        self.db = db or Database()
        self.prices = price_feed or PriceFeed(db=self.db, lookback_days=PRICE_LOOKBACK_DAYS)
        self.wf = walk_forward or WalkForward(db=self.db, price_feed=self.prices, sec_parser=sec_parser,
                                              history_days=INSIDER_INGEST_DAYS)
        self.base = prospective_dir(base)

    def ticker_signal(self, ticker, s0):
        """Scores at T = close of s0 (WalkForward.score_at), or DATA UNAVAILABLE with the reason."""
        prices = self.prices.get(ticker)
        if prices['status'] != 'OK':
            return {'status': DATA_UNAVAILABLE, 'reason': redact(prices['reason'])}
        close = prices['close']
        dates = _dates(close)
        if s0 not in dates:
            return {'status': DATA_UNAVAILABLE, 'reason': f'no close on {s0} in the price data'}
        i = dates.index(s0)
        if i + 1 < MIN_HISTORY:
            return {'status': DATA_UNAVAILABLE, 'reason': f'only {i + 1} sessions up to {s0} (minimum {MIN_HISTORY})'}
        self.wf.sec.last_error = None
        coverage = self.wf._insider_coverage(ticker)
        facts = self.wf.sec.ingest_company_facts(ticker)
        row = self.wf.score_at(ticker, close.to_numpy(dtype=float), dates, i, facts, coverage)
        return {'status': 'OK', **{k: row[k] for k in (*COMPONENTS, 'combined', 'signal')},
                'price_fetch_id': prices['fetch']['fetch_id'],
                'company_facts_fetch_id': facts['fetch_id'] if facts else None,
                'insider_coverage': coverage,
                'sec_error': redact(self.wf.sec.last_error) if self.wf.sec.last_error else None,
                'features': row['features']}

    def run(self, now=None, universe=UNIVERSE):
        """{'status': CREATED | EXISTS | NOT DUE | LEDGER BROKEN | DATA UNAVAILABLE, 's0', 'path', 'record', 'message'}."""
        from .weekly.core import code_version
        clock = now is None                     # generated_at = the instant the file is written (wall clock)
        now = to_utc_iso(now) or utc_now_iso()
        spy = self.prices.get(CALENDAR_TICKER)
        if spy['status'] != 'OK':
            return {'status': DATA_UNAVAILABLE, 's0': None, 'path': None, 'record': None,
                    'message': f"session calendar ({CALENDAR_TICKER} daily bars) unavailable: {redact(spy['reason'])}"}
        sessions = _dates(spy['close'])
        s0 = signal_session(sessions, now)
        if s0 is None:
            return {'status': DATA_UNAVAILABLE, 's0': None, 'path': None, 'record': None,
                    'message': 'no completed session in the calendar'}
        path = _record_path(self.base, s0)
        if path.exists():
            return {'status': 'EXISTS', 's0': s0, 'path': path, 'record': None,
                    'message': f'record for {s0} already made (records are never overwritten)'}
        ledger = verify_ledger(self.base)
        if not ledger['chain_ok']:
            return {'status': 'LEDGER BROKEN', 's0': s0, 'path': None, 'record': None,
                    'message': 'nothing recorded: ' + '; '.join(ledger['problems'])}
        week_over, too_late = week_bounds(s0)
        if now < week_over:
            return {'status': 'NOT DUE', 's0': s0, 'path': None, 'record': None,
                    'message': f'the week of {s0} is not over (record from {week_over})'}
        if now >= too_late:
            return {'status': 'NOT DUE', 's0': s0, 'path': None, 'record': None,
                    'message': f'too late for the week of {s0}: the next session may have opened ({too_late}); '
                               'the week is missing from the record'}
        signal = ScoringSignalFixed()
        tickers = {}
        for n, ticker in enumerate(universe, 1):
            print(f"  [{n}/{len(universe)}] {ticker}")
            try:
                tickers[ticker] = self.ticker_signal(ticker, s0)
            except Exception as e:  # noqa: BLE001 - one ticker must not stop the record
                tickers[ticker] = {'status': DATA_UNAVAILABLE, 'reason': redact(f'{type(e).__name__}: {e}')}
        generated = utc_now_iso() if clock else now
        if generated >= too_late:
            return {'status': 'NOT DUE', 's0': s0, 'path': None, 'record': None,
                    'message': f'too late for the week of {s0}: computed past {too_late}; nothing written'}
        record = _clean({
            'protocol': PROTOCOL, 'preregistration': PREREGISTRATION,
            's0': s0, 'signal_instant': session_close_utc(s0), 'started_at': now, 'generated_at': generated,
            'code_version': code_version(),
            'calendar': {'source': f'{CALENDAR_TICKER} daily bars (yfinance)',
                         'fetch_id': spy['fetch']['fetch_id'],
                         'last_sessions': [s for s in sessions if s <= s0][-5:]},
            'signal': {'name': 'ex-news combined heuristic score (ScoringSignalFixed)',
                       'components': list(COMPONENTS),
                       'weights': {k: signal.WEIGHTS[k] for k in COMPONENTS},
                       'min_components': signal.MIN_COMPONENTS,
                       'thresholds': {'positive': signal.POSITIVE_THRESHOLD, 'negative': signal.NEGATIVE_THRESHOLD}},
            'universe': list(universe),
            'tickers': tickers,
            'n_scored': sum(1 for x in tickers.values() if x.get('combined') is not None),
        })
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'x', encoding='utf-8') as f:            # never overwrite
            f.write(json.dumps(record, indent=1, sort_keys=True, allow_nan=False))
        entry = _append_ledger(self.base, record, path.relative_to(self.base).as_posix())
        notes = []
        if date.fromisoformat(s0).weekday() != 4:
            notes.append(f'{s0} is not a Friday: valid only if no session followed it in its week')
        if record['n_scored'] < MIN_TICKERS:
            notes.append(f"only {record['n_scored']} tickers scored (< {MIN_TICKERS}): the week will not count")
        return {'status': 'CREATED', 's0': s0, 'path': path, 'record': record, 'ledger_entry': entry,
                'message': f"record {s0}: {record['n_scored']}/{len(universe)} tickers scored, "
                           f"sha256 {entry['record_sha256']}" + ''.join(f'; {x}' for x in notes)}


# ---------------------------------------------------------------- evaluate

def _weekly_ics(rows, component, key, min_tickers=MIN_TICKERS):
    by_date = {}
    for r in rows:
        if r.get(component) is not None and r.get(key) is not None:
            by_date.setdefault(r['date'], []).append((r[component], r[key]))
    ics = [spearman([p[0] for p in v], [p[1] for p in v]) for v in by_date.values() if len(v) >= min_tickers]
    return [ic for ic in ics if ic is not None]


def _summary(ics):
    if not ics:
        return {'n_weeks': 0, 'mean_ic': None, 'positive_weeks_pct': None}
    return {'n_weeks': len(ics), 'mean_ic': round(sum(ics) / len(ics), 4),
            'positive_weeks_pct': round(sum(ic > 0 for ic in ics) / len(ics) * 100, 1)}


def confirmatory_test(rows, records, horizon, hypothesis, computed_at):
    """Pre-registered test on the given records (the first MIN_RECORDS valid evaluated ones)."""
    key = f'fwd_{horizon}d'
    chosen = set(records)
    stat = cross_sectional_ic([r for r in rows if r['date'] in chosen], 'combined', key, horizon, STEP, MIN_TICKERS)
    t = stat.get('t_stat')
    p = None if t is None else round(two_sided_p(t), 4)
    threshold = ALPHA / len(HYPOTHESES)
    mean = stat.get('mean_ic')
    return {'hypothesis': hypothesis, 'protocol': PROTOCOL, 'horizon_sessions': horizon, 'computed_at': computed_at,
            'records': sorted(chosen), 'n_weeks': stat.get('n_dates'), 'n_effective': stat.get('n_effective'),
            'mean_ic': mean, 'positive_weeks_pct': stat.get('positive_dates_pct'), 't_stat': t, 'p_value': p,
            'required_p': threshold,
            'confirmed': bool(p is not None and mean is not None and p < threshold and mean > 0),
            'adverse': bool(p is not None and mean is not None and p < threshold and mean < 0)}


def _returns(series, s1, horizon):
    dates, values = series
    if s1 not in dates:
        return None
    e = dates.index(s1)
    return values[e + horizon] / values[e] - 1 if e + horizon < len(values) else None


def evaluate(now=None, price_feed=None, db=None, base=None, write=True):
    """Realised outcomes of the records (module docstring); returns the evaluation dict."""
    now = to_utc_iso(now) or utc_now_iso()
    base = prospective_dir(base)
    ledger = verify_ledger(base)
    records = load_records(base)
    result = {'protocol': PROTOCOL, 'preregistration': PREREGISTRATION, 'computed_at': now,
              'ledger': {k: v for k, v in ledger.items() if k != 'verified'} | {'n_verified': len(ledger['verified'])},
              'hypotheses': {h: {'horizon_sessions': n, 'expected_sign': '+'} for h, n in HYPOTHESES.items()},
              'min_records': MIN_RECORDS, 'min_tickers': MIN_TICKERS, 'records': [], 'horizons': {}, 'samples': []}
    if not records:
        result.update(status='NO RECORDS', reason='no stage 3 record yet')
        return _write(base, result) if write else result
    earliest = min(records)
    feed = price_feed or PriceFeed(db=db or Database(),
                                   lookback_days=max(60, (date.fromisoformat(now[:10]) - date.fromisoformat(earliest)).days + 60))
    spy = feed.get(CALENDAR_TICKER)
    if spy['status'] != 'OK':
        result.update(status=DATA_UNAVAILABLE, reason=f"{CALENDAR_TICKER} daily bars unavailable: {redact(spy['reason'])}")
        return _write(base, result) if write else result
    sessions = [d for d in _dates(spy['close']) if session_close_utc(d) <= now]
    series = {}

    def prices_of(ticker):
        if ticker not in series:
            p = feed.get(ticker)
            if p['status'] != 'OK':
                series[ticker] = None
            else:
                pairs = [(d, float(v)) for d, v in zip(_dates(p['close']), p['close'].to_numpy(dtype=float))
                         if session_close_utc(d) <= now]
                series[ticker] = ([d for d, _ in pairs], [v for _, v in pairs])
        return series[ticker]

    for s0 in sorted(records):
        record, digest = records[s0]
        info = {'s0': s0, 'generated_at': record and record.get('generated_at'), 'problems': [], 'horizons': {}}
        result['records'].append(info)
        if record is None:
            info.update(status='invalid', problems=['record file is not readable JSON'])
            continue
        info['n_scored'] = record.get('n_scored')
        entry = ledger['verified'].get(s0)
        if entry is None or entry['record_sha256'] != digest:
            info['problems'].append('integrity: not verified by the ledger (missing entry, changed file or broken chain)')
        if record.get('protocol') != PROTOCOL:
            info['problems'].append(f"protocol {record.get('protocol')} is not {PROTOCOL} (another series)")
        later = [s for s in sessions if s > s0]
        if not later:
            info['status'] = 'pending' if not info['problems'] else 'invalid'
            info['note'] = 'entry session not observed yet'
            continue
        s1 = info['entry_date'] = later[0]
        if iso_week(s1) == iso_week(s0):
            info['problems'].append(f'weekly spacing: {s0} is not the last session of its week ({s1} followed)')
        if not record['generated_at'] < entry_open_bound(s1):
            info['problems'].append(f"timing: generated {record['generated_at']}, not before "
                                    f'{entry_open_bound(s1)} (open of the entry session {s1})')
        valid = not info['problems']
        info['status'] = 'valid' if valid else 'invalid'
        rows = []
        for ticker, x in sorted(record['tickers'].items()):
            if x.get('combined') is None:
                continue
            p = prices_of(ticker)
            row = {'date': s0, 'ticker': ticker, **{k: x.get(k) for k in (*COMPONENTS, 'combined', 'signal')}}
            for h in HORIZONS:
                row[f'fwd_{h}d'] = None if p is None or len(later) <= h else _returns(p, s1, h)
            rows.append(row)
        for h in HORIZONS:
            key = f'fwd_{h}d'
            if len(later) <= h:
                info['horizons'][f'{h}d'] = {'status': 'pending', 'exit_date': None}
                continue
            pairs = [r for r in rows if r[key] is not None]
            ic = spearman([r['combined'] for r in pairs], [r[key] for r in pairs]) \
                if len(pairs) >= MIN_TICKERS else None
            status = ('invalid record' if not valid else f'too few tickers (< {MIN_TICKERS})'
                      if len(pairs) < MIN_TICKERS else 'IC undefined (constant scores or returns)'
                      if ic is None else 'evaluated')
            info['horizons'][f'{h}d'] = {'status': status, 'exit_date': later[h], 'n_pairs': len(pairs),
                                         'ic': None if ic is None else round(ic, 4)}
        if valid:
            result['samples'].extend(rows)

    statuses = {'pending': 0, 'valid': 0, 'invalid': 0}
    for info in result['records']:
        statuses[info['status']] += 1
    result['record_counts'] = statuses
    concluded = 0
    for hyp, h in HYPOTHESES.items():
        key, label = f'fwd_{h}d', f'{h}d'
        evaluated = [i['s0'] for i in result['records'] if i['horizons'].get(label, {}).get('status') == 'evaluated']
        rows = [r for r in result['samples'] if r['date'] in set(evaluated)]
        realised = [r[key] for r in rows if r[key] is not None]
        out = {'hypothesis': hyp, 'n_evaluated': len(evaluated), 'required': MIN_RECORDS,
               'interim': _summary(_weekly_ics(rows, 'combined', key)),
               'exploratory': {'components': {c: _summary(_weekly_ics(rows, c, key)) for c in COMPONENTS},
                               'signal_classes': class_stats(rows, key),
                               'universe_mean_return_pct': round(sum(realised) / len(realised) * 100, 3)
                               if realised else None},
               'confirmatory': None}
        frozen = base / f'confirmatory_{label}.json'
        if frozen.exists():
            out['confirmatory'] = json.loads(frozen.read_text(encoding='utf-8'))
        elif len(evaluated) >= MIN_RECORDS:
            out['confirmatory'] = confirmatory_test(result['samples'], evaluated[:MIN_RECORDS], h, hyp, now)
            if write:
                with open(frozen, 'x', encoding='utf-8') as f:           # the test is run once
                    f.write(json.dumps(out['confirmatory'], indent=1))
        concluded += out['confirmatory'] is not None
        result['horizons'][label] = out
    result['status'] = 'CONCLUDED' if concluded == len(HYPOTHESES) else 'IN PROGRESS'
    return _write(base, result) if write else result


def _write(base, result):
    text = json.dumps(result, indent=1, default=str)
    (base / 'evaluation.json').write_text(text, encoding='utf-8')
    history = base / 'history'
    history.mkdir(exist_ok=True)
    (history / f"evaluation_{stamp(result['computed_at'])}.json").write_text(text, encoding='utf-8')
    return result


def latest_evaluation(now, base=None):
    """The latest evaluation computed at or before `now` (history files), or None."""
    history = _root(base) / 'history'
    cutoff = stamp(now)
    eligible = [p for p in sorted(history.glob('evaluation_*.json')) if p.stem.split('_', 1)[1] <= cutoff]
    if not eligible:
        return None
    data = json.loads(eligible[-1].read_text(encoding='utf-8'))
    return data if data.get('computed_at') and to_utc_iso(data['computed_at']) <= to_utc_iso(now) else None


def print_evaluation(result):
    print(f"\n[PROSPECTIVE] {result['protocol']} evaluated {result['computed_at']}: {result['status']}")
    led = result['ledger']
    print(f"  Ledger: {led['n_entries']} entries, {led['n_verified']} verified, chain "
          f"{'OK' if led['chain_ok'] else 'BROKEN'}" + ''.join(f"\n    ! {p}" for p in led['problems']))
    for info in result['records']:
        hs = ', '.join(f"{h} {x['status']}" + (f" IC {x['ic']:+.4f}" if x.get('ic') is not None else '')
                       for h, x in info['horizons'].items())
        print(f"  {info['s0']}  {info['status']:8} {hs}" + ''.join(f"\n    ! {p}" for p in info['problems']))
    for label, h in result.get('horizons', {}).items():
        conf, interim = h['confirmatory'], h['interim']
        head = f"  {h['hypothesis']} ({label}): {h['n_evaluated']}/{h['required']} valid weekly records evaluated"
        if conf:
            print(f"{head}; pre-registered test: mean IC {conf['mean_ic']}, t {conf['t_stat']}, p {conf['p_value']} "
                  f"(required < {conf['required_p']}): {'CONFIRMED' if conf['confirmed'] else 'NOT CONFIRMED'}")
        else:
            print(f"{head}; interim mean IC {interim['mean_ic']} over {interim['n_weeks']} weeks "
                  f"(no test before {h['required']})")
