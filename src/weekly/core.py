#!/usr/bin/env python3
"""
Weekly analyst report - core contract (phase P3.0)

Time model (every section uses it; no wall-clock reads inside sections):
  sessions   trading sessions observed in the SPY daily bars (yfinance, rank 2)
  s_0        last session whose end of day EOD(s_0) <= the requested cutoff
  T_c        EOD(s_0) = 05:00 UTC on the next calendar day (common.end_of_us_trading_day_utc)
  T_p        EOD(s_-5), the previous weekly cutoff
  window P   (T_p, T_c]: a fact belongs to the week when its availability time is in P
  W          the 5 sessions s_-4 .. s_0

Evidence and conclusions (docs/DATA_POLICY.md, "Evidence levels for conclusions"):
  evidence(...)   one cited fact: source, rank, value/fact text, as_of, published_at,
                  retrieved_at, fetch_id, freshness at T_c. Evidence published after T_c raises
                  LookAheadError (an audit FAIL, never silently accepted).
  conclude(...)   a conclusion with its evidence and a kind; the level is DECIDED here from the
                  rules, sections never set it:
      official_fact   STRONGLY SUPPORTED if every item is rank 1, fresh and unconflicted
      system_output   STRONGLY SUPPORTED (deterministic statement about this system)
      market_fact     rank-2 prices: STRONGLY SUPPORTED only with an independent agreeing
                      source (cross_checked=True), else UNCERTAIN (SINGLE_RANK2_SOURCE)
      model_output    UNCERTAIN (MODEL_NOT_VALIDATED) unless validation is DEMONSTRATED
      aggregator      UNCERTAIN (AGGREGATOR_ONLY)
      interpretation  UNCERTAIN (INTERPRETIVE)
    any extra reason code (stale, partial coverage, revision noise, conflict...) -> UNCERTAIN.
  unavailable(...)  DATA UNAVAILABLE item with a mandatory reason (never a conclusion).

Section contract: build(ctx) -> SectionResult with tables, conclusions, unavailable items and
notes; sections never write files and never call datetime.now().
"""

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone

from ..common import end_of_us_trading_day_utc, redact, reports_dir, to_utc_iso

STRONG, UNCERTAIN, UNAVAILABLE = 'STRONGLY SUPPORTED', 'UNCERTAIN', 'DATA UNAVAILABLE'
KINDS = ('official_fact', 'system_output', 'market_fact', 'model_output', 'aggregator',
         'interpretation')
REASON_CODES = (
    'SINGLE_RANK2_SOURCE', 'AGGREGATOR_ONLY', 'NOT_INDEPENDENT', 'STALE_AT_CUTOFF',
    'FRESHNESS_UNKNOWN', 'FIRST_PRINT_WITHIN_REVISION_NOISE', 'CONFLICTING_SOURCES',
    'TIMESTAMP_AMBIGUOUS', 'PARTIAL_COVERAGE', 'COMPARABILITY_BREAK', 'HEURISTIC_THRESHOLD',
    'MODEL_NOT_VALIDATED', 'INTERPRETIVE', 'ESTIMATE', 'BELOW_THRESHOLD')
WEEK_SESSIONS = 5
NEWS_DELAY_HOURS = 26        # NewsAPI free plan: results end ~24 h before retrieval (+ margin)


class LookAheadError(RuntimeError):
    """Evidence published after the cutoff was offered to a conclusion."""


# ---------------------------------------------------------------- time model

class TimeModel:
    def __init__(self, sessions, requested_cutoff=None, generated_at=None):
        """
        sessions: sorted ISO dates of trading sessions (from observed SPY bars).
        requested_cutoff: instant (default: generated_at); s_0 is the last session with
        EOD(s_0) <= requested_cutoff. generated_at: when the report is produced (G).
        """
        self.generated_at = to_utc_iso(generated_at) or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        requested = to_utc_iso(requested_cutoff) or self.generated_at
        eligible = [s for s in sessions if end_of_us_trading_day_utc(s) <= requested]
        if len(eligible) < 2 * WEEK_SESSIONS + 1:
            raise ValueError('not enough completed sessions before the requested cutoff')
        self.sessions = eligible
        self.s0 = eligible[-1]
        self.week = eligible[-WEEK_SESSIONS:]
        self.previous_week = eligible[-2 * WEEK_SESSIONS:-WEEK_SESSIONS]
        self.cutoff = end_of_us_trading_day_utc(self.s0)
        self.previous_cutoff = end_of_us_trading_day_utc(eligible[-WEEK_SESSIONS - 1])
        self.next_sessions_known = [s for s in sessions if s > self.s0]

    def in_window(self, instant):
        t = to_utc_iso(instant)
        return t is not None and self.previous_cutoff < t <= self.cutoff

    def news_complete(self):
        """NewsAPI results end ~24 h before retrieval: complete for the window only after this."""
        need = datetime.fromisoformat(self.cutoff) + timedelta(hours=NEWS_DELAY_HOURS)
        return datetime.fromisoformat(self.generated_at) >= need

    def as_dict(self):
        return {'s0': self.s0, 'week_sessions': self.week, 'previous_week_sessions': self.previous_week,
                'cutoff': self.cutoff, 'previous_cutoff': self.previous_cutoff,
                'window': f'({self.previous_cutoff}, {self.cutoff}]', 'generated_at': self.generated_at,
                'news_complete_for_window': self.news_complete(),
                'session_calendar_source': 'sessions observed in SPY daily bars (yfinance, rank 2)'}


# ---------------------------------------------------------------- evidence / conclusions

def evidence(tm, source, rank, fact, *, as_of=None, published_at=None, retrieved_at=None,
             fetch_id=None, fresh=None, basis=None):
    """One cited fact. Raises LookAheadError when it was published after the cutoff."""
    pub = to_utc_iso(published_at)
    avail = pub or to_utc_iso(retrieved_at)
    if avail is not None and avail > tm.cutoff:
        raise LookAheadError(f'{source}: {fact!r} available at {avail}, after cutoff {tm.cutoff}')
    return {'source': source, 'rank': rank, 'fact': fact, 'as_of': as_of, 'published_at': pub,
            'published_at_basis': basis, 'retrieved_at': to_utc_iso(retrieved_at),
            'fetch_id': fetch_id, 'fresh_at_cutoff': fresh}


def conclude(scope, question, statement, items, kind, reason_codes=(), resolve=None,
             cross_checked=False, validation_demonstrated=False):
    """Conclusion with its level decided from the rules (see module docstring)."""
    if kind not in KINDS:
        raise ValueError(f'unknown kind {kind}')
    codes = list(dict.fromkeys(reason_codes))
    for code in codes:
        if code not in REASON_CODES:
            raise ValueError(f'unknown reason code {code}')
    if not items and kind != 'system_output':
        raise ValueError('a conclusion needs evidence; use unavailable() when there is none')
    for item in items:
        if item.get('fresh_at_cutoff') is False:
            codes.append('STALE_AT_CUTOFF')
        elif item.get('fresh_at_cutoff') is None and kind == 'official_fact':
            codes.append('FRESHNESS_UNKNOWN')
    if kind == 'official_fact' and any(i['rank'] != 1 for i in items):
        codes.append('NOT_INDEPENDENT' if len(items) > 1 else 'SINGLE_RANK2_SOURCE')
    if kind == 'market_fact' and not cross_checked:
        codes.append('SINGLE_RANK2_SOURCE')
    if kind == 'model_output' and not validation_demonstrated:
        codes.append('MODEL_NOT_VALIDATED')
    if kind == 'aggregator':
        codes.append('AGGREGATOR_ONLY')
    if kind == 'interpretation':
        codes.append('INTERPRETIVE')
    codes = list(dict.fromkeys(codes))
    level = STRONG if not codes and kind in ('official_fact', 'system_output', 'market_fact') else UNCERTAIN
    record = {'scope': scope, 'question': question, 'statement': statement, 'kind': kind,
              'level': level, 'reason_codes': codes, 'evidence': items}
    if level == UNCERTAIN:
        record['what_would_resolve_it'] = resolve or _default_resolution(codes)
    record['id'] = hashlib.sha256(json.dumps([scope, question, statement], sort_keys=True)
                                  .encode()).hexdigest()[:12]
    return record


def _default_resolution(codes):
    hints = {'SINGLE_RANK2_SOURCE': 'a second independent price source agreeing',
             'AGGREGATOR_ONLY': 'an official primary document (filing, regulator, issuer)',
             'STALE_AT_CUTOFF': 'a fresher observation published before the cutoff',
             'FRESHNESS_UNKNOWN': 'a source stating its publication date',
             'FIRST_PRINT_WITHIN_REVISION_NOISE': 'the next vintage of the series',
             'PARTIAL_COVERAGE': 'complete coverage of the window',
             'MODEL_NOT_VALIDATED': 'out-of-sample validation demonstrating predictive power',
             'INTERPRETIVE': 'none: interpretations remain uncertain by rule',
             'HEURISTIC_THRESHOLD': 'a validated threshold'}
    return '; '.join(hints.get(c, c.lower().replace('_', ' ')) for c in codes)


def unavailable(scope, question, item, reason):
    if not reason:
        raise ValueError('DATA UNAVAILABLE needs a reason')
    return {'scope': scope, 'question': question, 'item': item, 'level': UNAVAILABLE,
            'reason': redact(reason)}


class SectionResult:
    def __init__(self, name, questions):
        self.name, self.questions = name, list(questions)
        self.tables, self.conclusions, self.unavailable, self.notes = [], [], [], []

    def table(self, title, columns, rows, scope='overall', question=None, note=None):
        self.tables.append({'title': title, 'columns': list(columns), 'rows': [list(r) for r in rows],
                            'scope': scope, 'question': question, 'note': note})

    def add(self, record):
        (self.unavailable if record['level'] == UNAVAILABLE else self.conclusions).append(record)

    def as_dict(self):
        return {'name': self.name, 'questions': self.questions, 'tables': self.tables,
                'conclusions': self.conclusions, 'unavailable': self.unavailable, 'notes': self.notes}


# ---------------------------------------------------------------- archive

def code_version():
    try:
        out = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() + ('-dirty' if dirty.stdout.strip() else '') if out.returncode == 0 else None
    except Exception:  # noqa: BLE001 - version is informative only
        return None


def archive_dir(tm):
    return reports_dir() / 'weekly' / tm.s0


def write_archive(tm, payload, html):
    """Write weekly.json / weekly.html / manifest.json; never overwrite (new version suffix)."""
    base = archive_dir(tm)
    base.mkdir(parents=True, exist_ok=True)
    version = 1
    while (base / f'weekly_v{version}.json').exists():
        version += 1
    text = redact(json.dumps(payload, indent=1, default=str))
    (base / f'weekly_v{version}.json').write_text(text, encoding='utf-8')
    (base / f'weekly_v{version}.html').write_text(redact(html), encoding='utf-8')
    fetch_ids = sorted({e['fetch_id'] for s in payload['sections'] for c in s['conclusions']
                        for e in c['evidence'] if e.get('fetch_id')})
    manifest = {'version': version, 'cutoff': tm.cutoff, 's0': tm.s0, 'generated_at': tm.generated_at,
                'code_version': payload.get('code_version'), 'fetch_ids': fetch_ids,
                'sha256_json': hashlib.sha256(text.encode()).hexdigest()}
    (base / f'manifest_v{version}.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    return base / f'weekly_v{version}.html', base / f'weekly_v{version}.json'
