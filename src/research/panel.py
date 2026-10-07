#!/usr/bin/env python3
"""
Point-in-time research panel (phase P2.1)

One row per (stock, weekly evaluation date T) with the pre-registered features of
factors.py, all computed from information available at T = session close (21:00 UTC):

prices    yfinance daily bars up to and including T (adjusted close for returns and
          indicators; split-adjusted-only close x volume for dollar volume); SPY for beta.
SEC       XBRL company facts, each fact usable from its filing's acceptance time (else the
          end of its 'filed' date); restatements are later versions (PointInTimeFacts).
market    market cap = close_raw(T) x shares_s x S(s), where shares_s is the share count as of
cap       s <= T and S(s) the product of splits after s. Share count, first available of:
          dei cover-page EntityCommonStockSharesOutstanding; us-gaap CommonStockSharesOutstanding;
          weighted-average diluted shares of the latest quarter (multi-class filers report the
          cover-page count per class only, which company facts omit). Source flagged per row. close_raw is
          split-adjusted, so S(s) only converts units back to the as-reported basis: the
          value equals price x shares as observable at T (no future information in it).
outcome   return from the close of session T+1 to the close of T+1+H (adjusted closes).

Definitions (TTM = trailing twelve months, from 3/6/9/12-month facts as in sec_xbrl):
  gross_profitability = gross profit TTM / assets; operating_margin = operating income TTM /
  revenue TTM; roe = net income TTM / equity (equity > 0); roa = net income TTM / assets;
  fcf = operating cash flow TTM - capex TTM; fcf_margin = fcf / revenue; accruals =
  (net income TTM - operating cash flow TTM) / assets; eps_growth = EPS TTM / EPS TTM one year
  earlier - 1 (prior EPS > 0 only); fcf_growth = (fcf - fcf one year earlier) / revenue one
  year earlier; asset_growth = assets / assets ~1 year earlier - 1; EV = market cap + debt -
  cash (debt unavailable -> EV unavailable); EBITDA = operating income + D&A TTM.
Missing inputs give None (never 0); EPS TTM is a sum of per-period EPS (approximation).
"""

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..common import DATA_UNAVAILABLE, utc_now_iso
from ..market_data import PriceFeed, session_close_utc
from ..sec_parser import COMPANY_FACTS_MAX_AGE, SECParser
from ..sec_xbrl import (DEBT_TAGS, DURATION_MONTHS, EQUITY_TAGS, REVENUE_TAGS, balance_sheet,
                        facts_to_observations, latest_ttm)
from .factors import FEATURES, HORIZONS, INSIDER_FEATURES
from .insider_history import InsiderHistory, insider_features_at
from .universe import member_at

HISTORY_DAYS = 3700            # ~10 years of prices
MIN_HISTORY = 260              # sessions before the first evaluation date (252 + margin)
STEP = 5                       # weekly evaluation dates
ENTRY_LAG = 1
BENCHMARK = 'SPY'

DURATION_TAGS = REVENUE_TAGS + (
    'NetIncomeLoss', 'OperatingIncomeLoss', 'GrossProfit', 'CostOfRevenue',
    'CostOfGoodsAndServicesSold', 'NetCashProvidedByUsedInOperatingActivities',
    'PaymentsToAcquirePropertyPlantAndEquipment', 'DepreciationDepletionAndAmortization',
    'DepreciationAndAmortization', 'DepreciationAmortizationAndAccretionNet')
INSTANT_TAGS = EQUITY_TAGS + DEBT_TAGS + ('Assets', 'CashAndCashEquivalentsAtCarryingValue')
EPS_TAG = 'EarningsPerShareDiluted'
SHARES_TAG = 'EntityCommonStockSharesOutstanding'
BS_SHARES_TAG = 'CommonStockSharesOutstanding'
WAVG_SHARES_TAG = 'WeightedAverageNumberOfDilutedSharesOutstanding'
DA_TAGS = ('DepreciationDepletionAndAmortization', 'DepreciationAndAmortization',
           'DepreciationAmortizationAndAccretionNet')


class PointInTimeFacts:
    """Replays fact versions in availability order: state(T) = latest version known at T."""

    def __init__(self, rows):
        self.versions = sorted(rows, key=lambda r: r['published_at'])
        self.pos = 0
        self.state = {}

    def advance(self, known_at):
        while self.pos < len(self.versions) and self.versions[self.pos]['published_at'] <= known_at:
            r = self.versions[self.pos]
            self.state.setdefault(r['metric'], {})[r['as_of_date']] = r
            self.pos += 1
        return self

    def durations(self, tag):
        return {m: self.state.get(f'xbrl:{tag}:{m}M', {}) for m in DURATION_MONTHS}

    def instant(self, tag):
        return self.state.get(f'xbrl:{tag}', {})

    def ttm(self, tag):
        current, prior = latest_ttm(self.durations(tag))
        return (current['value'] if current else None, current['end'] if current else None,
                prior['value'] if prior else None)

    def latest_instant(self, tag):
        series = self.instant(tag)
        if not series:
            return None, None
        end = max(series)
        return series[end]['value'], end

    def instant_near(self, tag, target, tol_days=45):
        series = self.instant(tag)
        best = None
        for end, row in series.items():
            gap = abs((date.fromisoformat(end) - target).days)
            if gap <= tol_days and (best is None or gap < best[0]):
                best = (gap, row['value'])
        return best[1] if best else None


def _div(a, b, positive_denominator=False):
    if a is None or b is None or b == 0 or (positive_denominator and b <= 0):
        return None
    return a / b


def fundamentals_at(pit):
    """Fundamental inputs at the PIT state (dict of floats or None)."""
    revenue = None
    for tag in REVENUE_TAGS:
        value, end, prior = pit.ttm(tag)
        if value is not None and (revenue is None or end > revenue[1]):
            revenue = (value, end, prior)
    rev, rev_end, rev_prior = revenue or (None, None, None)
    ni, _, _ = pit.ttm('NetIncomeLoss')
    op, _, _ = pit.ttm('OperatingIncomeLoss')
    gp, _, _ = pit.ttm('GrossProfit')
    if gp is None and rev is not None:
        for cost_tag in ('CostOfRevenue', 'CostOfGoodsAndServicesSold'):
            cost, cost_end, _ = pit.ttm(cost_tag)
            if cost is not None and cost_end == rev_end:
                gp = rev - cost
                break
    cfo, _, cfo_prior = pit.ttm('NetCashProvidedByUsedInOperatingActivities')
    capex, _, capex_prior = pit.ttm('PaymentsToAcquirePropertyPlantAndEquipment')
    da = next((v for v in (pit.ttm(t)[0] for t in DA_TAGS) if v is not None), None)
    eps, _, eps_prior = pit.ttm(EPS_TAG)
    instants = {t: pit.instant(t) for t in EQUITY_TAGS + DEBT_TAGS}
    sheet = balance_sheet(instants)
    equity = sheet['equity']['value'] if sheet['equity'] else None
    debt = sheet['debt']['value'] if sheet['debt'] else None
    assets, assets_end = pit.latest_instant('Assets')
    assets_prior = pit.instant_near('Assets', date.fromisoformat(assets_end) - timedelta(days=365)) \
        if assets_end else None
    cash, _ = pit.latest_instant('CashAndCashEquivalentsAtCarryingValue')
    shares, shares_end, shares_source = None, None, None
    for tag in (SHARES_TAG, BS_SHARES_TAG):
        shares, shares_end = pit.latest_instant(tag)
        if shares:
            shares_source = tag
            break
    if not shares:
        quarters = pit.durations(WAVG_SHARES_TAG).get(3) or {}
        if quarters:
            shares_end = max(quarters)
            shares, shares_source = quarters[shares_end]['value'], WAVG_SHARES_TAG
    fcf = cfo - capex if cfo is not None and capex is not None else None
    fcf_prior = cfo_prior - capex_prior if cfo_prior is not None and capex_prior is not None else None
    return {'revenue': rev, 'revenue_prior': rev_prior, 'net_income': ni, 'operating_income': op,
            'gross_profit': gp, 'cfo': cfo, 'fcf': fcf, 'fcf_prior': fcf_prior, 'da': da,
            'eps': eps, 'eps_prior': eps_prior, 'equity': equity, 'debt': debt,
            'assets': assets, 'assets_prior': assets_prior, 'cash': cash,
            'shares': shares, 'shares_as_of': shares_end, 'shares_source': shares_source}


def split_factor_after(splits, day):
    """Product of split ratios with split date strictly after `day` (S(s) in the docstring)."""
    factor = 1.0
    for when, ratio in splits:
        if when > day and ratio and ratio > 0:
            factor *= ratio
    return factor


def fundamental_features(f, close_raw, splits):
    """Quality / growth / value features from fundamentals_at() and the raw close at T."""
    mcap = None                          # splits None: split history unknown -> no market cap
    if f['shares'] and close_raw and splits is not None:
        mcap = close_raw * f['shares'] * split_factor_after(splits, f['shares_as_of'])
    ev = mcap + f['debt'] - (f['cash'] or 0) if mcap is not None and f['debt'] is not None else None
    ebitda = f['operating_income'] + f['da'] if f['operating_income'] is not None and f['da'] is not None else None
    eps_growth = None
    if f['eps'] is not None and f['eps_prior'] is not None and f['eps_prior'] > 0:
        eps_growth = f['eps'] / f['eps_prior'] - 1
    fcf_growth = None
    if f['fcf'] is not None and f['fcf_prior'] is not None and f['revenue_prior']:
        fcf_growth = (f['fcf'] - f['fcf_prior']) / f['revenue_prior'] if f['revenue_prior'] > 0 else None
    return {
        'gross_profitability': _div(f['gross_profit'], f['assets'], True),
        'operating_margin': _div(f['operating_income'], f['revenue'], True),
        'roe': _div(f['net_income'], f['equity'], True),
        'roa': _div(f['net_income'], f['assets'], True),
        'fcf_margin': _div(f['fcf'], f['revenue'], True),
        'accruals': _div(None if f['net_income'] is None or f['cfo'] is None
                         else f['net_income'] - f['cfo'], f['assets'], True),
        'debt_to_equity': _div(f['debt'], f['equity'], True),
        'revenue_growth': (_div(f['revenue'], f['revenue_prior'], True) - 1)
        if _div(f['revenue'], f['revenue_prior'], True) is not None else None,
        'eps_growth': eps_growth,
        'fcf_growth': fcf_growth,
        'asset_growth': (_div(f['assets'], f['assets_prior'], True) - 1)
        if _div(f['assets'], f['assets_prior'], True) is not None else None,
        'earnings_yield': _div(f['net_income'], mcap, True),
        'sales_to_ev': _div(f['revenue'], ev, True),
        'fcf_yield': _div(f['fcf'], mcap, True),
        'ebitda_to_ev': _div(ebitda, ev, True),
        'book_to_market': _div(f['equity'], mcap, True),
        'log_market_cap': math.log10(mcap) if mcap and mcap > 0 else None,
    }


FUNDAMENTAL_FEATURES = ('gross_profitability', 'operating_margin', 'roe', 'roa', 'fcf_margin',
                        'accruals', 'debt_to_equity', 'revenue_growth', 'eps_growth', 'fcf_growth',
                        'asset_growth', 'earnings_yield', 'sales_to_ev', 'fcf_yield', 'ebitda_to_ev',
                        'book_to_market', 'log_market_cap')


def price_features(adj, raw, volume, spy, i):
    """Price / market-structure features at index i (arrays aligned on the same sessions)."""
    def ret(a, b):
        return float(adj[a] / adj[b] - 1) if adj[b] > 0 else None
    lr = np.diff(np.log(adj[i - 252:i + 1]))
    lr_spy = np.diff(np.log(spy[i - 252:i + 1]))
    vol_1y = float(lr.std(ddof=1) * math.sqrt(252))
    var_spy = float(lr_spy.var(ddof=1))
    beta = float(np.cov(lr, lr_spy, ddof=1)[0, 1] / var_spy) if var_spy > 0 else None
    resid = lr - beta * lr_spy if beta is not None else None
    dollar = raw[i - 62:i + 1] * volume[i - 62:i + 1]
    vol_recent, vol_base = volume[i - 20:i + 1].mean(), volume[i - 125:i + 1].mean()
    mom_12_1 = ret(i - 21, i - 252)
    return {
        'mom_1m': ret(i, i - 21), 'mom_3m': ret(i, i - 63), 'mom_6m': ret(i, i - 126),
        'mom_12_1': mom_12_1,
        'risk_adj_mom': mom_12_1 / vol_1y if mom_12_1 is not None and vol_1y > 0 else None,
        'vol_3m': float(lr[-63:].std(ddof=1) * math.sqrt(252)),
        'beta_1y': beta,
        'idio_vol_1y': float(resid.std(ddof=1) * math.sqrt(252)) if resid is not None else None,
        'log_dollar_volume': math.log10(dollar.mean()) if dollar.mean() > 0 else None,
        'volume_trend': math.log(vol_recent / vol_base) if vol_recent > 0 and vol_base > 0 else None,
        'dist_high_1y': float(adj[i] / adj[i - 251:i + 1].max() - 1),
    }


def add_sector_features(rows):
    """Cross-sectional sector features per date (from same-date rows only)."""
    by_date = {}
    for r in rows:
        by_date.setdefault(r['date'], []).append(r)
    for group in by_date.values():
        by_sector = {}
        for r in group:
            by_sector.setdefault(r['sector'], []).append(r)
        for members in by_sector.values():
            moms = [m['features']['mom_6m'] for m in members if m['features'].get('mom_6m') is not None]
            eys = sorted(m['features']['earnings_yield'] for m in members
                         if m['features'].get('earnings_yield') is not None)
            mean_mom = sum(moms) / len(moms) if len(moms) >= 3 else None
            median_ey = eys[len(eys) // 2] if len(eys) >= 3 else None
            for m in members:
                f = m['features']
                f['sector_mom_6m'] = mean_mom
                f['mom_6m_vs_sector'] = f['mom_6m'] - mean_mom \
                    if mean_mom is not None and f.get('mom_6m') is not None else None
                f['earnings_yield_vs_sector'] = f['earnings_yield'] - median_ey \
                    if median_ey is not None and f.get('earnings_yield') is not None else None
    return rows


class PanelBuilder:
    def __init__(self, db, history_days=HISTORY_DAYS, insider=False):
        self.db = db
        self.sec = SECParser(db=db)
        self.prices = PriceFeed(db=db, lookback_days=history_days)
        self.splits_cache = {}
        self.insider = InsiderHistory(sec=self.sec) if insider else None

    def splits(self, yahoo_ticker):
        """[(date, ratio)] from yfinance, logged as a fetch (unit conversion only)."""
        import yfinance as yf
        endpoint = f'yfinance.Ticker({yahoo_ticker}).splits'
        requested_at = utc_now_iso()
        try:
            series = yf.Ticker(yahoo_ticker).splits
            pairs = [(pd.Timestamp(d).date().isoformat(), float(v)) for d, v in series.items()]
            self.db.record_fetch('yfinance', endpoint, requested_at=requested_at, status='OK',
                                 raw=json_dumps(pairs), n_records=len(pairs))
            return pairs, None
        except Exception as e:  # noqa: BLE001 - market cap then unavailable
            self.db.record_fetch('yfinance', endpoint, requested_at=requested_at,
                                 status=DATA_UNAVAILABLE, error=f'{type(e).__name__}: {e}')
            return None, f'{type(e).__name__}: {e}'

    def sec_rows(self, cik):
        """Point-in-time fact rows for a CIK (company facts + acceptance times)."""
        facts = self.sec._get_json(f"{self.sec.SEC_API}/api/xbrl/companyfacts/CIK{cik}.json",
                                   max_age=COMPANY_FACTS_MAX_AGE)
        if not facts:
            return None, self.sec.last_error
        subs = self.sec._get_json(f"{self.sec.SEC_API}/submissions/CIK{cik}.json")
        acceptance = {f['accession_number']: (f['published_at'], f['published_at_basis'])
                      for f in self.sec._recent_filings(subs) if f['accession_number'] and f['published_at']} \
            if subs else {}
        rows = facts_to_observations(cik, facts, acceptance, INSTANT_TAGS, DURATION_TAGS)
        rows += facts_to_observations(cik, facts, acceptance, (), (EPS_TAG,), unit='USD/shares')
        rows += facts_to_observations(cik, facts, acceptance, (SHARES_TAG,), (), namespace='dei',
                                      unit='shares')
        rows += facts_to_observations(cik, facts, acceptance, (BS_SHARES_TAG,), (WAVG_SHARES_TAG,),
                                      unit='shares')
        return rows, None

    def build_ticker(self, member, calendar, spy):
        """Rows for one stock on the evaluation calendar; (rows, info)."""
        prices = self.prices.get(member['yahoo_ticker'])
        if prices['status'] != 'OK' or prices.get('frame') is None:
            return [], {'status': DATA_UNAVAILABLE, 'reason': prices['reason']}
        frame = prices['frame'].join(spy.rename('spy'), how='inner')
        if 'volume' not in frame or 'close_raw' not in frame or len(frame) < MIN_HISTORY + 10:
            return [], {'status': DATA_UNAVAILABLE, 'reason': f'{len(frame)} usable sessions'}
        adj, raw = frame['close'].to_numpy(float), frame['close_raw'].to_numpy(float)
        volume, spy_values = frame['volume'].to_numpy(float), frame['spy'].to_numpy(float)
        dates = [d.date().isoformat() for d in frame.index]
        index = {d: k for k, d in enumerate(dates)}
        rows_sec, sec_error = self.sec_rows(member['cik']) if member.get('cik') else (None, 'no CIK')
        pit = PointInTimeFacts(rows_sec or [])
        splits, split_error = self.splits(member['yahoo_ticker'])
        history = None
        if self.insider is not None:
            history = self.insider.load(member['cik']) if member.get('cik') else {'error': 'no CIK'}
        out = []
        for day in calendar:
            i = index.get(day)
            if i is None or i < 252 or not member_at(member, day):
                continue
            known = session_close_utc(day)
            feats = price_features(adj, raw, volume, spy_values, i)
            shares_source = None
            if rows_sec:
                fund = fundamentals_at(pit.advance(known))
                shares_source = fund['shares_source']
                feats.update(fundamental_features(fund, raw[i], splits))
            else:
                feats.update(dict.fromkeys(FUNDAMENTAL_FEATURES))
            if self.insider is not None:
                mcap = 10 ** feats['log_market_cap'] if feats.get('log_market_cap') is not None else None
                feats.update(insider_features_at(history, known, mcap))
            row = {'ticker': member['ticker'], 'date': day, 'known_at': known,
                   'sector': member['sector'], 'features': feats, 'entry_date': None,
                   'shares_source': shares_source}
            if i + ENTRY_LAG < len(dates):
                row['entry_date'] = dates[i + ENTRY_LAG]
            for h in HORIZONS:
                exit_ = i + ENTRY_LAG + h
                row[f'fwd_{h}d'] = float(adj[exit_] / adj[i + ENTRY_LAG] - 1) if exit_ < len(dates) else None
                row[f'exit_{h}d'] = dates[exit_] if exit_ < len(dates) else None
            out.append(row)
        return out, {'status': 'OK', 'n_rows': len(out), 'sec_error': sec_error,
                     'split_error': split_error, 'sec_facts': len(rows_sec or []),
                     'first_session': dates[0], 'last_session': dates[-1],
                     'insider': None if history is None else (
                         {'error': history['error']} if history.get('error') else
                         {k: history[k] for k in ('coverage_start', 'n_filings', 'n_parsed')}
                         | {'n_failed': len(history['failed_at'])}),
                     'price_fetch_id': prices['fetch']['fetch_id']}

    def build(self, members, progress=True):
        spy_prices = self.prices.get(BENCHMARK)
        if spy_prices['status'] != 'OK':
            raise RuntimeError(f'benchmark {BENCHMARK} unavailable: {spy_prices["reason"]}')
        spy = spy_prices['close']
        sessions = [d.date().isoformat() for d in spy.index]
        calendar = sessions[MIN_HISTORY::STEP]
        rows, info = [], {}
        for n, member in enumerate(members, 1):
            try:
                ticker_rows, ticker_info = self.build_ticker(member, calendar, spy)
            except Exception as e:  # noqa: BLE001 - reported, the study continues
                ticker_rows, ticker_info = [], {'status': 'ERROR', 'reason': f'{type(e).__name__}: {e}'}
            rows += ticker_rows
            info[member['ticker']] = ticker_info
            if progress:
                print(f"  {member['ticker']:6} ({n}/{len(members)}) {ticker_info['status']} "
                      f"{ticker_info.get('n_rows', 0)} rows"
                      + (f" - {ticker_info.get('reason') or ticker_info.get('sec_error')}"
                         if ticker_info['status'] != 'OK' or ticker_info.get('sec_error') else ''))
        add_sector_features(rows)
        spy_values = spy.to_numpy(float)
        spy_index = {d: k for k, d in enumerate(sessions)}
        benchmark = {}
        for day in calendar:
            i = spy_index[day]
            benchmark[day] = {f'fwd_{h}d': float(spy_values[i + ENTRY_LAG + h] / spy_values[i + ENTRY_LAG] - 1)
                              if i + ENTRY_LAG + h < len(spy_values) else None for h in HORIZONS}
        return rows, info, benchmark, calendar


def json_dumps(value):
    import json
    return json.dumps(value)


def check_features(rows, features=FEATURES):
    """Every row must carry exactly the pre-registered features."""
    expected = set(features)
    for r in rows:
        missing = expected - set(r['features'])
        if missing:
            raise ValueError(f"{r['ticker']} {r['date']}: features not computed: {sorted(missing)}")
