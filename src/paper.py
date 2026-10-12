#!/usr/bin/env python3
"""
Paper trading simulator (master mission P4) - strategy PT1 (docs/research/PAPER_STRATEGY_PT1.md). PAPER ONLY:
there is no broker connection and no code path that sends an order anywhere; the simulator writes to its journals.

`python main.py paper [rebalance|update|status]` (default: rebalance then update), run by scripts/daily_run.py.

State is never stored separately: cash, positions and pending orders are rebuilt by replaying the append-only
transaction journal (src/journal.py), so every number can be traced to journal entries.

rebalance  uses the latest stage 3 record that is valid (ledger-verified, s0's week over) and not used yet, while
           the open of the following Monday (13:30 UTC, the earliest possible open of s1) has not passed. Writes one
           'rebalance' entry, market-on-open 'order' entries (sells for held names that left the top N, buys for new
           names) and, in the predictions journal, one 'prediction' per scored ticker.
update     for each session after the last processed one (sessions = SPY bars whose close is before now):
           1. fills the pending orders whose execution session is this one (the first session whose 09:30 New York
              open is after the order time): sells first, then buys in rank order; buy price = as-traded open x
              (1 + slippage + half-spread), sized by the risk engine at that price with stop = fill - 2 x ATR14(s0);
              sell price = open x (1 - slippage - half-spread); commission on both;
           2. corporate actions with an ex-date on this session (yfinance actions, rank 2): splits multiply shares
              and divide stop and cost basis; cash dividends are credited for the shares held at the previous close;
           3. stops: a held position whose session low <= stop is sold at min(open, stop) x (1 - slippage -
              half-spread) (a gap through the stop fills at the open, below the stop);
           4. a 'mark' at the as-traded close: equity, cash, exposure, drawdown, and both benchmarks.
As-traded prices: Yahoo's unadjusted bars are split-adjusted retroactively; a price of session s is multiplied
back by the ratios of the splits dated after s (and volumes divided), so fills, stops, marks and positions always
use the prices that traded then. Benchmarks: SPY and the equal-weight universe from adjusted bars (total return),
both started at the open of the first fill session, the equal-weight one rebalanced at each fill session's open.
"""

import json
import math
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from . import risk as risk_engine
from .common import DATA_UNAVAILABLE, load_config, redact, to_utc_iso, utc_now_iso
from .database import Database
from .journal import Journal, entry_id
from .market_data import PriceFeed
from .technicals import atr

STRATEGY = 'PT1'
NEW_YORK = ZoneInfo('America/New_York')
PAPER_DEFAULTS = {'strategy': STRATEGY, 'initial_capital': 100000, 'top_n': 8, 'min_scored': 10,
                  'preregistration': 'docs/research/PAPER_STRATEGY_PT1.md'}
LOOKBACK_DAYS = 400


def session_open_utc(day):
    return to_utc_iso(datetime.combine(date.fromisoformat(day), time(9, 30), tzinfo=NEW_YORK))


def as_traded(frame, splits):
    """Frame (index iso dates) with open/high/low/close_raw and volume converted to the prices that traded then."""
    f = frame.copy()
    factor = pd.Series(1.0, index=f.index)
    for d, ratio in splits.items():
        factor[[x < d for x in f.index]] *= ratio
    for col in ('open_raw', 'high_raw', 'low_raw', 'close_raw'):
        if col in f:
            f[col] = f[col] * factor
    if 'volume' in f:
        f['volume'] = f['volume'] / factor
    return f


class Paper:
    def __init__(self, db=None, price_feed=None, base=None, config=None, actions=None):
        self.db = db or Database()
        self.prices = price_feed or PriceFeed(db=self.db, lookback_days=LOOKBACK_DAYS)
        self.cfg = config if config is not None else load_config()
        self.risk, self.risk_defaulted = risk_engine.settings(self.cfg)
        self.p = {**PAPER_DEFAULTS, **(self.cfg.get('paper') or {})}
        self.base = base
        self.tx, self.pred = Journal('transactions', base), Journal('predictions', base)
        self._actions = actions            # tests inject {ticker: {'splits': {}, 'dividends': {}}}
        self._frames, self._action_cache = {}, {}

    # ------------------------------------------------------------------ data

    def actions(self, ticker):
        """{'splits': {iso: ratio}, 'dividends': {iso: cash per share}} from yfinance (logged), cached per run."""
        if self._actions is not None:
            return self._actions.get(ticker, {'splits': {}, 'dividends': {}})
        if ticker not in self._action_cache:
            try:
                import yfinance as yf
                tk = yf.Ticker(ticker)
                out = {'splits': {d.date().isoformat(): float(r) for d, r in tk.splits.items()},
                       'dividends': {d.date().isoformat(): float(v) for d, v in tk.dividends.items()}}
                self.db.record_fetch('yfinance', f'yfinance.Ticker({ticker}).actions', status='OK',
                                     raw=json.dumps(out, sort_keys=True), raw_ext='json')
            except Exception as e:  # noqa: BLE001 - a missing action list is reported, never assumed empty
                self.db.record_fetch('yfinance', f'yfinance.Ticker({ticker}).actions', status=DATA_UNAVAILABLE,
                                     error=redact(f'{type(e).__name__}: {e}'))
                out = None
            self._action_cache[ticker] = out
        return self._action_cache[ticker]

    def frame(self, ticker):
        """As-traded daily bars (index iso dates) or None."""
        if ticker not in self._frames:
            p = self.prices.get(ticker)
            f = p.get('frame')
            if p['status'] != 'OK' or f is None or 'open_raw' not in f:
                self._frames[ticker] = None
            else:
                f = f.copy()
                f.index = [d.date().isoformat() if hasattr(d, 'date') else str(d)[:10] for d in f.index]
                acts = self.actions(ticker)
                self._frames[ticker] = as_traded(f, (acts or {}).get('splits', {}))
        return self._frames[ticker]

    # ------------------------------------------------------------------ state

    def state(self):
        st = {'cash': None, 'positions': {}, 'pending': {}, 'used_records': set(), 'last_session': None,
              'marks': [], 'start_session': None, 'bench': None, 'costs': 0.0, 'traded': 0.0, 'stops': 0}
        for e in self.tx.entries():
            t = e['type']
            if t == 'start':
                st['cash'] = e['capital']
            elif t == 'rebalance':
                st['used_records'].add(e['s0'])
            elif t == 'order':
                st['pending'][e['id']] = e
            elif t in ('order_rejected', 'order_cancelled'):
                st['pending'].pop(e['order_id'], None)
            elif t == 'fill':
                st['pending'].pop(e['order_id'], None)
                st['costs'] += e['costs']
                st['traded'] += e['notional']
                if e['side'] == 'buy':
                    st['cash'] -= e['cash_out']
                    st['positions'][e['ticker']] = {'shares': e['shares'], 'stop': e['stop'],
                                                    'cost': e['cash_out'] / e['shares'],
                                                    'entry_session': e['session'], 'sector': e.get('sector')}
                else:
                    st['cash'] += e['cash_in']
                    st['positions'].pop(e['ticker'], None)
            elif t == 'stop_exit':
                st['cash'] += e['cash_in']
                st['costs'] += e['costs']
                st['traded'] += e['notional']
                st['stops'] += 1
                st['positions'].pop(e['ticker'], None)
            elif t == 'dividend':
                st['cash'] += e['amount']
            elif t == 'split':
                pos = st['positions'].get(e['ticker'])
                if pos:
                    pos.update(shares=e['shares_after'], stop=e['stop_after'], cost=e['cost_after'])
            elif t == 'mark':
                st['marks'].append(e)
                st['last_session'] = e['session']
                st['start_session'] = st['start_session'] or e['session']
                st['bench'] = e.get('bench_state')
        return st

    def _check(self):
        for j in (self.tx, self.pred):
            v = j.verify()
            if not v['ok']:
                raise RuntimeError(f'{j.path.name}: {v["problem"]}')

    # ------------------------------------------------------------------ rebalance

    def rebalance(self, now=None, base=None):
        """Use the latest valid, unused stage 3 record (module docstring). Returns a message dict."""
        from .prospective import load_records, verify_ledger, week_bounds
        now = to_utc_iso(now) or utc_now_iso()
        self._check()
        st = self.state()
        if st['cash'] is None:
            self.tx.append([{'type': 'start', 'strategy': STRATEGY, 'capital': float(self.p['initial_capital']),
                             'created_at': now, 'preregistration': self.p['preregistration'],
                             'risk_settings': self.risk, 'risk_defaulted': self.risk_defaulted,
                             'paper_settings': self.p, 'note': 'paper only: no broker, no real order'}])
            st = self.state()
        ledger = verify_ledger(base)
        records = load_records(base)
        valid = sorted(s0 for s0, (rec, sha) in records.items()
                       if rec and s0 in ledger['verified'] and ledger['verified'][s0]['record_sha256'] == sha)
        if not valid:
            return {'status': 'NO RECORD', 'message': 'no valid stage 3 record'}
        s0 = valid[-1]
        if s0 in st['used_records']:
            return {'status': 'UP TO DATE', 'message': f'record {s0} already used'}
        deadline = week_bounds(s0)[1]
        if now >= deadline:
            return {'status': 'TOO LATE', 'message': f'record {s0}: its entry session may have opened ({deadline}); '
                                                     'no order (the strategy waits for the next record)'}
        record, sha = records[s0]
        from .market_data import session_close_utc
        signal_instant = record.get('signal_instant') or session_close_utc(s0)
        scored = sorted(((t, x['combined']) for t, x in record['tickers'].items() if x.get('combined') is not None),
                        key=lambda kv: (-kv[1], kv[0]))
        entries = []
        if len(scored) < self.p['min_scored']:
            entries.append({'type': 'rebalance', 'strategy': STRATEGY, 's0': s0, 'record_sha256': sha,
                            'created_at': now, 'targets': [], 'note': f'only {len(scored)} scored tickers: no change'})
            self.tx.append(entries)
            return {'status': 'NO CHANGE', 'message': entries[0]['note']}
        top = [t for t, _ in scored[:self.p['top_n']]]
        rank = {t: i for i, (t, _) in enumerate(scored, 1)}
        held = set(st['positions']) | {o['ticker'] for o in st['pending'].values() if o['side'] == 'buy'}
        sells = sorted(t for t in st['positions'] if t not in top)
        buys = [t for t in top if t not in held]
        entries.append({'type': 'rebalance', 'strategy': STRATEGY, 's0': s0, 'record_sha256': sha, 'created_at': now,
                        'targets': top, 'sells': sells, 'buys': buys, 'holds': sorted(set(top) & set(st['positions']))})
        for t in sells:
            entries.append({'type': 'order', 'id': entry_id(STRATEGY, s0, t, 'sell'), 'strategy': STRATEGY,
                            'side': 'sell', 'ticker': t, 'created_at': now, 's0': s0,
                            'signal_instant': signal_instant,
                            'rule': 'market-on-open, first session whose open is after created_at',
                            'rationale': f'no longer in the top {self.p["top_n"]} of the record of {s0} '
                                         f'(rank {rank.get(t, "unscored")})'})
        for t in buys:
            f = self.frame(t)
            atr14 = None
            if f is not None:
                bars = f[[d <= s0 for d in f.index]]
                if len(bars) > 15:
                    atr14 = float(atr(bars['high_raw'], bars['low_raw'], bars['close_raw']).iloc[-1])
                adv = float(bars['volume'].iloc[-20:].mean()) if len(bars) >= 20 else None
            else:
                adv = None
            entries.append({'type': 'order', 'id': entry_id(STRATEGY, s0, t, 'buy'), 'strategy': STRATEGY,
                            'side': 'buy', 'ticker': t, 'created_at': now, 's0': s0,
                            'signal_instant': signal_instant, 'signal': {'combined': dict(scored)[t],
                                                                                   'rank': rank[t]},
                            'atr14_s0': atr14, 'adv20_shares_s0': adv,
                            'rule': 'market-on-open, first session whose open is after created_at',
                            'stop_rule': f"fill - {self.risk['stop_atr_multiple']} x ATR14 at s0 (as-traded bars)",
                            'sizing': 'risk engine at the fill price', 'exit_rule': 'stop, or out of the top N of a '
                            'later record (sold at its s1 open)',
                            'rationale': f'rank {rank[t]} of {len(scored)} in the stage 3 record of {s0}'})
        self.tx.append(entries)
        self._predictions(record, sha, scored)
        return {'status': 'ORDERS', 'message': f'record {s0}: {len(buys)} buy and {len(sells)} sell order(s), '
                                               f"targets {', '.join(top)}"}

    def _predictions(self, record, sha, scored):
        known = self.pred.ids()
        rank = {t: i for i, (t, _) in enumerate(scored, 1)}
        out = []
        for t, x in sorted(record['tickers'].items()):
            if x.get('combined') is None:
                continue
            pid = entry_id('prediction', record['s0'], t)
            if pid in known:
                continue
            out.append({'type': 'prediction', 'id': pid, 'ticker': t, 'timestamp': record['generated_at'],
                        'signal_instant': record.get('signal_instant') or f"{record['s0']}T21:00:00+00:00", 'horizons_sessions': [20, 5],
                        'data_and_sources': {'record': f"reports/prospective/records/record_{record['s0']}.json",
                                             'record_sha256': sha, 'price_fetch_id': x.get('price_fetch_id'),
                                             'company_facts_fetch_id': x.get('company_facts_fetch_id')},
                        'signals_available': {k: x.get(k) for k in ('technical', 'fundamentals', 'insider')},
                        'model_output': {'combined': x['combined'], 'label': x.get('signal'), 'rank': rank[t],
                                         'of': len(scored)},
                        'model_version': {'protocol': record.get('protocol'), 'code_version': record.get('code_version')},
                        'assumptions': 'heuristic weights 0.25 / 0.40 / 0.15 (renormalised) and thresholds 65 / 40 '
                                       'were never fitted or validated',
                        'uncertainties': 'no predictive edge demonstrated (walk-forward NOT DEMONSTRATED; descriptive '
                                         'evaluation: AUC about 0.51); single-source prices; SEC timing calibrated',
                        'expected_outcome': 'no directional claim and no probability: stage 3 hypothesis that higher '
                                            'scores rank higher returns across the universe (P1 20 sessions, P2 5)'})
        if out:
            self.pred.append(out)

    # ------------------------------------------------------------------ update

    def update(self, now=None):
        now = to_utc_iso(now) or utc_now_iso()
        self._check()
        st = self.state()
        if st['cash'] is None:
            return {'status': 'NOT STARTED', 'message': 'no start entry (run rebalance first)'}
        spy = self.prices.get('SPY')
        if spy['status'] != 'OK':
            return {'status': DATA_UNAVAILABLE, 'message': f"SPY calendar unavailable: {spy['reason']}"}
        sessions = [d.date().isoformat() for d in spy['close'].index]
        first_order = min((o['created_at'] for o in st['pending'].values()), default=None)
        start = st['last_session']
        todo = [s for s in sessions if (start is None or s > start)
                and (start is not None or (first_order and session_open_utc(s) > first_order))]
        done = []
        for s in todo:
            entries = self._session(s, st, now)
            if entries is None:
                break                                   # a bar is missing: stop here, retry later
            self.tx.append(entries)
            st = self.state()
            done.append(s)
        n_out = self.record_outcomes(now)
        return {'status': 'OK', 'message': f"{len(done)} session(s) processed" + (f' ({done[0]} to {done[-1]})'
                                                                                   if done else '')
                + f'; {n_out} prediction outcome(s) recorded'}

    def record_outcomes(self, now=None, base=None):
        """
        Append an 'outcome' entry for each prediction whose realised forward return is now known in the latest
        stage 3 evaluation (reports/prospective/evaluation.json); predictions themselves are never modified.
        """
        from .prospective import _root
        path = _root(base) / 'evaluation.json'
        if not path.exists():
            return 0
        ev = json.loads(path.read_text(encoding='utf-8'))
        known = self.pred.ids()
        preds = {e['id']: e for e in self.pred.entries() if e['type'] == 'prediction'}
        out = []
        for row in ev.get('samples') or []:
            pid = entry_id('prediction', row['date'], row['ticker'])
            if pid not in preds:
                continue
            for h in (20, 5):
                value = row.get(f'fwd_{h}d')
                oid = entry_id('outcome', pid, h)
                if value is None or oid in known:
                    continue
                out.append({'type': 'outcome', 'id': oid, 'prediction_id': pid, 'ticker': row['ticker'],
                            'horizon_sessions': h, 'realised_return': value, 's0': row['date'],
                            'evaluation_computed_at': ev.get('computed_at'), 'recorded_at': to_utc_iso(now) or utc_now_iso(),
                            'note': 'return from the close of s1 to the close H sessions later (stage 3 rule)'})
        if out:
            self.pred.append(out)
        return len(out)

    def _bar(self, ticker, s):
        f = self.frame(ticker)
        if f is None or s not in f.index:
            return None
        row = f.loc[s]
        vals = {k: float(row[k]) for k in ('open_raw', 'high_raw', 'low_raw', 'close_raw', 'open', 'close')
                if k in row and row[k] == row[k]}
        return vals if {'open_raw', 'low_raw', 'close_raw'} <= set(vals) else None

    def _session(self, s, st, now):
        """Journal entries of session s, or None when a needed bar is missing (processing stops)."""
        r = self.risk
        side_cost = (r['slippage_bps'] + r['half_spread_bps']) / 1e4
        out, cash = [], st['cash']
        positions = {t: dict(p) for t, p in st['positions'].items()}
        equity_before = st['marks'][-1]['equity'] if st['marks'] else cash
        due = [o for o in st['pending'].values() if session_open_utc(s) > o['created_at']]
        needed = set(positions) | {o['ticker'] for o in due}
        bars = {t: self._bar(t, s) for t in needed}
        missing = [t for t, b in bars.items() if b is None]
        if missing:
            if any(t in positions for t in missing):
                return None
            for o in due:                                # an order without a bar on its session is cancelled
                if o['ticker'] in missing:
                    out.append({'type': 'order_cancelled', 'order_id': o['id'], 'ticker': o['ticker'], 'session': s,
                                'reason': f'no bar for {o["ticker"]} on {s}'})
            due = [o for o in due if o['ticker'] not in missing]
        # 0. corporate actions with ex-date s, on the holdings of the previous close (before the open): a split
        #    changes shares / stop / cost; a cash dividend goes to the holder at the previous close
        for t in list(positions):
            acts = self.actions(t)
            if acts is None:
                out.append({'type': 'data_problem', 'ticker': t, 'session': s,
                            'problem': 'corporate actions unavailable (yfinance): splits / dividends not processed'})
                continue
            ratio = acts['splits'].get(s)
            if ratio and ratio != 1:
                q = positions[t]
                after = {'shares_after': q['shares'] * ratio, 'stop_after': q['stop'] / ratio,
                         'cost_after': q['cost'] / ratio}
                out.append({'type': 'split', 'ticker': t, 'session': s, 'ratio': ratio, 'shares_before': q['shares'],
                            **after})
                q.update(shares=after['shares_after'], stop=after['stop_after'], cost=after['cost_after'])
            div = acts['dividends'].get(s)
            if div:
                amount = div * positions[t]['shares']
                out.append({'type': 'dividend', 'ticker': t, 'session': s, 'per_share': div,
                            'shares': positions[t]['shares'], 'amount': round(amount, 2)})
                cash += amount
        # 1. fills: sells first, then buys in rank order
        for o in sorted(due, key=lambda o: (o['side'] != 'sell', (o.get('signal') or {}).get('rank', 0))):
            b, t = bars[o['ticker']], o['ticker']
            if o['side'] == 'sell':
                pos = positions.get(t)
                if not pos:
                    out.append({'type': 'order_cancelled', 'order_id': o['id'], 'ticker': t, 'session': s,
                                'reason': 'no position to sell (stopped out before)'})
                    continue
                price = b['open_raw'] * (1 - side_cost)
                notional = price * pos['shares']
                commission = notional * r['commission_bps'] / 1e4
                proceeds = notional - commission
                out.append({'type': 'fill', 'order_id': o['id'], 'side': 'sell', 'ticker': t, 'session': s,
                            'open': b['open_raw'], 'price': round(price, 6), 'shares': pos['shares'],
                            'notional': round(notional, 2), 'commission': round(commission, 2),
                            'slippage_and_spread': round(b['open_raw'] * side_cost * pos['shares'], 2),
                            'costs': round(commission + b['open_raw'] * side_cost * pos['shares'], 2),
                            'cash_in': round(proceeds, 2),
                            'realised_pnl': round(proceeds - pos['cost'] * pos['shares'], 2),
                            'signal_timestamp': o['signal_instant'], 'rationale': o['rationale']})
                cash += proceeds
                positions.pop(t)
                continue
            price = b['open_raw'] * (1 + side_cost)
            if o.get('atr14_s0') is None:
                out.append({'type': 'order_rejected', 'order_id': o['id'], 'ticker': t, 'session': s,
                            'reasons': ['ATR14 at s0 unavailable: no stop can be set']})
                continue
            stop = price - r['stop_atr_multiple'] * o['atr14_s0']
            equity = cash + sum(p['shares'] * bars[x]['open_raw'] for x, p in positions.items())
            sized = risk_engine.size_position(equity, cash, price, stop, o.get('adv20_shares_s0'), r)
            sector = self._sector(t)
            if sized['accepted']:
                notional_by = {x: p['shares'] * bars[x]['open_raw'] for x, p in positions.items()}
                sectors = {x: p.get('sector') for x, p in positions.items()}
                room = r['max_sector_pct'] / 100 * equity - sum(v for x, v in notional_by.items()
                                                                if sectors.get(x) == sector)
                cap = math.floor(max(room, 0) / price)
                if cap < sized['shares']:
                    sized['binding'].append('max_sector_pct')
                    sized['shares'] = cap
                    if cap <= 0:
                        sized['accepted'] = False
                        sized['reasons'].append(f'sector {sector} already at {r["max_sector_pct"]}% of equity')
            if not sized['accepted']:
                out.append({'type': 'order_rejected', 'order_id': o['id'], 'ticker': t, 'session': s,
                            'reasons': sized['reasons']})
                continue
            shares = sized['shares']
            notional = price * shares
            commission = notional * r['commission_bps'] / 1e4
            per_share_loss = price - stop + 2 * risk_engine.cost_per_share(price, r)
            out.append({'type': 'fill', 'order_id': o['id'], 'side': 'buy', 'ticker': t, 'session': s,
                        'open': b['open_raw'], 'price': round(price, 6), 'shares': shares, 'stop': round(stop, 6),
                        'notional': round(notional, 2), 'commission': round(commission, 2),
                        'slippage_and_spread': round(b['open_raw'] * side_cost * shares, 2),
                        'costs': round(commission + b['open_raw'] * side_cost * shares, 2),
                        'cash_out': round(notional + commission, 2), 'sector': sector,
                        'planned_loss': round(shares * per_share_loss, 2),
                        'position_risk_pct': round(shares * per_share_loss / equity * 100, 3),
                        'notional_pct': round(notional / equity * 100, 2), 'binding_limits': sized['binding'],
                        'signal_timestamp': o['signal_instant'], 'rationale': o['rationale'],
                        'exit_rule': o.get('exit_rule')})
            cash -= notional + commission
            positions[t] = {'shares': shares, 'stop': stop, 'cost': (notional + commission) / shares, 'sector': sector}
        # 3. stops
        for t in list(positions):
            p, b = positions[t], bars[t]
            if b['low_raw'] <= p['stop']:
                raw = min(b['open_raw'], p['stop'])
                price = raw * (1 - side_cost)
                notional = price * p['shares']
                commission = notional * r['commission_bps'] / 1e4
                out.append({'type': 'stop_exit', 'ticker': t, 'session': s, 'stop': round(p['stop'], 6),
                            'open': b['open_raw'], 'low': b['low_raw'], 'gap_through_stop': b['open_raw'] < p['stop'],
                            'price': round(price, 6), 'shares': p['shares'], 'notional': round(notional, 2),
                            'costs': round(commission + raw * side_cost * p['shares'], 2),
                            'cash_in': round(notional - commission, 2),
                            'realised_pnl': round(notional - commission - p['cost'] * p['shares'], 2)})
                cash += notional - commission
                positions.pop(t)
        # 4. mark
        value = sum(p['shares'] * bars[t]['close_raw'] for t, p in positions.items())
        equity = cash + value
        peak = max([m['equity'] for m in st['marks']] + [equity])
        bench = self._benchmarks(s, st, out)
        out.append({'type': 'mark', 'session': s, 'created_at': now, 'cash': round(cash, 2),
                    'positions_value': round(value, 2), 'equity': round(equity, 2),
                    'gross_exposure_pct': round(value / equity * 100, 2) if equity else None,
                    'drawdown_pct': round((equity / peak - 1) * 100, 3),
                    'positions': {t: {'shares': p['shares'], 'close': bars[t]['close_raw'], 'stop': round(p['stop'], 6)}
                                  for t, p in positions.items()},
                    'bench_state': bench, 'equity_change_pct': round((equity / equity_before - 1) * 100, 4)
                    if equity_before else None})
        return out

    def _sector(self, ticker):
        """SEC SIC major group (first 2 digits) from the submissions feed (official), or 'unknown'."""
        try:
            from .sec_parser import SECParser
            feed = SECParser(db=self.db).get_filings(ticker) or {}
            sic = str(feed.get('sic') or '')
            return f'SIC {sic[:2]}' if sic[:2].isdigit() else 'unknown'
        except Exception:  # noqa: BLE001 - an unknown sector counts as its own group
            return 'unknown'

    def _benchmarks(self, s, st, entries):
        """Total-return benchmarks (adjusted bars) started at the first fill session's open."""
        from .prospective import UNIVERSE
        bench = dict(st['bench']) if st['bench'] else None
        filled = [e for e in entries if e['type'] == 'fill']
        if bench is None and not filled:
            return None

        def adj(t, col):
            b = self._bar(t, s)
            return None if b is None else b.get(col)
        if bench is None:
            spy_open = adj('SPY', 'open')
            bench = {'start_session': s, 'spy_open_start': spy_open, 'ew_value': 1.0, 'ew_base': {}, 'ew_session': s}
            bench['ew_base'] = {t: adj(t, 'open') for t in UNIVERSE if adj(t, 'open')}
        elif filled:                                         # rebalance the equal-weight benchmark at this open
            value_now = self._ew_value(bench, s, 'open')
            bench['ew_value'] = value_now if value_now is not None else bench['ew_value']
            bench['ew_base'] = {t: adj(t, 'open') for t in UNIVERSE if adj(t, 'open')}
            bench['ew_session'] = s
        spy_close = adj('SPY', 'close')
        bench['spy_return_pct'] = round((spy_close / bench['spy_open_start'] - 1) * 100, 4) \
            if spy_close and bench.get('spy_open_start') else None
        ew = self._ew_value(bench, s, 'close')
        bench['ew_return_pct'] = round((ew - 1) * 100, 4) if ew is not None else None
        return bench

    def _ew_value(self, bench, s, col):
        rel = [self._bar(t, s).get(col) / base for t, base in bench['ew_base'].items()
               if self._bar(t, s) and self._bar(t, s).get(col)]
        return bench['ew_value'] * sum(rel) / len(rel) if rel else None

    # ------------------------------------------------------------------ status

    def status(self):
        st = self.state()
        marks = st['marks']
        if not marks:
            return {'status': 'NO MARK', 'pending_orders': len(st['pending']), 'cash': st['cash']}
        eq = pd.Series([m['equity'] for m in marks], index=[m['session'] for m in marks])
        rets = eq.pct_change().dropna()
        start_equity = float(self.p['initial_capital'])
        out = {'status': 'OK', 'strategy': STRATEGY, 'first_session': marks[0]['session'],
               'last_session': marks[-1]['session'], 'sessions': len(marks), 'equity': marks[-1]['equity'],
               'total_return_pct': round((marks[-1]['equity'] / start_equity - 1) * 100, 3),
               'positions': marks[-1]['positions'], 'cash': marks[-1]['cash'], 'stops': st['stops'],
               'total_costs': round(st['costs'], 2),
               'turnover': round(st['traded'] / float(eq.mean()), 3) if len(eq) else None,
               **risk_engine.drawdown_stats(eq.tolist()),
               'benchmarks': {k: (marks[-1].get('bench_state') or {}).get(k) for k in ('spy_return_pct', 'ew_return_pct')},
               'risk_score': risk_engine.RISK_SCORE_STATUS,
               'note': 'interim, descriptive: the pre-registered evaluation needs at least 52 weekly rebalances'}
        if len(rets) >= 20:
            sd = float(rets.std(ddof=1))
            down = float((rets.clip(upper=0) ** 2).mean() ** 0.5)
            out['volatility_ann_pct'] = round(sd * math.sqrt(252) * 100, 2)
            out['sharpe'] = round(float(rets.mean()) / sd * math.sqrt(252), 3) if sd else None
            out['sortino'] = round(float(rets.mean()) / down * math.sqrt(252), 3) if down else None
        else:
            out['sharpe'] = out['sortino'] = None
            out['ratios_note'] = f'{len(rets)} daily returns: Sharpe / Sortino need at least 20'
        return out
