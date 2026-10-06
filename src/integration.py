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
"""

import json

from .backtester import Backtester
from .common import (DATA_UNAVAILABLE, NOT_IMPLEMENTED, reports_dir, tickers,
                     unavailable, utc_now_iso)
from .dashboard import Dashboard
from .insider_tracker import InsiderTracker
from .macro_fred import MacroFRED
from .news_processor import NewsProcessor
from .prediction_engine import PredictionEngine
from .price_technical import PriceTechnical
from .report_generator import ReportGenerator
from .scoring_fundamentals import ScoringFundamentals
from .scoring_signal_fixed import ScoringSignalFixed
from .sec_parser import SECParser


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
        self.sec = SECParser()
        self.insider = InsiderTracker()
        self.backtester = Backtester()
        self.technical = PriceTechnical()
        self.news = NewsProcessor()
        self.macro = MacroFRED()
        self.fundamentals = ScoringFundamentals(sec_parser=self.sec)
        self.signal = ScoringSignalFixed()
        self.prediction = PredictionEngine()
        self.report = ReportGenerator()
        self.dashboard = Dashboard()

    @staticmethod
    def _safe(name, func, *args):
        """Run one module; an exception becomes an explicit unavailable payload."""
        try:
            return func(*args)
        except Exception as e:  # noqa: BLE001 - logged and surfaced in the report
            print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
            return unavailable(name, f"{type(e).__name__}: {e}")

    def run_full_analysis(self, ticker):
        """Complete analysis for one ticker"""
        print(f"\n[ANALYZING {ticker}]\n")

        modules = {}
        modules['sec'] = self._safe('sec', self.sec.run, ticker)
        modules['insider'] = self._safe('insider', self.insider.run, ticker)
        modules['backtest'] = self._safe('backtest', self.backtester.run, ticker)
        modules['walk_forward'] = {
            'status': NOT_IMPLEMENTED,
            'reason': 'Walk-forward validation not implemented yet (phase P1.2)',
        }
        modules['technical'] = self._safe('technical', self.technical.analyze, ticker)
        modules['news'] = self._safe('news', self.news.analyze, ticker)
        modules['fundamentals'] = self._safe('fundamentals', self.fundamentals.analyze, ticker)
        modules['signal'] = self._safe('signal', self.signal.analyze, ticker,
                                       modules['technical'], modules['fundamentals'],
                                       modules['news'])
        modules['prediction'] = self._safe('prediction', self.prediction.analyze, ticker)

        print(f"\n  Signal: {modules['signal'].get('recommendation', DATA_UNAVAILABLE)}")

        return {
            'ticker': ticker,
            'timestamp': utc_now_iso(),
            'modules': modules,
            'data_availability': {name: module_status(m) for name, m in modules.items()},
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

        print("\n[REPORT GENERATION]")
        out_dir = reports_dir()
        html_path = out_dir / 'analysis.html'
        json_path = out_dir / 'analysis.json'
        html_path.write_text(self.report.generate_html(all_results, run_started), encoding='utf-8')
        json_path.write_text(json.dumps(all_results, indent=2, ensure_ascii=False, default=str),
                             encoding='utf-8')
        print(f"  HTML report: {html_path}")
        print(f"  JSON report: {json_path}")
        dashboard_path = self.dashboard.save_dashboard_html(
            self.dashboard.create_live_dashboard_html(all_results))
        print(f"  Dashboard:   {dashboard_path}")

        print(self.report.generate_summary(all_results))
        return all_results


if __name__ == "__main__":
    Integration().run_daily_batch()
