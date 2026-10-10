#!/usr/bin/env python3
"""
Common helpers shared by all modules (Phase P0.1).

- Explicit "DATA UNAVAILABLE" status instead of silent neutral defaults
- Single source of truth for data/report paths (no more cwd-relative paths)
- Universe configuration loaded from scheduler_config.json
- Timezone-aware UTC timestamps

P0.2 additions:
- redact(): secrets are masked in every error / reason / report (FRED errors used to
  print the request URL including api_key).
- secret_env(): reads an API key and rejects obvious placeholders such as "<key>".
- to_utc_iso(): one timestamp format, so ISO strings compare correctly in SQLite.
- raw_dir() / backups_dir() for raw source payloads and database backups.
"""

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DATA_UNAVAILABLE = 'DATA UNAVAILABLE'
NOT_IMPLEMENTED = 'NOT IMPLEMENTED'
NA_DISPLAY = 'N/A — source unavailable'

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / 'scheduler_config.json'


SECRET_ENV_VARS = ('FRED_API_KEY', 'NEWSAPI_KEY')
REDACTED = '***REDACTED***'
_SECRET_PARAM_RE = re.compile(r'((?:api_?key|apikey|token|access_token)=)[^&\s\'"]+', re.IGNORECASE)


def utc_now_iso():
    """Current time as an ISO-8601 UTC timestamp (timezone-aware)."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def to_utc_iso(value):
    """
    Normalize a datetime / ISO string to 'YYYY-MM-DDTHH:MM:SS+00:00' (None stays None).
    Naive values are assumed to be UTC. A single format keeps SQLite string comparisons valid.
    """
    if value is None or value == '':
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    elif isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def end_of_us_trading_day_utc(day):
    """
    Conservative UTC instant after which a US-dated publication (FRED vintage date,
    market session) is certainly public: 05:00 UTC the next day = midnight New York (EST).
    """
    day = date.fromisoformat(day) if isinstance(day, str) else day
    nxt = day + timedelta(days=1)
    return to_utc_iso(datetime(nxt.year, nxt.month, nxt.day, 5, 0, 0, tzinfo=timezone.utc))


def redact(text):
    """Mask API keys: values of known secret env vars and key-like URL parameters."""
    if text is None:
        return None
    text = str(text)
    for name in SECRET_ENV_VARS:
        raw = os.getenv(name, '').strip()
        for secret in {raw, raw.strip('<>').strip()}:
            if len(secret) >= 6:
                text = text.replace(secret, REDACTED)
    return _SECRET_PARAM_RE.sub(lambda m: m.group(1) + REDACTED, text)


def secret_env(name):
    """
    Return (value, problem) for an API key environment variable.
    problem is None when the value looks usable, otherwise a human-readable reason;
    the value is never included in the reason.
    """
    value = os.getenv(name, '').strip()
    if not value or value.lower() == 'demo':
        return None, f'{name} not set'
    if value.startswith('<') or value.endswith('>'):
        return None, f'{name} looks like a placeholder (remove the surrounding < >)'
    if any(ch.isspace() for ch in value):
        return None, f'{name} contains whitespace'
    return value, None


def data_dir():
    """Directory holding the SQLite database (override with TRADING_AGENT_DATA_DIR)."""
    path = Path(os.getenv('TRADING_AGENT_DATA_DIR', PROJECT_ROOT / 'data'))
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path():
    return str(data_dir() / 'trading_pro.db')


def raw_dir():
    """Raw source payloads (content-addressed, gzip). Excluded from git with data/."""
    path = data_dir() / 'raw'
    path.mkdir(parents=True, exist_ok=True)
    return path


def backups_dir():
    path = data_dir() / 'backups'
    path.mkdir(parents=True, exist_ok=True)
    return path


def reports_dir():
    """Directory for generated reports (override with TRADING_AGENT_REPORTS_DIR)."""
    path = Path(os.getenv('TRADING_AGENT_REPORTS_DIR', PROJECT_ROOT / 'reports'))
    path.mkdir(parents=True, exist_ok=True)
    return path


def history_dir():
    """Immutable per-run copies of reports (weekly reports need 'the latest run before T')."""
    path = reports_dir() / 'history'
    path.mkdir(parents=True, exist_ok=True)
    return path


def stamp(instant):
    """Filesystem-safe UTC stamp of an ISO instant: 2026-10-07T09:15:12+00:00 -> 20261007T091512Z."""
    return to_utc_iso(instant).replace('-', '').replace(':', '').replace('+0000', 'Z')


def load_config():
    """Load the universe/scheduling configuration."""
    with open(CONFIG_PATH, encoding='utf-8-sig') as f:
        return json.load(f)


def tickers():
    return list(load_config().get('stocks', []))


def validation_universe():
    """Tickers for walk-forward validation (defaults to the daily universe)."""
    return list(load_config().get('validation_universe') or tickers())


def company_name(ticker):
    """Company name used for news queries; falls back to the ticker."""
    return load_config().get('companies', {}).get(ticker, ticker)


def unavailable(source, reason, **extra):
    """Standard payload for a value/source that could not be obtained."""
    payload = {
        'status': DATA_UNAVAILABLE,
        'source': source,
        'reason': redact(reason),
        'checked_at': utc_now_iso(),
    }
    payload.update(extra)
    return payload


def is_missing(value):
    """True for None and NaN."""
    return value is None or (isinstance(value, float) and value != value)


def display(value, fmt=None, suffix=''):
    """Render a value for reports; missing values never get a placeholder number."""
    if is_missing(value) or value == DATA_UNAVAILABLE:
        return NA_DISPLAY
    if fmt and isinstance(value, (int, float)):
        return f"{value:{fmt}}{suffix}"
    return f"{value}{suffix}"


def close_series(data):
    """
    Extract the Close column as a 1-D Series from a yfinance DataFrame.
    Recent yfinance versions return MultiIndex columns even for one ticker.
    """
    close = data['Close']
    if hasattr(close, 'columns'):
        close = close.iloc[:, 0]
    return close.dropna()
