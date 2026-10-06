"""
Test configuration.

All tests run OFFLINE: every HTTP request and every yfinance download is blocked
by default, so a test can never silently depend on (or fabricate) live data.
Synthetic prices used in some tests exist only to check calculation logic; they
never reach a report outside the test's temporary directory.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class NetworkBlocked(requests.exceptions.ConnectionError):
    pass


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """Isolate filesystem and block all network access."""
    monkeypatch.setenv('TRADING_AGENT_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('TRADING_AGENT_REPORTS_DIR', str(tmp_path / 'reports'))
    for var in ('SEC_USER_AGENT', 'FRED_API_KEY', 'NEWSAPI_KEY'):
        monkeypatch.delenv(var, raising=False)

    def blocked_request(self, method, url, *args, **kwargs):
        raise NetworkBlocked(f'network disabled in tests: {method} {url}')

    monkeypatch.setattr(requests.sessions.Session, 'request', blocked_request)

    import yfinance
    monkeypatch.setattr(yfinance, 'download', lambda *a, **k: pd.DataFrame())
    return tmp_path


def make_price_frame(n=500, seed=0, multiindex=True, ticker='TEST'):
    """Synthetic adjusted-close frame shaped like recent yfinance output (logic tests only)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end='2026-09-30', periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    frame = pd.DataFrame({'Close': close, 'Volume': 1_000_000}, index=dates)
    if multiindex:
        frame.columns = pd.MultiIndex.from_product([frame.columns, [ticker]])
    return frame


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f'HTTP {self.status_code}')
