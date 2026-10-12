#!/usr/bin/env python3
"""
Technical indicators and price action (master mission P2) - reference implementations, descriptive only

These are NOT the indicators of the frozen heuristic signal (src/indicators.py, unchanged during stage 3). Inputs are
daily bars (pandas Series indexed by date): adjusted close / open / high / low (yfinance auto_adjust, rank 2) and
volume. No bar is ever filled: a missing session is a missing row, and every rolling statistic requires its full
window (min_periods = window); values inside a warm-up period are NaN, never a default.

Indicators (formula; period)
  sma(n)              arithmetic mean of the last n closes; n = 20, 50, 200
  ema(n)              recursive EMA, alpha = 2 / (n + 1), seeded with the SMA of the first n closes; n = 20, 50, 200
  rsi(14)             Wilder: first average gain / loss = mean of the first 14 changes, then
                      avg = (avg x 13 + current) / 14; RSI = 100 - 100 / (1 + avg gain / avg loss);
                      100 when avg loss = 0 and avg gain > 0; undefined (NaN) when both are 0
  macd(12, 26, 9)     EMA12 - EMA26 (seeded EMAs), signal = EMA9 of MACD, histogram = MACD - signal
  bollinger(20, 2)    middle = SMA20, bands = middle +/- 2 x population standard deviation (ddof 0, as defined by
                      Bollinger); %B = (close - lower) / (upper - lower); bandwidth = (upper - lower) / middle
  atr(14)             true range = max(high - low, |high - previous close|, |low - previous close|); Wilder average
  adx(14)             Wilder: +DM / -DM, smoothed with Wilder sums; +DI / -DI = 100 x DM / TR; DX = 100 x |+DI - -DI|
                      / (+DI + -DI); ADX = Wilder average of DX (first = mean of the first 14 DX)
  hist_vol(n)         sample standard deviation (ddof 1) of n daily log returns x sqrt(252); n = 20, 60
  momentum(n)         close / close n sessions earlier - 1; n = 21, 63, 126, 252 (about 1, 3, 6, 12 months);
                      momentum_12_1 = close 21 sessions ago / close 252 sessions ago - 1
  drawdown            close / highest close of the last 252 sessions - 1; max_drawdown_1y = worst such value
  relative_volume     volume / mean volume of the 20 previous sessions
  relative_strength   (1 + stock return) / (1 + benchmark return) - 1 over n sessions, both from the same calendar
  trend               'up' when close > SMA50 > SMA200 and SMA200 above its value 20 sessions earlier, 'down' when
                      the mirror holds, else 'mixed'; strength by ADX: >= 25 strong, < 20 weak (Wilder's usual
                      reading, a convention); persistence = share of the last 60 sessions with close > SMA50

Price action (objective rules)
  pivots(k=5)         swing high at i: high[i] is the strict maximum of high[i-k .. i+k]; swing low likewise on lows.
                      A pivot at i is only KNOWN at i + k (no look-ahead): pivots(known_at) excludes later ones
  levels              pivot prices of the last 252 sessions clustered when within LEVEL_TOLERANCE_ATR x ATR14 of the
                      cluster's first price (sorted by price); level = mean, touches = cluster size; nearest support
                      = highest level below the close, resistance = lowest level above it (estimates, not prices
                      that will hold)
  breakout(55)        close above the highest high of the previous 55 sessions / below the lowest low
  retracement         last completed swing = the latest confirmed pivot and the opposite pivot before it (k = 5);
                      retraced % = share of that leg given back by the close: up leg (high - close) / (high - low),
                      down leg (close - low) / (high - low); 0 = at the leg's end, 100 = back at its start, > 100
                      beyond it. Measured only; Fibonacci ratios are conventions and are not used as levels
  range_position      52-week (252-session) high and low of the closes and the distance of the close to each
  volatility regime   percentile of HV20 within its values over the last 756 sessions: < 20 low, > 80 high, else
                      normal (at least 252 values required)
  candles             on the last bar, with body = |close - open|, range = high - low: doji (body <= 10% of range);
                      bullish / bearish engulfing (previous body opposite and engulfed by the current body); hammer
                      (lower shadow >= 2 x body, upper shadow <= body, body > 0); shooting star (mirror). Patterns
                      are descriptions of one bar, not forecasts.
Not implemented: Dow theory, Elliott waves and Smart Money Concepts / ICT (their rules are not precise enough to be
reproduced and tested).
"""

import math

import numpy as np
import pandas as pd

NOT_IMPLEMENTED_METHODS = {
    'Dow theory': 'NOT IMPLEMENTED: trend confirmation rules depend on judgement (which swings count)',
    'Elliott waves': 'NOT IMPLEMENTED: wave counts are not unique and not reproducible',
    'Smart Money Concepts / ICT': 'NOT IMPLEMENTED: definitions (order blocks, liquidity) are not standardised',
}
PIVOT_K = 5
LEVEL_TOLERANCE_ATR = 0.5
LEVEL_LOOKBACK = 252
BREAKOUT_N = 55
REGIME_LOOKBACK = 756


def sma(x, n):
    return x.rolling(n, min_periods=n).mean()


def ema(x, n):
    """EMA seeded with the SMA of the first n values (NaN before)."""
    out = pd.Series(np.nan, index=x.index, dtype=float)
    values = x.to_numpy(dtype=float)
    if len(values) < n:
        return out
    alpha = 2 / (n + 1)
    current = values[:n].mean()
    result = [np.nan] * (n - 1) + [current]
    for v in values[n:]:
        current = alpha * v + (1 - alpha) * current
        result.append(current)
    return pd.Series(result, index=x.index, dtype=float)


def _wilder(values, n):
    """Wilder smoothing: first value = mean of the first n values, then (prev x (n - 1) + v) / n; NaN before."""
    out = [np.nan] * len(values)
    if len(values) < n:
        return out
    current = float(np.mean(values[:n]))
    out[n - 1] = current
    for i in range(n, len(values)):
        current = (current * (n - 1) + values[i]) / n
        out[i] = current
    return out


def rsi(close, n=14):
    delta = close.diff().to_numpy(dtype=float)[1:]
    gains, losses = np.clip(delta, 0, None), np.clip(-delta, 0, None)
    ag, al = _wilder(gains, n), _wilder(losses, n)
    out = [np.nan]
    for g, l in zip(ag, al):
        if math.isnan(g):
            out.append(np.nan)
        elif l == 0:
            out.append(100.0 if g > 0 else np.nan)
        else:
            out.append(100 - 100 / (1 + g / l))
    return pd.Series(out, index=close.index, dtype=float)


def macd(close, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    valid = line.dropna()
    sig = pd.Series(np.nan, index=close.index, dtype=float)
    if len(valid) >= signal:
        sig.loc[valid.index] = ema(valid, signal)
    return {'macd': line, 'signal': sig, 'histogram': line - sig}


def bollinger(close, n=20, k=2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    return {'middle': mid, 'upper': upper, 'lower': lower, 'pct_b': (close - lower) / (upper - lower),
            'bandwidth': (upper - lower) / mid}


def true_range(high, low, close):
    prev = close.shift(1)
    return pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1, skipna=False)


def atr(high, low, close, n=14):
    tr = true_range(high, low, close).to_numpy(dtype=float)[1:]
    return pd.Series([np.nan] + _wilder(tr, n), index=close.index, dtype=float)


def adx(high, low, close, n=14):
    """{'adx', 'plus_di', 'minus_di'} (Wilder)."""
    up, down = high.diff(), -low.diff()
    plus = np.where((up > down) & (up > 0), up, 0.0)[1:]
    minus = np.where((down > up) & (down > 0), down, 0.0)[1:]
    tr = true_range(high, low, close).to_numpy(dtype=float)[1:]
    if len(tr) < 2 * n:
        nan = pd.Series(np.nan, index=close.index, dtype=float)
        return {'adx': nan, 'plus_di': nan, 'minus_di': nan}

    def wilder_sum(v):
        out = [np.nan] * len(v)
        current = float(np.sum(v[:n]))
        out[n - 1] = current
        for i in range(n, len(v)):
            current = current - current / n + v[i]
            out[i] = current
        return np.array(out)
    s_tr, s_p, s_m = wilder_sum(tr), wilder_sum(plus), wilder_sum(minus)
    with np.errstate(divide='ignore', invalid='ignore'):
        pdi, mdi = 100 * s_p / s_tr, 100 * s_m / s_tr
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    first = n - 1
    adx_vals = [np.nan] * len(dx)
    valid = dx[first:]
    if len(valid) >= n:
        smoothed = _wilder(list(valid), n)
        adx_vals[first:] = smoothed
    pad = [np.nan]
    return {'adx': pd.Series(pad + list(adx_vals), index=close.index, dtype=float),
            'plus_di': pd.Series(pad + list(pdi), index=close.index, dtype=float),
            'minus_di': pd.Series(pad + list(mdi), index=close.index, dtype=float)}


def hist_vol(close, n=20):
    r = np.log(close / close.shift(1))
    return r.rolling(n, min_periods=n).std(ddof=1) * math.sqrt(252)


def momentum(close, n):
    return close / close.shift(n) - 1


def drawdown(close, window=252):
    peak = close.rolling(window, min_periods=1).max()
    return close / peak - 1


def relative_volume(volume, n=20):
    return volume / volume.shift(1).rolling(n, min_periods=n).mean()


def relative_strength(close, bench, n):
    """(1 + stock return) / (1 + benchmark return) - 1 over n sessions, on the common dates."""
    both = pd.concat([close, bench], axis=1, join='inner').dropna()
    if len(both) <= n:
        return None
    s, b = both.iloc[:, 0], both.iloc[:, 1]
    rs, rb = s.iloc[-1] / s.iloc[-1 - n] - 1, b.iloc[-1] / b.iloc[-1 - n] - 1
    return (1 + rs) / (1 + rb) - 1


def pivots(high, low, k=PIVOT_K, known_upto=None):
    """[(date, 'high' | 'low', price)] of swing points known at position known_upto (default: the last bar)."""
    n = len(high)
    last = n - 1 if known_upto is None else known_upto
    out = []
    hv, lv = high.to_numpy(dtype=float), low.to_numpy(dtype=float)
    for i in range(k, n - k):
        if i + k > last:
            break
        window_h, window_l = hv[i - k:i + k + 1], lv[i - k:i + k + 1]
        if np.isnan(window_h).any() or np.isnan(window_l).any():
            continue
        if hv[i] == window_h.max() and (window_h == hv[i]).sum() == 1:
            out.append((high.index[i], 'high', float(hv[i])))
        if lv[i] == window_l.min() and (window_l == lv[i]).sum() == 1:
            out.append((low.index[i], 'low', float(lv[i])))
    return out


def levels(points, tolerance):
    """Clusters of pivot prices within `tolerance` of the cluster's first price: [{'level', 'touches', 'last'}]."""
    out = []
    for when, _, price in sorted(points, key=lambda p: p[2]):
        if out and price - out[-1]['first'] <= tolerance:
            c = out[-1]
            c['prices'].append(price)
            c['last'] = max(c['last'], when)
        else:
            out.append({'first': price, 'prices': [price], 'last': when})
    return [{'level': float(np.mean(c['prices'])), 'touches': len(c['prices']), 'last': c['last']} for c in out]


def retracement(points, close):
    """{'leg', 'from': (date, price), 'to': (date, price), 'retraced_pct'} of the last completed swing, or None."""
    pts = sorted(points, key=lambda p: p[0])
    if not pts:
        return None
    last = pts[-1]
    prev = next((p for p in reversed(pts[:-1]) if p[1] != last[1]), None)
    if prev is None or last[2] == prev[2]:
        return None
    return {'leg': 'up' if last[1] == 'high' else 'down', 'from': (prev[0], prev[2]), 'to': (last[0], last[2]),
            'retraced_pct': round((last[2] - close) / (last[2] - prev[2]) * 100, 1)}


def candle(o, h, l, c, prev=None):
    """Patterns of one bar (see module docstring); prev = (open, close) of the previous bar or None."""
    found = []
    rng, body = h - l, abs(c - o)
    if rng <= 0:
        return found
    upper, lower = h - max(o, c), min(o, c) - l
    if body <= 0.1 * rng:
        found.append('doji')
    if prev is not None:
        po, pc = prev
        if pc < po and c > o and o <= pc and c >= po and body > abs(pc - po):
            found.append('bullish engulfing')
        if pc > po and c < o and o >= pc and c <= po and body > abs(pc - po):
            found.append('bearish engulfing')
    if body > 0 and lower >= 2 * body and upper <= body:
        found.append('hammer')
    if body > 0 and upper >= 2 * body and lower <= body:
        found.append('shooting star')
    return found


def _last(x):
    if x is None or not len(x):
        return None
    v = x.iloc[-1]
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def analyze(frame, bench=None):
    """
    Indicators and price action on the last bar of `frame` (columns close, open, high, low, volume; index = dates,
    oldest first). bench: benchmark closes (Series) for relative strength. Returns {'values', 'price_action',
    'missing'} where missing lists the values that could not be computed (insufficient history or no OHLC).
    """
    close = frame['close'].astype(float)
    have_ohlc = all(c in frame for c in ('open', 'high', 'low')) and frame[['open', 'high', 'low']].notna().all(axis=None)
    v = {}
    for n in (20, 50, 200):
        v[f'sma{n}'] = _last(sma(close, n))
        v[f'ema{n}'] = _last(ema(close, n))
    v['rsi14'] = _last(rsi(close))
    m = macd(close)
    v.update(macd=_last(m['macd']), macd_signal=_last(m['signal']), macd_hist=_last(m['histogram']))
    b = bollinger(close)
    v.update(bb_upper=_last(b['upper']), bb_lower=_last(b['lower']), bb_pct_b=_last(b['pct_b']),
             bb_bandwidth=_last(b['bandwidth']))
    v['hv20'], v['hv60'] = _last(hist_vol(close, 20)), _last(hist_vol(close, 60))
    for name, n in (('mom_1m', 21), ('mom_3m', 63), ('mom_6m', 126), ('mom_12m', 252)):
        v[name] = _last(momentum(close, n))
    v['mom_12_1'] = _last(close.shift(21) / close.shift(252) - 1)
    dd = drawdown(close)
    v['drawdown_from_52w_high'] = _last(dd)
    v['max_drawdown_1y'] = float(dd.iloc[-252:].min()) if len(dd) >= 252 else None
    v['relative_volume'] = _last(relative_volume(frame['volume'].astype(float))) if 'volume' in frame else None
    if bench is not None:
        for name, n in (('rs_1m', 21), ('rs_3m', 63), ('rs_6m', 126), ('rs_12m', 252)):
            r = relative_strength(close, bench, n)
            v[name] = None if r is None else float(r)
    s50, s200 = sma(close, 50), sma(close, 200)
    pa = {}
    if have_ohlc:
        high, low = frame['high'].astype(float), frame['low'].astype(float)
        a = atr(high, low, close)
        v['atr14'] = _last(a)
        d = adx(high, low, close)
        v.update(adx14=_last(d['adx']), plus_di=_last(d['plus_di']), minus_di=_last(d['minus_di']))
        recent = slice(max(0, len(frame) - LEVEL_LOOKBACK), len(frame))
        pts = pivots(high.iloc[recent], low.iloc[recent])
        if v['atr14'] and pts:
            ls = levels(pts, LEVEL_TOLERANCE_ATR * v['atr14'])
            c = float(close.iloc[-1])
            below = [x for x in ls if x['level'] < c]
            above = [x for x in ls if x['level'] > c]
            pa['support'] = max(below, key=lambda x: x['level']) if below else None
            pa['resistance'] = min(above, key=lambda x: x['level']) if above else None
            pa['n_pivots'] = len(pts)
        if pts:
            pa['retracement'] = retracement(pts, float(close.iloc[-1]))
        if len(frame) > BREAKOUT_N:
            hh = float(high.iloc[-1 - BREAKOUT_N:-1].max())
            ll = float(low.iloc[-1 - BREAKOUT_N:-1].min())
            c = float(close.iloc[-1])
            pa['breakout'] = 'above the 55-session high' if c > hh else 'below the 55-session low' if c < ll else None
            pa['channel_55'] = (ll, hh)
        prev = (float(frame['open'].iloc[-2]), float(close.iloc[-2])) if len(frame) > 1 else None
        pa['candles'] = candle(float(frame['open'].iloc[-1]), float(high.iloc[-1]), float(low.iloc[-1]),
                               float(close.iloc[-1]), prev)
    if len(close) >= 252:
        hi, lo = float(close.iloc[-252:].max()), float(close.iloc[-252:].min())
        c = float(close.iloc[-1])
        pa['high_52w'], pa['low_52w'] = hi, lo
        pa['from_52w_high'], pa['from_52w_low'] = c / hi - 1, c / lo - 1
    hv = hist_vol(close, 20).dropna().iloc[-REGIME_LOOKBACK:]
    if len(hv) >= 252:
        cur = float(hv.iloc[-1])
        pct = float((hv < cur).mean() * 100 + (hv == cur).mean() * 50)
        pa['volatility_regime'] = {'hv20': cur, 'percentile': round(pct, 1), 'n': len(hv),
                                   'regime': 'low' if pct < 20 else 'high' if pct > 80 else 'normal'}
    if v['sma50'] is not None and v['sma200'] is not None and len(s200.dropna()) > 20:
        c = float(close.iloc[-1])
        rising = float(s200.iloc[-1]) > float(s200.iloc[-21])
        state = 'up' if c > v['sma50'] > v['sma200'] and rising else \
            'down' if c < v['sma50'] < v['sma200'] and not rising else 'mixed'
        strength = None if v.get('adx14') is None else 'strong' if v['adx14'] >= 25 else \
            'weak' if v['adx14'] < 20 else 'moderate'
        above = (close.iloc[-60:] > s50.iloc[-60:]).mean() if len(close) >= 60 else None
        pa['trend'] = {'state': state, 'sma200_rising': rising, 'strength_by_adx': strength,
                       'persistence_above_sma50_60d': None if above is None else round(float(above) * 100, 1)}
    missing = sorted(k for k, x in v.items() if x is None) + ([] if have_ohlc else ['ATR / ADX / pivots / candles '
                                                                                   '(no open / high / low)'])
    return {'values': v, 'price_action': pa, 'missing': missing, 'not_implemented': NOT_IMPLEMENTED_METHODS}
