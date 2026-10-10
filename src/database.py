#!/usr/bin/env python3
"""
Database - provenance layer (phase P0.2)

Single owner of the SQLite schema. Every stored value can be traced back to:
  source  -> which provider, with a fixed reliability rank (SOURCES)
  fetch   -> one row in source_fetches per HTTP call / download (status, error, timing)
  raw     -> the raw payload on disk (data/raw/, gzip, content-addressed by SHA-256,
             secrets redacted before writing)
  time    -> as_of_date (period the value refers to), published_at (when it became
             public at the source) and retrieved_at (when we obtained this version)

Look-ahead rule: a value may be used at instant T only if it was available at T,
i.e. COALESCE(published_at, retrieved_at) <= T. When the source does not give a
publication time, published_at is NULL and the retrieval time is the only safe bound.
strict_vintage=True additionally requires retrieved_at <= T (the exact stored version
was in our hands at T), for values that sources revise retroactively (adjusted prices).

Schema history:
  v0/v1  ad-hoc tables created by each module (sec_data, macro_data, backtest_results,
         backtest_fixed, insider_transactions) and the unused tables of this file
         (fundamentals, prices, calendar_events, macro_indicators). Their publication
         timestamps cannot be established and some carried invented "confidence"
         numbers, so they are backed up, exported and DROPPED, then refilled from
         the real sources by the next run.
  v2     source_fetches, observations, backtest_results (provenance-aware).
"""

import gzip
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from .common import (backups_dir, data_dir, db_path, raw_dir, redact, to_utc_iso,
                     utc_now_iso, REDACTED, SECRET_ENV_VARS)

SCHEMA_VERSION = 2

# Lower rank = more authoritative. Used to order conflicting values for the same fact.
SOURCES = {
    'SEC EDGAR': {'rank': 1, 'kind': 'official regulatory filings (U.S. SEC)'},
    'FRED': {'rank': 1, 'kind': 'official statistics (Federal Reserve Bank of St. Louis)'},
    'yfinance': {'rank': 2, 'kind': 'unofficial market data (Yahoo Finance via yfinance)'},
    'NewsAPI': {'rank': 3, 'kind': 'news aggregator (not a primary source)'},
    'S&P 500 list (datasets/s-and-p-500-companies)': {
        'rank': 3, 'kind': 'third-party compiled list of current S&P 500 members (GitHub)'},
}

# Maximum age (days) of as_of_date for a value to count as FRESH, per update cadence.
CADENCE_MAX_AGE_DAYS = {
    'daily_market': 5,     # trading sessions: weekend + holiday
    'daily': 7,            # daily official series (published with a lag)
    'weekly': 14,          # weekly official series (jobless claims, NFCI, mortgage rates)
    'event': 14,           # event filings (8-K, Form 4, 144, 13D/G, S-3 / 424B, NT 10-x)
    'monthly': 80,         # monthly series: period start + ~6 weeks publication lag
    'quarterly_filing': 120,  # 10-Q / 10-K publication date
    'news': 7,
}

LEGACY_TABLES = ('sec_data', 'macro_data', 'backtest_results', 'backtest_fixed',
                 'insider_transactions', 'fundamentals', 'prices', 'calendar_events',
                 'macro_indicators')

SECRET_PARAM_NAMES = {'api_key', 'apikey', 'token', 'access_token'}

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS source_fetches (
    fetch_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    endpoint        TEXT NOT NULL,          -- URL / call description, secrets removed
    request_params  TEXT,                   -- JSON, secret parameters removed
    requested_at    TEXT NOT NULL,
    completed_at    TEXT NOT NULL,          -- = retrieved_at of everything it produced
    status          TEXT NOT NULL,          -- OK / DATA UNAVAILABLE
    http_status     INTEGER,
    error           TEXT,                   -- redacted
    n_records       INTEGER,
    raw_path        TEXT,                   -- relative to the data directory
    raw_sha256      TEXT,                   -- SHA-256 of the stored (uncompressed) payload
    raw_bytes       INTEGER,
    CHECK (requested_at <= completed_at)
);

CREATE TABLE IF NOT EXISTS observations (
    obs_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,
    source_rank         INTEGER NOT NULL,
    entity              TEXT NOT NULL,      -- ticker or series id
    metric              TEXT NOT NULL,
    as_of_date          TEXT NOT NULL,      -- date / period the value refers to
    value               REAL,
    value_text          TEXT,
    unit                TEXT,
    published_at        TEXT,               -- when it became public; NULL = unknown
    published_at_basis  TEXT NOT NULL,      -- how published_at was determined
    value_revisable     INTEGER NOT NULL DEFAULT 0,
    retrieved_at        TEXT NOT NULL,
    fetch_id            INTEGER NOT NULL REFERENCES source_fetches(fetch_id),
    CHECK (published_at IS NULL OR published_at <= retrieved_at),
    CHECK (value IS NOT NULL OR value_text IS NOT NULL)
);
-- A version is identified by its fact key + publication + fetch. Text-only
-- observations are events (filings, articles): their identifier is part of the key.
CREATE UNIQUE INDEX IF NOT EXISTS ux_observations_version ON observations
    (source, entity, metric, as_of_date, COALESCE(published_at, ''),
     CASE WHEN value IS NULL THEN value_text ELSE '' END, fetch_id);
CREATE INDEX IF NOT EXISTS ix_observations_lookup ON observations (entity, metric, as_of_date);

CREATE TABLE IF NOT EXISTS backtest_results (
    ticker              TEXT NOT NULL,
    signal_date         TEXT NOT NULL,
    horizon_days        INTEGER NOT NULL,
    predicted_signal    TEXT NOT NULL,
    actual_direction    TEXT NOT NULL,
    correct             INTEGER NOT NULL,
    forward_return_pct  REAL NOT NULL,
    outcome_date        TEXT NOT NULL,      -- session whose close resolves the outcome
    method              TEXT NOT NULL,
    price_fetch_id      INTEGER NOT NULL REFERENCES source_fetches(fetch_id),
    computed_at         TEXT NOT NULL,
    PRIMARY KEY (ticker, signal_date, horizon_days, method, price_fetch_id),
    CHECK (signal_date < outcome_date)
);
"""


def source_rank(source):
    if source not in SOURCES:
        raise ValueError(f'unknown source {source!r}; register it in database.SOURCES')
    return SOURCES[source]['rank']


def freshness(as_of_date, cadence, now=None):
    """FRESH / STALE / UNKNOWN from the age of as_of_date against the cadence limit."""
    max_age = CADENCE_MAX_AGE_DAYS.get(cadence)
    if as_of_date is None or max_age is None:
        return {'status': 'UNKNOWN', 'as_of_date': as_of_date, 'age_days': None,
                'max_age_days': max_age, 'cadence': cadence}
    ref = as_of_date if isinstance(as_of_date, date) else date.fromisoformat(str(as_of_date)[:10])
    today = (now or datetime.now(timezone.utc)).date()
    age = (today - ref).days
    return {'status': 'FRESH' if age <= max_age else 'STALE', 'as_of_date': str(ref),
            'age_days': age, 'max_age_days': max_age, 'cadence': cadence}


def _clean_params(params):
    if not params:
        return None
    return json.dumps({k: (REDACTED if k.lower() in SECRET_PARAM_NAMES else v)
                       for k, v in sorted(params.items())}, default=str)


class Database:
    """Provenance-aware storage. Creating an instance migrates the schema if needed."""

    def __init__(self, path=None, verbose=False):
        self.db_path = str(path or db_path())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self.last_migration = None
        self.migrate()
        self.ensure_indexes()

    # ------------------------------------------------------------------ connection

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=60)   # concurrent runs: wait for the write lock
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def schema_version(self):
        with self.connect() as conn:
            return conn.execute('PRAGMA user_version').fetchone()[0]

    def tables(self):
        with self.connect() as conn:
            return sorted(r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))

    # ------------------------------------------------------------------ migration

    def backup(self, label):
        """
        Copy the whole database (SQLite backup API) and export every table to JSON.
        Returns {'db': path, 'export': path, 'row_counts': {...}}; raises if the copy
        does not contain the same row counts as the original.
        """
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        stem = f"{Path(self.db_path).stem}_{label}_{stamp}"
        target_db = backups_dir() / f'{stem}.db'
        target_json = backups_dir() / f'{stem}_export.json'

        src = sqlite3.connect(self.db_path)
        dst = sqlite3.connect(target_db)
        try:
            src.backup(dst)
        finally:
            dst.close()

        export, counts = {}, {}
        try:
            names = [r[0] for r in src.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for name in names:
                cur = src.execute(f'SELECT * FROM "{name}"')
                columns = [d[0] for d in cur.description]
                rows = [list(r) for r in cur.fetchall()]
                export[name] = {'columns': columns, 'rows': rows}
                counts[name] = len(rows)
        finally:
            src.close()

        check = sqlite3.connect(target_db)
        try:
            for name, n in counts.items():
                copied = check.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                if copied != n:
                    raise RuntimeError(f'backup verification failed for {name}: {copied} != {n}')
        finally:
            check.close()

        target_json.write_text(json.dumps({
            'source_db': self.db_path, 'exported_at': utc_now_iso(),
            'schema_version': None, 'tables': export}, indent=1, default=str), encoding='utf-8')
        return {'db': str(target_db), 'export': str(target_json), 'row_counts': counts}

    def migrate(self):
        with self.connect() as conn:
            version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version >= SCHEMA_VERSION:
            return None

        legacy = [t for t in self.tables() if t in LEGACY_TABLES]
        info = {'from_version': version, 'to_version': SCHEMA_VERSION,
                'dropped_tables': legacy, 'backup': None}
        if legacy:
            # Back up BEFORE dropping anything; backup() raises if verification fails.
            info['backup'] = self.backup(f'pre_v{SCHEMA_VERSION}')
            with self.connect() as conn:
                for name in legacy:
                    conn.execute(f'DROP TABLE IF EXISTS "{name}"')
            print(f"  [DATABASE] schema v{version} -> v{SCHEMA_VERSION}: legacy tables "
                  f"{', '.join(legacy)} backed up to {info['backup']['db']} and dropped "
                  f"(publication timestamps not recoverable; refilled from sources).")

        with self.connect() as conn:
            conn.executescript(SCHEMA_V2)
            conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        self.last_migration = info
        return info

    def ensure_indexes(self):
        """Indexes added after schema v2 (idempotent): cache lookups by endpoint."""
        with self.connect() as conn:
            conn.execute('CREATE INDEX IF NOT EXISTS ix_fetches_endpoint ON source_fetches '
                         '(source, endpoint, completed_at)')
        # WAL: readers never block writers (a long read query stalled a concurrent download
        # with 'database is locked'). The mode is stored in the database file.
        conn = sqlite3.connect(self.db_path, timeout=60)
        try:
            conn.execute('PRAGMA journal_mode=WAL')
        except sqlite3.OperationalError:
            pass                    # another process holds a lock: keep the current mode
        finally:
            conn.close()

    # ------------------------------------------------------------------ fetch log + raw

    @staticmethod
    def _payload_bytes(raw):
        if raw is None:
            return None
        if isinstance(raw, bytes):
            text = raw.decode('utf-8', errors='replace')
        elif isinstance(raw, str):
            text = raw
        else:
            text = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
        text = redact(text)
        for name in SECRET_ENV_VARS:
            secret = os.getenv(name, '').strip().strip('<>').strip()
            if len(secret) >= 6 and secret in text:
                raise RuntimeError(f'refusing to store raw payload containing {name}')
        return text.encode('utf-8')

    def store_raw(self, source, payload, ext='json'):
        """Write a redacted payload under data/raw/<source>/<sha[:2]>/<sha>.<ext>.gz (deduplicated)."""
        data = self._payload_bytes(payload)
        if data is None:
            return None
        sha = hashlib.sha256(data).hexdigest()
        slug = ''.join(c if c.isalnum() else '_' for c in source.lower()).strip('_')
        target = raw_dir() / slug / sha[:2] / f'{sha}.{ext}.gz'
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix('.tmp')
            with open(tmp, 'wb') as fh:
                with gzip.GzipFile(fileobj=fh, mode='wb', mtime=0) as gz:
                    gz.write(data)
            tmp.replace(target)
        return {'raw_path': str(target.relative_to(data_dir())), 'raw_sha256': sha,
                'raw_bytes': len(data)}

    def record_fetch(self, source, endpoint, *, requested_at=None, status, params=None,
                     http_status=None, error=None, raw=None, raw_ext='json', n_records=None):
        """
        Log one call to a source (success or failure) and store its raw payload.
        requested_at None: the call started now (callers that may not read the clock, e.g. weekly
        report sections, let the database layer timestamp it).
        """
        source_rank(source)
        completed_at = utc_now_iso()
        requested_at = requested_at or completed_at
        stored = self.store_raw(source, raw, raw_ext) if raw is not None else None
        with self.connect() as conn:
            cur = conn.execute(
                '''INSERT INTO source_fetches (source, endpoint, request_params, requested_at,
                       completed_at, status, http_status, error, n_records, raw_path,
                       raw_sha256, raw_bytes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (source, redact(endpoint), _clean_params(params), to_utc_iso(requested_at),
                 completed_at, status, http_status, redact(error), n_records,
                 stored and stored['raw_path'], stored and stored['raw_sha256'],
                 stored and stored['raw_bytes']))
            fetch_id = cur.lastrowid
        return {'fetch_id': fetch_id, 'source': source, 'retrieved_at': completed_at,
                'status': status, **(stored or {})}

    def get_fetch(self, fetch_id):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM source_fetches WHERE fetch_id=?', (fetch_id,)).fetchone()
        return dict(row) if row else None

    def latest_fetch(self, source, endpoint, since=None):
        """
        Most recent successful fetch of `endpoint` with a stored raw payload, completed
        after `since` (any time when None). Used to reuse immutable or recent documents
        instead of downloading them again. Returns a fetch dict like record_fetch.
        """
        sql = ("SELECT * FROM source_fetches WHERE source=? AND endpoint=? AND status='OK' "
               "AND raw_path IS NOT NULL")
        args = [source, redact(endpoint)]
        if since is not None:
            sql += ' AND completed_at >= ?'
            args.append(to_utc_iso(since))
        with self.connect() as conn:
            row = conn.execute(sql + ' ORDER BY completed_at DESC, fetch_id DESC LIMIT 1',
                               args).fetchone()
        if not row:
            return None
        return {'fetch_id': row['fetch_id'], 'source': row['source'],
                'retrieved_at': row['completed_at'], 'status': row['status'],
                'raw_path': row['raw_path'], 'raw_sha256': row['raw_sha256'],
                'raw_bytes': row['raw_bytes'], 'reused': True}

    def read_raw(self, fetch_id):
        """Decompressed raw payload of a fetch, after checking its SHA-256."""
        fetch = self.get_fetch(fetch_id)
        if not fetch or not fetch['raw_path']:
            return None
        data = gzip.decompress((data_dir() / fetch['raw_path']).read_bytes())
        if hashlib.sha256(data).hexdigest() != fetch['raw_sha256']:
            raise RuntimeError(f'raw payload of fetch {fetch_id} does not match its SHA-256')
        return data.decode('utf-8')

    # ------------------------------------------------------------------ observations

    def upsert_observations(self, fetch, rows):
        """
        Store observations produced by `fetch` (dict returned by record_fetch).
        rows: dicts with entity, metric, as_of_date, value and/or value_text, and optional
        unit, published_at, published_at_basis, value_revisable.
        A version identical to the latest stored one (same key and value) is skipped;
        a different value is stored as a new version - history is never overwritten.
        published_at later than retrieval is clamped to retrieval (it was public by then).
        Returns the number of new rows.
        """
        source = fetch['source']
        rank = source_rank(source)
        retrieved_at = fetch['retrieved_at']
        prepared = []
        for r in rows:
            published = to_utc_iso(r.get('published_at'))
            basis = r.get('published_at_basis') or ('unknown' if published is None else 'source')
            if published is not None and published > retrieved_at:
                published, basis = retrieved_at, basis + '; clamped to retrieval time'
            value = r.get('value')
            prepared.append((r['entity'], r['metric'], str(r['as_of_date'])[:10],
                             None if value is None else float(value), r.get('value_text'),
                             r.get('unit'), published, basis, int(bool(r.get('value_revisable')))))
        if not prepared:
            return 0

        keys = {(p[0], p[1]) for p in prepared}
        latest = {}
        with self.connect() as conn:
            for entity, metric in keys:
                for row in conn.execute(
                        '''SELECT as_of_date, COALESCE(published_at, '') AS pub, value, value_text
                           FROM observations WHERE source=? AND entity=? AND metric=?
                           ORDER BY retrieved_at''', (source, entity, metric)):
                    event_id = row['value_text'] if row['value'] is None else ''
                    latest[(entity, metric, row['as_of_date'], row['pub'], event_id)] = \
                        (row['value'], row['value_text'])

            new = []
            for p in prepared:
                key = (p[0], p[1], p[2], p[6] or '', p[4] if p[3] is None else '')
                if key in latest and latest[key] == (p[3], p[4]):
                    continue
                latest[key] = (p[3], p[4])
                new.append((source, rank, *p, retrieved_at, fetch['fetch_id']))
            conn.executemany(
                '''INSERT INTO observations (source, source_rank, entity, metric, as_of_date, value,
                       value_text, unit, published_at, published_at_basis, value_revisable,
                       retrieved_at, fetch_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                [(n[0], n[1], n[2], n[3], n[4], n[5], n[6], n[7], n[8], n[9], n[10], n[11], n[12])
                 for n in new])
        return len(new)

    @staticmethod
    def _known_filter(known_at, strict_vintage):
        sql, args = '', []
        if known_at is not None:
            sql += ' AND COALESCE(published_at, retrieved_at) <= ?'
            args.append(to_utc_iso(known_at))
            if strict_vintage:
                sql += ' AND retrieved_at <= ?'
                args.append(to_utc_iso(known_at))
        return sql, args

    def series(self, entity, metric, known_at=None, source=None, strict_vintage=False,
               start=None, end=None):
        """
        [(as_of_date, row)] one version per as_of_date: the latest version available at
        known_at (all stored versions when known_at is None), best-ranked source first.
        """
        sql = 'SELECT * FROM observations WHERE entity=? AND metric=?'
        args = [entity, metric]
        if source:
            sql += ' AND source=?'
            args.append(source)
        if start:
            sql += ' AND as_of_date >= ?'
            args.append(str(start)[:10])
        if end:
            sql += ' AND as_of_date <= ?'
            args.append(str(end)[:10])
        extra, extra_args = self._known_filter(known_at, strict_vintage)
        sql += extra + (' ORDER BY as_of_date, source_rank DESC, '
                        'COALESCE(published_at, retrieved_at), retrieved_at')
        with self.connect() as conn:
            rows = conn.execute(sql, args + extra_args).fetchall()
        chosen = {}
        for row in rows:          # later rows (better rank, more recent) overwrite earlier ones
            chosen[row['as_of_date']] = dict(row)
        return sorted(chosen.items())

    def get_point_in_time(self, entity, metric, known_at=None, as_of_date=None, source=None,
                          strict_vintage=False):
        """
        Most recent observation (by as_of_date <= as_of_date) that was available at
        known_at, with any conflicting values from other sources for the same date.
        """
        rows = self.series(entity, metric, known_at=known_at, source=source,
                           strict_vintage=strict_vintage, end=as_of_date)
        if not rows:
            return None
        best = rows[-1][1]
        best['conflicts'] = self.conflicts(entity, metric, best['as_of_date'], known_at,
                                           exclude_source=best['source'], value=best['value'])
        return best

    def conflicts(self, entity, metric, as_of_date, known_at=None, exclude_source=None, value=None):
        """Values from other sources for the same fact that differ from `value`."""
        sql = 'SELECT source, source_rank, value, value_text FROM observations ' \
              'WHERE entity=? AND metric=? AND as_of_date=?'
        args = [entity, metric, as_of_date]
        if exclude_source:
            sql += ' AND source != ?'
            args.append(exclude_source)
        extra, extra_args = self._known_filter(known_at, False)
        with self.connect() as conn:
            rows = conn.execute(sql + extra, args + extra_args).fetchall()
        return [dict(r) for r in rows if value is None or r['value'] != value]

    def events(self, entity, metric, published_from=None, published_to=None, source=None):
        """
        Distinct event observations (e.g. filings) whose availability time
        COALESCE(published_at, retrieved_at) is in (published_from, published_to].
        """
        sql = ('SELECT as_of_date, value_text, '
               'MIN(COALESCE(published_at, retrieved_at)) AS available_at '
               'FROM observations WHERE entity=? AND metric=?')
        args = [entity, metric]
        if source:
            sql += ' AND source=?'
            args.append(source)
        sql += ' GROUP BY as_of_date, value_text HAVING 1=1'
        if published_from is not None:
            sql += ' AND available_at > ?'
            args.append(to_utc_iso(published_from))
        if published_to is not None:
            sql += ' AND available_at <= ?'
            args.append(to_utc_iso(published_to))
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql + ' ORDER BY available_at', args)]

    def count(self, table):
        with self.connect() as conn:
            return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

    # ------------------------------------------------------------------ provenance

    @staticmethod
    def provenance(fetch, cadence=None, as_of_date=None, published_at=None,
                   published_at_basis=None, freshness_date=None):
        """Provenance block for module outputs (freshness on freshness_date, else as_of_date)."""
        source = fetch['source'] if fetch else None
        return {
            'source': source,
            'source_rank': SOURCES[source]['rank'] if source in SOURCES else None,
            'source_kind': SOURCES[source]['kind'] if source in SOURCES else None,
            'fetch_id': fetch.get('fetch_id') if fetch else None,
            'retrieved_at': fetch.get('retrieved_at') if fetch else None,
            'raw_sha256': fetch.get('raw_sha256') if fetch else None,
            'as_of_date': str(as_of_date)[:10] if as_of_date else None,
            'published_at': to_utc_iso(published_at),
            'published_at_basis': published_at_basis,
            'freshness': freshness(freshness_date or as_of_date, cadence),
        }

    # ------------------------------------------------------------------ backtest

    def save_backtest_results(self, rows):
        with self.connect() as conn:
            conn.executemany(
                '''INSERT OR REPLACE INTO backtest_results (ticker, signal_date, horizon_days,
                       predicted_signal, actual_direction, correct, forward_return_pct,
                       outcome_date, method, price_fetch_id, computed_at)
                   VALUES (:ticker, :signal_date, :horizon_days, :predicted_signal,
                           :actual_direction, :correct, :forward_return_pct, :outcome_date,
                           :method, :price_fetch_id, :computed_at)''', rows)
        return len(rows)


if __name__ == "__main__":
    db = Database(verbose=True)
    print(f"Database: {db.db_path} (schema v{db.schema_version()})")
    for t in db.tables():
        print(f"  {t:20} {db.count(t)} rows")
