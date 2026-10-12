#!/usr/bin/env python3
"""
Weekly report section 'technicals' - Q1 "What happened this week?" (master mission P2: technical analysis and
price action)

Per company of ctx.universe: src/technicals.analyze on the adjusted daily bars up to s_0 (yfinance, rank 2) and,
for comparison, on the bars up to s_-5; the benchmark (config weekly.benchmark) for relative strength. Formulas,
periods and the treatment of missing bars are in src/technicals.py (reference implementations, not the indicators
of the frozen heuristic signal).

Kinds: values computed from one rank-2 price source are market_fact (UNCERTAIN, SINGLE_RANK2_SOURCE); trend,
regime, levels and candle names are rule-based descriptions -> interpretation (UNCERTAIN). Indicators describe
market conditions: no statement says a price will rise or fall, and support / resistance levels are estimates
from an explicit method, never prices that will hold. Sections never call the wall clock and never write files.
"""

from ...database import source_rank
from ...market_data import session_close_utc
from ...technicals import NOT_IMPLEMENTED_METHODS, analyze
from ..core import SectionResult, conclude, evidence, unavailable
from .market import WEEK, fresh_flag

NAME = 'technicals'
QUESTIONS = [1]
YF = 'yfinance'
ROWS = (('sma20', 'SMA 20'), ('sma50', 'SMA 50'), ('sma200', 'SMA 200'), ('ema20', 'EMA 20'), ('ema50', 'EMA 50'),
        ('ema200', 'EMA 200'), ('rsi14', 'RSI 14 (Wilder)'), ('macd', 'MACD 12/26'), ('macd_signal', 'MACD signal 9'),
        ('macd_hist', 'MACD histogram'), ('bb_pct_b', 'Bollinger %B (20, 2)'), ('bb_bandwidth', 'Bollinger bandwidth'),
        ('atr14', 'ATR 14 (Wilder)'), ('adx14', 'ADX 14'), ('plus_di', '+DI 14'), ('minus_di', '-DI 14'),
        ('hv20', 'historical volatility 20d (annualised)'), ('hv60', 'historical volatility 60d (annualised)'),
        ('mom_1m', 'momentum 1 month (21 sessions)'), ('mom_3m', 'momentum 3 months (63)'),
        ('mom_6m', 'momentum 6 months (126)'), ('mom_12m', 'momentum 12 months (252)'),
        ('mom_12_1', 'momentum 12-1 (252 to 21 sessions ago)'), ('drawdown_from_52w_high', 'drawdown from the 52-week high'),
        ('max_drawdown_1y', 'maximum drawdown, last 252 sessions'), ('relative_volume', 'relative volume (vs 20 sessions)'),
        ('rs_1m', 'relative strength vs benchmark, 1 month'), ('rs_3m', 'relative strength, 3 months'),
        ('rs_6m', 'relative strength, 6 months'), ('rs_12m', 'relative strength, 12 months'))
PCT_KEYS = {'hv20', 'hv60', 'mom_1m', 'mom_3m', 'mom_6m', 'mom_12m', 'mom_12_1', 'drawdown_from_52w_high',
            'max_drawdown_1y', 'rs_1m', 'rs_3m', 'rs_6m', 'rs_12m'}


def _frame(ctx, ticker):
    p = ctx.prices(ticker)
    f = p.get('frame')
    if p.get('status') != 'OK' or f is None or not len(f):
        return None, p
    f = f.copy()
    f.index = [d.date().isoformat() if hasattr(d, 'date') else str(d)[:10] for d in f.index]
    return f, p


def _shown(key, v):
    if v is None:
        return None
    return round(v * 100, 2) if key in PCT_KEYS else round(v, 4) if abs(v) < 10 else round(v, 2)


def _day(d):
    return d.date().isoformat() if hasattr(d, 'date') else str(d)[:10]


def build(ctx, tickers=None):
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    benchmark = (getattr(ctx, 'weekly', None) or {}).get('benchmark', 'SPY')
    bench_frame, _ = _frame(ctx, benchmark)
    bench = bench_frame['close'].astype(float) if bench_frame is not None else None
    for t in list(tickers or ctx.universe):
        f, p = _frame(ctx, t)
        if f is None:
            res.add(unavailable(t, 1, 'technical analysis', f"prices unavailable: {p.get('reason')}"))
            continue
        day = f.index[-1]
        prev_day = tm.previous_week[-1]
        now = analyze(f, bench)
        before_frame = f[[d <= prev_day for d in f.index]]
        before = analyze(before_frame, bench[[d <= prev_day for d in bench.index]] if bench is not None else None) \
            if len(before_frame) else {'values': {}, 'price_action': {}}
        rows = [[label, _shown(k, before['values'].get(k)), _shown(k, now['values'].get(k))] for k, label in ROWS]
        fetch = p.get('fetch') or {}
        item = evidence(tm, YF, source_rank(YF), f'{t}: adjusted daily bars up to {day}', as_of=day,
                        published_at=session_close_utc(day), retrieved_at=fetch.get('retrieved_at'),
                        fetch_id=fetch.get('fetch_id'), fresh=fresh_flag(ctx, day, 'daily_market'),
                        basis='session close 21:00 UTC (estimate)')
        v, pa = now['values'], now['price_action']
        parts = []
        if v.get('rsi14') is not None:
            parts.append(f"RSI14 {v['rsi14']:.1f} (a week earlier {before['values'].get('rsi14') or float('nan'):.1f})")
        if v.get('mom_3m') is not None:
            parts.append(f"3-month momentum {v['mom_3m'] * 100:+.1f}%")
        if v.get('rs_3m') is not None:
            parts.append(f"3-month relative strength vs {benchmark} {v['rs_3m'] * 100:+.1f}%")
        etf = ((getattr(ctx, 'weekly', None) or {}).get('sector_etf') or {}).get(t)
        etf_frame = _frame(ctx, etf)[0] if etf else None
        if etf_frame is not None:
            from ...technicals import relative_strength
            rs_sector = relative_strength(f['close'].astype(float), etf_frame['close'].astype(float), 63)
            if rs_sector is not None:
                parts.append(f'3-month relative strength vs its sector ETF {etf} {rs_sector * 100:+.1f}%')
                rows.append([f'relative strength vs sector ETF {etf}, 3 months', None, round(rs_sector * 100, 2)])
        if v.get('hv20') is not None:
            parts.append(f"20-day volatility {v['hv20'] * 100:.1f}% annualised")
        if v.get('drawdown_from_52w_high') is not None:
            parts.append(f"{v['drawdown_from_52w_high'] * 100:+.1f}% from the 52-week high")
        res.table(f'{t}: technical indicators (adjusted daily bars, yfinance)',
                  ['indicator', f'at the close of {prev_day}', f'at the close of {day}'], rows, scope=t, question=1,
                  note='Percent values for volatility, momentum, drawdown and relative strength. Formulas, periods and '
                       'warm-up rules: src/technicals.py. A blank value needs more history than available. Indicators '
                       'describe conditions; they are not forecasts. Not available: ' + ', '.join(now['missing'] or ['none']))
        if parts:
            res.add(conclude(t, 1, f'{t}: at the close of {day}: ' + '; '.join(parts) + '. Calculated from one price '
                                   'source; a description of conditions, not a forecast.', [item], 'market_fact'))
        desc = []
        trend = pa.get('trend')
        if trend:
            desc.append(f"trend rule: {trend['state']} (close vs SMA50 / SMA200, SMA200 "
                        f"{'rising' if trend['sma200_rising'] else 'not rising'}; ADX reading "
                        f"{trend['strength_by_adx'] or 'n/a'}; {trend['persistence_above_sma50_60d']}% of the last 60 "
                        'sessions above SMA50)')
        reg = pa.get('volatility_regime')
        if reg:
            desc.append(f"volatility regime {reg['regime']} (HV20 at the {reg['percentile']:.0f}th percentile of "
                        f"{reg['n']} sessions)")
        if pa.get('support') or pa.get('resistance'):
            s_, r_ = pa.get('support'), pa.get('resistance')
            desc.append('estimated levels from swing pivots: '
                        + (f"support {s_['level']:.2f} ({s_['touches']} pivot(s))" if s_ else 'no support below')
                        + ', ' + (f"resistance {r_['level']:.2f} ({r_['touches']} pivot(s))" if r_ else
                                  'no resistance above'))
        if pa.get('breakout'):
            desc.append(f"close {pa['breakout']}")
        rt = pa.get('retracement')
        if rt:
            desc.append(f"{rt['retraced_pct']:.0f}% of the last {rt['leg']} swing retraced ({_day(rt['from'][0])} "
                        f"{rt['from'][1]:.2f} -> {_day(rt['to'][0])} {rt['to'][1]:.2f}; confirmed pivots, k = 5)")
        if pa.get('candles'):
            desc.append('last bar: ' + ', '.join(pa['candles']))
        if desc:
            res.add(conclude(t, 1, f'{t}: rule-based price-action description at the close of {day}: '
                                   + '; '.join(desc) + '. Objective rules (src/technicals.py); estimates, not forecasts '
                                   'or levels that will hold.', [item], 'interpretation'))
    for method, reason in NOT_IMPLEMENTED_METHODS.items():
        res.add(unavailable('overall', 1, method, reason))
    res.notes.append('Technical indicators are computed with reference implementations (src/technicals.py) on adjusted '
                     'bars from one secondary source (yfinance). They are not the inputs of the heuristic signal and '
                     f'no indicator is presented as a validated prediction. Comparison bar: s_-{WEEK}.')
    return res
