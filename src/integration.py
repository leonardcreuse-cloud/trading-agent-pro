#!/usr/bin/env python3
"""
Integration - Orchestrate all analysis modules

P0.1 changes:
- Tickers come from scheduler_config.json (no hardcoded list).
- Removed the fake walk-forward block: it computed scores, discarded them and printed
  "Data leakage: PREVENTED" unconditionally. Walk-forward validation is reported as
  NOT IMPLEMENTED until phase P1.2.
- The "prediction" module is reported as historical base rates (not a model).
- Each run records a UTC timestamp and a data-availability summary per source.
- data/ and reports/ directories are created automatically.

P0.2 changes:
- One Database (schema v2, migrated on start with a backup) and one PriceFeed are
  shared by all modules: prices are downloaded once per ticker and run.
- Each result carries a `provenance` summary per module (source, rank, fetch id,
  retrieval / publication time, freshness).
- Reports are passed through redact() before being written (no API key on disk).

P0.3 changes:
- Fundamentals from SEC XBRL company facts; insider activity from parsed Form 4 XML.
  Both share the run's SECParser (one ticker file, one submissions feed per ticker).
- The insider score is the fourth component of the combined signal.

P1.2: the walk_forward block is the summary of the last 'python main.py walkforward' run
(reports/walk_forward.json), flagged stale after 7 days; DATA UNAVAILABLE if never run.

P1.4: the signal block carries validation (has predictive power been demonstrated?),
data_reliability (coverage, freshness, source ranks) and explicit NOT IMPLEMENTED
model_prediction / prediction_confidence / risk_score. It is not a trade recommendation.
"""

import json

from .backtester import Backtester
from .common import (DATA_UNAVAILABLE, history_dir, redact, stamp, reports_dir, tickers,
                     unavailable, utc_now_iso)
from .dashboard import Dashboard
from .database import Database
from .insider_tracker import InsiderTracker
from .macro_fred import MacroFRED
from .market_data import PriceFeed
from .news_processor import NewsProcessor
from .prediction_engine import PredictionEngine
from .price_technical import PriceTechnical
from .report_generator import ReportGenerator
from .scoring_fundamentals import ScoringFundamentals
from .scoring_signal_fixed import (ScoringSignalFixed, not_implemented_fields, research_summary,
                                   validation_status)
from .sec_parser import SECParser
from .walk_forward import latest_summary as walk_forward_summary


def module_status(payload):
    """'OK', 'PROVISIONAL', DATA UNAVAILABLE, NOT IMPLEMENTED or 'ERROR' for a module output."""
    if not isinstance(payload, dict):
        return DATA_UNAVAILABLE
    if payload.get('status'):
        return payload['status']
    if payload.get('error'):
        return 'ERROR'
    return 'OK'


class Integration:
    """Orchestrate all analysis modules"""

    def __init__(self):
        self.db = Database()
        self.prices = PriceFeed(db=self.db)
        self.sec = SECParser(db=self.db)
        self.insider = InsiderTracker(sec_parser=self.sec)
        self.backtester = Backtester(price_feed=self.prices)
        self.technical = PriceTechnical(price_feed=self.prices)
        self.news = NewsProcessor(db=self.db)
        self.macro = MacroFRED(db=self.db)
        self.fundamentals = ScoringFundamentals(sec_parser=self.sec)
        self.signal = ScoringSignalFixed()
        self.prediction = PredictionEngine(price_feed=self.prices)
        self.report = ReportGenerator()
        self.dashboard = Dashboard()

    @staticmethod
    def _safe(name, func, *args):
        """Run one module; an exception becomes an explicit unavailable payload."""
        try:
            return func(*args)
        except Exception as e:  # noqa: BLE001 - logged and surfaced in the report
            print(redact(f"  [ERROR] {name}: {type(e).__name__}: {e}"))
            return unavailable(name, f"{type(e).__name__}: {e}")

    @staticmethod
    def _data_reliability(modules):
        """Coverage, freshness and source rank of the inputs of the quantitative signal."""
        sig = modules['signal']
        names = {'technical': 'technical', 'fundamentals': 'sec', 'news': 'news', 'insider': 'insider'}
        inputs = {}
        for component, module in names.items():
            m = modules.get(module) or {}
            prov = m.get('financials_provenance') if module == 'sec' else m.get('provenance')
            prov = prov or {}
            inputs[component] = {
                'status': m.get('status') or m.get('source_status'),
                'source': prov.get('source'), 'source_rank': prov.get('source_rank'),
                'freshness': (prov.get('freshness') or {}).get('status', 'UNKNOWN'),
                'as_of_date': prov.get('as_of_date')}
        weak = [c for c, i in inputs.items()
                if c in sig.get('available_components', []) and i['freshness'] != 'FRESH']
        return {'coverage': sig.get('coverage'), 'missing_components': sig.get('missing_components'),
                'inputs': inputs, 'not_fresh_inputs': weak,
                'note': 'Reliability of the data feeding the signal, not of the signal itself.'}

    def run_full_analysis(self, ticker):
        """Complete analysis for one ticker"""
        print(f"\n[ANALYZING {ticker}]\n")

        modules = {}
        modules['sec'] = self._safe('sec', self.sec.run, ticker)
        modules['insider'] = self._safe('insider', self.insider.run, ticker)
        modules['backtest'] = self._safe('backtest', self.backtester.run, ticker)
        modules['walk_forward'] = self._safe('walk_forward', walk_forward_summary)
        modules['technical'] = self._safe('technical', self.technical.analyze, ticker)
        modules['news'] = self._safe('news', self.news.analyze, ticker)
        modules['fundamentals'] = self._safe('fundamentals', self.fundamentals.analyze, ticker)
        modules['signal'] = self._safe('signal', self.signal.analyze, ticker,
                                       modules['technical'], modules['fundamentals'],
                                       modules['news'], modules['insider'])
        modules['prediction'] = self._safe('prediction', self.prediction.analyze, ticker)
        if isinstance(modules['signal'], dict) and 'quantitative_signal' in modules['signal']:
            modules['signal'].update({
                'validation': validation_status(modules['walk_forward'],
                                                [research_summary(1), research_summary(2)]),
                'data_reliability': self._data_reliability(modules),
                **not_implemented_fields(),
            })

        sig = modules['signal']
        print(f"\n  {sig.get('signal_summary', DATA_UNAVAILABLE)}")
        if sig.get('validation'):
            print(f"  Validation: {sig['validation']['status']} - not a trade recommendation")

        return {
            'ticker': ticker,
            'timestamp': utc_now_iso(),
            'modules': modules,
            'data_availability': {name: module_status(m) for name, m in modules.items()},
            'provenance': {name: m.get('provenance') for name, m in modules.items()
                           if isinstance(m, dict) and m.get('provenance')},
        }

    def run_daily_batch(self):
        """Run complete analysis for all configured tickers"""
        run_started = utc_now_iso()
        print("\n" + "=" * 80)
        print(f"[TRADING AGENT PRO - BATCH ANALYSIS] started {run_started}")
        print("=" * 80)

        all_results = [self.run_full_analysis(t) for t in tickers()]

        macro_data = self._safe('macro', self.macro.run)
        for result in all_results:
            result['modules']['macro'] = macro_data
            result['data_availability']['macro'] = module_status(macro_data)
        macro_provenance = {name: ind.get('provenance')
                            for name, ind in (macro_data.get('indicators') or {}).items()
                            if ind.get('provenance')}

        print("\n[REPORT GENERATION]")
        out_dir = reports_dir()
        html_path = out_dir / 'analysis.html'
        json_path = out_dir / 'analysis.json'
        html_path.write_text(redact(self.report.generate_html(all_results, run_started,
                                                              macro_provenance)),
                             encoding='utf-8')
        report_json = redact(json.dumps(all_results, indent=2, ensure_ascii=False, default=str))
        json_path.write_text(report_json, encoding='utf-8')
        (history_dir() / f'analysis_{stamp(run_started)}.json').write_text(report_json, encoding='utf-8')
        print(f"  HTML report: {html_path}")
        print(f"  JSON report: {json_path}")
        dashboard_path = self.dashboard.save_dashboard_html(
            redact(self.dashboard.create_live_dashboard_html(all_results)))
        print(f"  Dashboard:   {dashboard_path}")

        print(self.report.generate_summary(all_results))
        return all_results


if __name__ == "__main__":
    Integration().run_daily_batch()
