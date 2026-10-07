#!/usr/bin/env python3
"""
Market data - one provenance-aware yfinance price feed per run (phase P0.2)

Previously three modules downloaded the same prices separately and nothing was stored.
PriceFeed downloads once per ticker and run, logs the call in source_fetches, keeps the
raw CSV in data/raw/ and stores daily observations:

  close      split- and dividend-adjusted close (auto_adjust) -> value_revisable=1:
             Yahoo rewrites past adjusted prices after every split / dividend, so the
             stored version is only known from its retrieval time (strict_vintage).
  close_raw  close as reported by Yahoo (split-adjusted only), value_revisable=1.
  volume
published_at = 21:00 UTC on the session date (16:00 New York in winter, conservative in
summer). Sessions whose close is after the retrieval time (bar still in progress) are
dropped: a live intraday price is not a closing price.
"""

from datetime import date, datetime, time, timedelta, timezone

import pandas as pd
import yfinance as yf

from .common import to_utc_iso, utc_now_iso
from .database import Database

YF_SOURCE = 'yfinance'
SESSION_CLOSE_UTC = time(21, 0)


def session_close_utc(day):
    day = day if isinstance(day, date) else date.fromisoformat(str(day)[:10])
    return to_utc_iso(datetime.combine(day, SESSION_CLOSE_UTC, tzinfo=timezone.utc))


def _column(data, name):
    if name not in data:
        return None
    col = data[name]
    if hasattr(col, 'columns'):          # MultiIndex columns (recent yfinance)
        col = col.iloc[:, 0]
    return col


class PriceFeed:
    """Daily prices with provenance; one download per (ticker, lookback) per instance."""

    def __init__(self, db=None, lookback_days=730):
        self.db = db or Database()
        self.lookback_days = lookback_days
        self._cache = {}

    def _download(self, ticker, start, end):
        adjusted = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        unadjusted = None
        try:
            unadjusted = yf.download(ticker, start=start, end=end, progress=False,
                                     auto_adjust=False)
        except Exception:  # noqa: BLE001 - close_raw is optional
            unadjusted = None
        return adjusted, unadjusted

    def get(self, ticker):
        """
        {'status', 'close' (pd.Series of completed sessions), 'fetch', 'provenance', 'reason'}.
        """
        if ticker in self._cache:
            return self._cache[ticker]
        result = self._fetch(ticker)
        self._cache[ticker] = result
        return result

    def _fetch(self, ticker):
        end = datetime.now()
        start = end - timedelta(days=self.lookback_days)
        endpoint = f'yfinance.download({ticker})'
        params = {'start': start.date().isoformat(), 'end': end.date().isoformat(),
                  'interval': '1d'}
        requested_at = utc_now_iso()
        try:
            adjusted, unadjusted = self._download(ticker, start, end)
        except Exception as e:  # noqa: BLE001 - recorded and surfaced
            fetch = self.db.record_fetch(YF_SOURCE, endpoint, params=params,
                                         requested_at=requested_at, status='DATA UNAVAILABLE',
                                         error=f'{type(e).__name__}: {e}')
            return self._unavailable(fetch, f'{type(e).__name__}: {e}')

        close = _column(adjusted, 'Close') if adjusted is not None else None
        if close is None or close.dropna().empty:
            fetch = self.db.record_fetch(YF_SOURCE, endpoint, params=params,
                                         requested_at=requested_at, status='DATA UNAVAILABLE',
                                         error='yfinance returned no data', n_records=0)
            return self._unavailable(fetch, 'yfinance returned no data')

        frame = pd.DataFrame({'close': close})
        volume = _column(adjusted, 'Volume')
        if volume is not None:
            frame['volume'] = volume
        raw_close = _column(unadjusted, 'Close') if unadjusted is not None and not unadjusted.empty else None
        if raw_close is not None:
            frame['close_raw'] = raw_close
        frame = frame[frame['close'].notna()]
        frame.index = pd.to_datetime(frame.index).date

        retrieved_bound = utc_now_iso()
        completed = [d for d in frame.index if session_close_utc(d) <= retrieved_bound]
        dropped = len(frame) - len(completed)
        frame = frame.loc[completed]

        fetch = self.db.record_fetch(
            YF_SOURCE, endpoint, params=params, requested_at=requested_at, status='OK',
            raw=frame.to_csv(index_label='date'), raw_ext='csv', n_records=len(frame))

        rows = []
        for day, rec in frame.iterrows():
            published = session_close_utc(day)
            for metric, unit in (('close', 'USD'), ('close_raw', 'USD'), ('volume', 'shares')):
                if metric in rec and pd.notna(rec[metric]):
                    rows.append({'entity': ticker, 'metric': metric, 'as_of_date': day,
                                 'value': float(rec[metric]), 'unit': unit,
                                 'published_at': published,
                                 'published_at_basis': 'session close 21:00 UTC (estimate)',
                                 'value_revisable': metric != 'volume'})
        self.db.upsert_observations(fetch, rows)

        series = pd.Series(frame['close'].to_numpy(dtype=float),
                           index=pd.to_datetime(list(frame.index)), name='Close')
        last = frame.index[-1] if len(frame) else None
        full = frame.copy()
        full.index = pd.to_datetime(list(full.index))
        return {
            'status': 'OK' if len(frame) else 'DATA UNAVAILABLE',
            'close': series,
            'frame': full,          # close (adjusted), volume, close_raw (split-adjusted only)
            'fetch': fetch,
            'dropped_incomplete_sessions': dropped,
            'provenance': self.db.provenance(
                fetch, cadence='daily_market', as_of_date=last,
                published_at=session_close_utc(last) if last else None,
                published_at_basis='session close 21:00 UTC (estimate); adjusted prices '
                                   'are revised retroactively by Yahoo'),
            'reason': None if len(frame) else 'no completed session',
        }

    def _unavailable(self, fetch, reason):
        return {'status': 'DATA UNAVAILABLE', 'close': None, 'frame': None, 'fetch': fetch,
                'dropped_incomplete_sessions': 0,
                'provenance': self.db.provenance(fetch, cadence='daily_market'),
                'reason': reason}
