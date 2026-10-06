#!/usr/bin/env python3
"""
Common helpers shared by all modules (Phase P0.1).

- Explicit "DATA UNAVAILABLE" status instead of silent neutral defaults
- Single source of truth for data/report paths (no more cwd-relative paths)
- Universe configuration loaded from scheduler_config.json
- Timezone-aware UTC timestamps
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

DATA_UNAVAILABLE = 'DATA UNAVAILABLE'
NOT_IMPLEMENTED = 'NOT IMPLEMENTED'
NA_DISPLAY = 'N/A — source unavailable'

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / 'scheduler_config.json'


def utc_now_iso():
    """Current time as an ISO-8601 UTC timestamp (timezone-aware)."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def data_dir():
    """Directory holding the SQLite database (override with TRADING_AGENT_DATA_DIR)."""
    path = Path(os.getenv('TRADING_AGENT_DATA_DIR', PROJECT_ROOT / 'data'))
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path():
    return str(data_dir() / 'trading_pro.db')


def reports_dir():
    """Directory for generated reports (override with TRADING_AGENT_REPORTS_DIR)."""
    path = Path(os.getenv('TRADING_AGENT_REPORTS_DIR', PROJECT_ROOT / 'reports'))
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config():
    """Load the universe/scheduling configuration."""
    with open(CONFIG_PATH, encoding='utf-8-sig') as f:
        return json.load(f)


def tickers():
    return list(load_config().get('stocks', []))


def company_name(ticker):
    """Company name used for news queries; falls back to the ticker."""
    return load_config().get('companies', {}).get(ticker, ticker)


def unavailable(source, reason, **extra):
    """Standard payload for a value/source that could not be obtained."""
    payload = {
        'status': DATA_UNAVAILABLE,
        'source': source,
        'reason': reason,
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
