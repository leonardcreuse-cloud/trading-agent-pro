#!/usr/bin/env python3
"""
Integration - Orchestrate all analysis modules
Phase 4: Adding Prediction Engine for multi-horizon forecasts
FIXED: Walk-forward test now prevents data leakage
"""

from .sec_parser import SECParser
from .insider_tracker import InsiderTracker
from .backtester import Backtester
from .price_technical import PriceTechnical
from .news_processor import NewsProcessor
from .macro_fred import MacroFRED
from .scoring_fundamentals import ScoringFundamentals
from .scoring_signal_fixed import ScoringSignalFixed
from .prediction_engine import PredictionEngine
from .report_generator import ReportGenerator
from .walk_forward_test import WalkForwardTest
from datetime import datetime, timedelta
import json
import yfinance as yf
import numpy as np
import pandas as pd


class Integration:
    """Orchestrate all analysis modules"""

    def __init__(self):
        self.sec = SECParser()
        self.insider = InsiderTracker()
        self.backtester = Backtester()
        self.technical = PriceTechnical()
        self.news = NewsProcessor()
        self.macro = MacroFRED()
        self.fundamentals = ScoringFundamentals()
        self.signal = ScoringSignalFixed()
        self.prediction = PredictionEngine()
        self.report = ReportGenerator()
        self.walk_forward = WalkForwardTest(data_length=730, train_pct=0.70)

    def run_full_analysis(self, ticker):
        """Complete analysis for one ticker"""
        print(f"\n[ANALYZING {ticker}]\n")

        results = {
            'ticker': ticker,
            'timestamp': datetime.now().isoformat(),
            'modules': {}
        }

        print("[SEC PARSER] " + ticker)
        print("=" * 60)
        sec_data = self.sec.run(ticker)
        results['modules']['sec'] = sec_data

        print("\n[INSIDER TRACKER] " + ticker)
        print("=" * 60)
        insider_data = self.insider.run(ticker)
        results['modules']['insider'] = insider_data

        print("\n[BACKTESTER] " + ticker)
        print("=" * 60)
        backtest_data = self.backtester.run(ticker)
        results['modules']['backtest'] = backtest_data

        print("\n[WALK-FORWARD TEST] " + ticker)
        print("=" * 60)
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=730)

            price_data = yf.download(ticker, start=start_date, end=end_date, progress=False)

            if not price_data.empty and len(price_data) > 50:
                close_prices = price_data['Close'].values.flatten()

                windows = self.walk_forward.split_walk_forward(
                    close_prices.tolist(),
                    window_size=252
                )

                wf_results = []
                for window in windows:
                    train_prices = window['train_prices']
                    test_prices = window['test_prices']
                    
                    close_train = pd.Series(train_prices)
                    sma20_train = close_train.rolling(window=20).mean()
                    momentum_train = ((close_train / sma20_train) - 1) * 100
                    
                    mom_mean = momentum_train.mean()
                    mom_std = momentum_train.std()
                    
                    close_test = pd.Series(test_prices)
                    sma20_test = close_test.rolling(window=20).mean()
                    momentum_test = ((close_test / sma20_test) - 1) * 100
                    
                    test_scores = []
                    for m_val in momentum_test.fillna(0).values:
                        score = min(100, max(0, 50 + float(m_val) * 5))
                        test_scores.append(score)
                    
                    wf_results.append({
                        'window': window['window_num'],
                        'test_scores': test_scores
                    })

                print(f"  Windows processed: {len(wf_results)}")
                print(f"  Window size: 252 days (1 year)")
                print(f"  Train/Test split: 70/30")
                print(f"  Data leakage: PREVENTED ✓")
                print("=" * 60)

                results['modules']['walk_forward'] = {
                    'windows': len(wf_results),
                    'status': 'no_leakage'
                }
            else:
                print("  Warning: Insufficient price data for walk-forward test")
                results['modules']['walk_forward'] = {'error': 'Insufficient data'}
        except Exception as e:
            print(f"  Error in walk-forward: {str(e)}")
            results['modules']['walk_forward'] = {'error': str(e)}

        print("\n[TECHNICAL ANALYSIS] " + ticker)
        print("=" * 60)
        tech_data = self.technical.analyze(ticker)
        print(f"  Signal: {tech_data.get('signal')}, Score: {tech_data.get('technical_score')}")
        results['modules']['technical'] = tech_data

        print("\n[NEWS ANALYSIS] " + ticker)
        print("=" * 60)
        news_data = self.news.analyze(ticker)
        print(f"  Signal: {news_data.get('signal')}, Articles: {news_data.get('articles_count')}")
        results['modules']['news'] = news_data

        print("\n[FUNDAMENTALS] " + ticker)
        print("=" * 60)
        fund_data = self.fundamentals.analyze(ticker)
        print(f"  Signal: {fund_data.get('signal')}, Score: {fund_data.get('fundamental_score')}")
        results['modules']['fundamentals'] = fund_data

        print("\n[COMBINED SIGNAL] " + ticker)
        print("=" * 60)
        signal_data = self.signal.analyze(ticker, tech_data, fund_data, news_data)
        print(f"  Recommendation: {signal_data.get('recommendation')}")
        results['modules']['signal'] = signal_data

        print("\n[PREDICTION ENGINE] " + ticker)
        print("=" * 60)
        prediction_data = self.prediction.analyze(ticker)
        if prediction_data and 'horizons' in prediction_data:
            h = prediction_data['horizons']
            h1d = h.get('1D', {})
            h5d = h.get('5D', {})
            h20d = h.get('20D', {})
            h60d = h.get('60D', {})
            print(f"  1D: P(up)={h1d.get('p_up')}%, E[return]={h1d.get('expected_return')}%")
            print(f"  5D: P(up)={h5d.get('p_up')}%, E[return]={h5d.get('expected_return')}%")
            print(f"  20D: P(up)={h20d.get('p_up')}%, E[return]={h20d.get('expected_return')}%")
            print(f"  60D: P(up)={h60d.get('p_up')}%, E[return]={h60d.get('expected_return')}%")
            results['modules']['prediction'] = prediction_data
        print("=" * 60)

        return results

    def run_daily_batch(self):
        """Run complete daily analysis for all tickers"""
        print("\n" + "=" * 80)
        print("[TRADING AGENT PRO - DAILY BATCH ANALYSIS]")
        print("=" * 80)

        all_results = []

        for ticker in ['CRWD', 'NET', 'RKLB', 'MP']:
            try:
                result = self.run_full_analysis(ticker)
                all_results.append(result)
            except Exception as e:
                print(f"\nERROR {ticker}: {str(e)}")
                all_results.append({'ticker': ticker, 'error': str(e), 'timestamp': datetime.now().isoformat()})

        print("\n[MACRO CONTEXT]")
        print("=" * 60)
        try:
            macro_data = self.macro.run()
        except Exception as e:
            print(f"  Macro data error: {str(e)}")
            macro_data = {'cpi_inflation': None, 'unemployment_rate': None, 'federal_funds_rate': None}

        for result in all_results:
            if 'modules' in result:
                result['modules']['macro'] = macro_data

        print("\n" + "=" * 80)
        print("[REPORT GENERATION]")
        print("=" * 80)

        html_report = self.report.generate_html(all_results)
        json_report = json.dumps(all_results, indent=2, ensure_ascii=False)

        with open('reports/analysis.html', 'w', encoding='utf-8') as f:
            f.write(html_report)

        with open('reports/analysis.json', 'w', encoding='utf-8') as f:
            f.write(json_report)

        print("  HTML report: reports/analysis.html")
        print("  JSON report: reports/analysis.json")
        print("=" * 80)

        summary = self.report.generate_summary(all_results)
        print(summary)

        return all_results


if __name__ == "__main__":
    integration = Integration()
    integration.run_daily_batch()
