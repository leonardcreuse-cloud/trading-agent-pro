# Master mission — requirement traceability (state on 2026-10-12)

Each requirement of the master mission, its status, and where it is implemented and tested.

**Statuses:**
- **DONE**: implemented and checked by tests and a live run.
- **PARTIAL**: implemented, with a stated gap.
- **BLOCKED**: needs a source this environment refuses, or a licence.
- **NOT IMPLEMENTED**: deliberately absent, with the reason.

Live figures are from the cloud database on 2026-10-12. Commands are `python main.py <command>`.

## 1. Absolute rules

| Requirement | Status | Where / evidence |
|---|---|---|
| No fabricated values in production | DONE | P6 scan (`docs/MISSION_STATUS.md`): no random data, no neutral-50 default, no missing value set to 0 in production code. Demo blocks on invented inputs were removed. Two research-only rules are documented as errata, results unchanged. |
| Synthetic data only in isolated tests | DONE | `tests/conftest.py` redirects data and reports to a temporary folder and blocks the network. `common._not_production_under_tests` refuses the production folders under pytest. |
| DATA UNAVAILABLE / NOT IMPLEMENTED / NOT CALIBRATED, never 0, 50 or an average | DONE | `docs/DATA_POLICY.md` (status vocabulary); every section's `unavailable()` items carry a reason. |
| A failing source is named with its error | DONE | The `source_fetches` log; `collect`, `sources`, and report part 20. |
| Traceable sources (source, timestamp, value, method) | DONE | Observations carry `published_at`, `retrieved_at` and `fetch_id`, with raw payloads hashed. Report evidence items and the archive manifest list the fetch ids. |
| FEATURE_INFORMATION_TIMESTAMP <= PREDICTION_TIMESTAMP | DONE | `weekly/core.evidence` raises `LookAheadError`. Point-in-time readers use `known_at`. The audit's walk-forward checks; the stage 3 timing rule. |
| Source format changes detected | DONE | Audit `record_count_drops` (parsed-record drops per endpoint); parsers return DATA UNAVAILABLE on layout changes. |
| Back up before migration; no irreversible deletion | DONE | `dedupe` writes a backup first; journals are append-only; research results are write-once (`--recalc` keeps originals). |
| Pre-registered hypotheses never modified | DONE | Stage 1/2/3 and PT1 documents committed before their data. Errata are appended and dated; results are unchanged. |

## 2. Initial assessment

| Requirement | Status | Where / evidence |
|---|---|---|
| Repository state, commits, experiments | DONE | `docs/MISSION_STATUS.md` (P0). |
| `analyze`, `audit`, `weekly`, tests run | DONE | P0, P6 and gap-round live runs. Tests: 598 passed. |
| Unreached modules, stubs, silent exceptions, reports vs code | DONE | 19 unreached modules moved to `legacy/`. `DATA_POLICY.md` re-aligned with the code (ex-news signal, statuses). The macro unit bug and the duplicate valuation basis were found and fixed. |
| Stage 2 preserved and distinguishable from recalculations | DONE | `reports/research_stage2.json` is write-once; `--recalc LABEL` writes separate files that keep the original SHA-256. |

## 3. Pillar 1 — fundamentals and macro

| Requirement | Status | Where / evidence |
|---|---|---|
| Income statement, balance sheet, cash flow, dilution | DONE | `src/fundamentals_ext.py`, `src/sec_xbrl.py`; weekly part 9. |
| Company guidance | DONE (quoted) | `src/guidance.py`: the latest 8-K item 2.02, exhibit 99, "Outlook / Guidance" section, quoted verbatim and never parsed into numbers. Live: CRWD, NET, RKLB quoted; MP issues none. |
| Valuation ratios with formulas and guards | DONE | `src/valuation.py` (P/E only with a meaningful denominator, P/B, ROE, P/S, EV/sales, EV/EBITDA, FCF yield). History percentiles; peers, with split-suspect peers excluded unless explained. |
| Intrinsic value (DCF, scenarios, sensitivity, reverse DCF, reliability) | DONE | `src/intrinsic.py`; assumptions in `scheduler_config.json` `valuation.dcf`. |
| Macro: CPI, PPI, PCE, GDP, labour, Fed / ECB, yields, curve, real yields, spreads, VIX, dollar, confidence, retail, industry | DONE | `weekly/sections/macro.py`, `agencies.py` (FRED / ALFRED vintages, BLS, BEA). |
| PMI | PARTIAL | ISM and S&P Global are proprietary and not on FRED. Shown instead: the Philadelphia, New York and Dallas Fed manufacturing surveys (official, not PMIs), industrial production, capacity utilisation. |
| Monetary and fiscal policy | DONE | Fed funds target, ECB rate, Fed total assets (WALCL), monthly federal deficit (MTSDS133FMS), FOMC calendar. |
| Transmission to companies, correlation ≠ causation | DONE | Synthesis macro pillar and commodities exposure map: rule-based statements, labelled as interpretation. |
| Commodities: oil, gas, gold, copper, metals | DONE | `weekly/sections/commodities.py` (FRED / IMF series via FRED, EIA, COMEX futures via yfinance). |
| Rare earths, lithium | BLOCKED | No free official price series; USGS is refused by the network policy. Listed as DATA UNAVAILABLE. |
| Geopolitics: 7-point event analysis | DONE | `weekly/sections/geopolitics.py` (Federal Register, GPR, GDELT). |

## 4. Pillar 2 — technical analysis

| Requirement | Status | Where / evidence |
|---|---|---|
| Raw and adjusted prices, sessions, splits, dividends, volumes, missing dates, units | DONE | `market_data.py`; audit checks for bars, OHLC, missing sessions, volumes, adjustment steps and splits. |
| Identifier changes | DONE | Audit `identifiers`: the ticker resolves to the CIK of every stored SEC fact; name changes over 5 years are reported. |
| Provider identified as secondary | DONE | `source_registry.py` (yfinance rank 2, unofficial). |
| Second source cross-check | DONE | Cboe delayed daily history (`collect`); audit `second source`; weekly part 2 table. Live: 40 of 41 tickers identical. HON reveals a 1-for-2 split that yfinance does not list. |
| SMA / EMA 20-50-200, RSI, MACD, Bollinger, ATR, volatility, momentum 1-3-6-12, drawdown, relative volume, relative strength, trend strength | DONE | `src/technicals.py`. Reference check against stockstats: `tests/test_p73_reference_indicators.py`; conventions documented. |
| Support / resistance, trends, breakouts, retracements, highs / lows, candles, volatility regimes | DONE | `technicals.analyze` (pivots known with a k-bar delay, levels, 55-session breakout, retracement of the last swing, 52-week range, four candle patterns, HV20 regime). |
| Dow, Elliott, SMC / ICT | NOT IMPLEMENTED | Rules are not precise enough to reproduce (`NOT_IMPLEMENTED_METHODS`). |
| Indicators describe conditions; never a validated prediction | DONE | Every technical statement says so; no indicator feeds a trade rule except the frozen stage 3 heuristic, which is under test. |

## 5. Pillar 3 — quantitative

| Requirement | Status | Where / evidence |
|---|---|---|
| Factor groups tested | PARTIAL | Tested: momentum, quality, growth, value, volatility / liquidity / size, relative strength, sector (stage 1), and insider (stage 2). Not tested: analyst revisions (no free point-in-time history), macro (time-series design needed), events and sentiment (earnings-surprise and news histories not built; NewsAPI keeps one month). |
| Hypotheses before confirmation | DONE | `docs/research/STAGE2_PREREGISTRATION.md`, `STAGE3_PREREGISTRATION.md`, `PAPER_STRATEGY_PT1.md`. |
| Regression, regularisation, baselines, random forest, gradient boosting | DONE | `src/research/experiment.py` (logistic, L2 logistic, random forest, gradient boosting; baselines). |
| Temporal splits, walk-forward, purging, out of sample, point in time, multiple testing, dependence | DONE | `research/experiment.py`, `research/stats.py` (purged folds, Benjamini-Hochberg, effective n for overlapping horizons). |
| Delisted stocks, survivorship | BLOCKED | No allowed source of delisted prices. The bias is stated in every study. |
| Metrics (AUC, precision / recall / F1, Brier, calibration, Sharpe, Sortino, drawdown, turnover, costs, benchmarks) | DONE | `research/metrics.py`, `heuristic_evaluation.py`, `research/stats.py`. |
| Probabilities never invented; NOT CALIBRATED | DONE | `scoring_signal_fixed.predicted_probability`; dashboard; DATA_POLICY. |
| Can conclude no edge | DONE | Walk-forward NOT DEMONSTRATED; stages 1 and 2 confirmed 0 of 4 hypotheses; the heuristic evaluation shows no edge. |

## 6. Pillar 4 — sentiment and positioning

| Requirement | Status | Where / evidence |
|---|---|---|
| News pipeline (validation, dedup, relevance, events, sentiment, materiality, exposure, novelty, evidence) | DONE | `news_processor.py`, `weekly/sections/news.py`. The lexicon sentiment is descriptive only (NOT VALIDATED, outside the signal). |
| Aggregator not proof alone | DONE | NewsAPI is rank 3; news conclusions are always UNCERTAIN. |
| COT, put / call, IV, IV percentile, OI, skew, term structure, VIX, short interest, days to cover | DONE | `external_sources.py`, `weekly/sections/positioning.py`. The IV percentile needs a year of snapshots and shows DATA UNAVAILABLE until then. Short interest is labelled semi-monthly. |
| Fear & Greed | NOT IMPLEMENTED | Editorial index; its host is refused here. |
| Source access re-tested; endpoint, status, auth, frequency, terms, limits | DONE | `python main.py sources` (`src/source_registry.py`). Live: 17 / 17 integrated sources reachable; 10 official alternatives refused by the network policy. |

## 7. Combining the pillars

| Requirement | Status | Where / evidence |
|---|---|---|
| Explainable agree / conflict / not comparable; no score addition into a recommendation | DONE | `weekly/sections/synthesis.py` (rules `synthesis-v1`). Agreement is labelled a hypothesis; no weights are changed. |

## 8. Risk

| Requirement | Status | Where / evidence |
|---|---|---|
| Sizing 1% target / 2% hard, exposure, sector, concentration, liquidity, volatility; stop limitation documented | DONE | `src/risk.py`, `docs/research/PAPER_STRATEGY_PT1.md`. |
| Risk metrics; no validated global score | DONE | `risk.portfolio_metrics`; weekly part 18 (PT1 portfolio risk); `RISK_SCORE_STATUS` NOT IMPLEMENTED. |

## 9–10. Journals and paper trading

| Requirement | Status | Where / evidence |
|---|---|---|
| Prediction journal fields; transaction journal fields; separate, append-only, never rewritten | DONE | `src/journal.py` (hash chain), `src/paper.py`. |
| Realised result and drawdown per trade | DONE | `src/paper_report.py` `trades` (realised or unrealised P&L, sessions held, worst position value against cost). |
| Pre-registered rules, execution after the signal, costs, dividends, splits, benchmarks | DONE | PT1: market-on-open after the record; commission, slippage and spread; corporate actions; SPY and equal-weight benchmarks. |
| Monitoring: return, volatility, Sharpe, Sortino, drawdown, turnover, costs, by horizon, calibration, backtest vs paper | DONE | `paper.status`, `paper_report.outcomes_by_horizon`, `backtest_vs_paper`; `paper report`; weekly part 21; dashboard. |
| 12 months before any real money; no real orders | DONE | No broker code; the PT1 evaluation needs 52 weekly rebalances. |

## 11. Weekly analyst

| Requirement | Status | Where / evidence |
|---|---|---|
| 22 parts, 13 questions per asset, facts vs calculations vs interpretations | DONE | `weekly/report.py` (structure table); conclusion kinds and evidence levels. |
| Refresh, availability check, news window, pipeline, validation checks, report, archive, failures | DONE | `scripts/daily_run.py`: Sunday runs collect, analyze, prospective, paper, sources, audit, weekly, dashboard; status INCOMPLETE gives exit 3. |
| Reproducible from data and code version | DONE (with a stated limit) | `weekly --verify`: the rebuild of v16 is IDENTICAL (521 items). Inputs re-downloaded at generation (adjusted prices revised after dividends, news) can change a rebuild made weeks later; `--verify` lists every difference. |
| Facts checked against their sources | DONE | `verify-report`: v16 gives 84 of 84 MATCH (FRED as known at the cutoff, SEC filings, closes, guidance quotes). |

## 12. Dashboard

| Requirement | Status | Where / evidence |
|---|---|---|
| Price, fundamentals, valuation, trend, indicators, regime, events, risks, missing data, source quality, signal, validation, predictions, paper, benchmarks | DONE | `src/dashboard.py`, `python main.py dashboard` (daily, last step). Only real outputs, each dated; DATA UNAVAILABLE with the reason otherwise. |

## 13–16. Architecture, phases, success criteria

| Requirement | Status | Where / evidence |
|---|---|---|
| Pipeline from sources to monitoring, reusing modules | DONE | See `docs/MISSION_STATUS.md` (P0–P6 and gap round G0–G6). |
| Phase reports (files, tests, results, gaps) | DONE | `docs/MISSION_STATUS.md`, `docs/CHANGELOG.md`. |
| Edge claims | — | None is made: no predictive ability has been demonstrated. |
