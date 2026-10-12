# Master mission — status by phase

Mission received 2026-10-12: a reliable financial analyst, quantitative research system and paper-trading
platform (four pillars, risk engine, journals, paper trading, weekly report), with data integrity first.
This file is updated at the end of every phase with what was actually run and observed.

## P0 — Data integrity and calculation safety (2026-10-12)

### State found
- Git: branch `claude/nifty-ramanujan-u1p317`, clean, in sync with origin (head ce558b3). Not merged into main.
- Experiments:
  - **Stage 1** (2026-10-07): finished.
  - **Stage 2 holdout** (2026-10-11): finished, 0 of 4 pre-registered hypotheses confirmed. Results are in
    `reports/research_stage2.json` and `docs/research/STAGE2_RESULTS.md` (committed).
  - **Stage 3 prospective record**: started 2026-10-12, first record committed before the open.
- Production commands, run live in the cloud copy of the database (a clean worktree at HEAD):

  | Command | Exit | Result |
  |---|---|---|
  | `analyze` | 0 | 4 tickers |
  | `weekly` | 0 | Week ending 2026-10-09, v5: 86 strongly supported, 140 uncertain, 45 data unavailable |
  | `audit` | 0 | 0 FAIL, 440 PASS, 8 WARN |
  | `collect` | 2 | Every source OK except GDELT 2026-10-11 (HTTP 404: that daily file is published the next morning, and the run was at 07:00 UTC) |

- Tests: 490 passed before the changes, 495 after.

### Findings and what was done

| Finding | Action |
|---|---|
| A rerun of `research --stage N` would overwrite the pre-registered results file | Results are written once (`open(..., 'x')`) and checked before any work. A later run needs `--recalc LABEL` and goes to `research_stage<N>_recalc_<label>.json`, marked as not confirmatory, with the original's SHA-256 |
| 19 modules never called by `main.py`, `daily_run` or `scheduler`, several with fabricated defaults (`return 50` confidence/reliability, hardcoded prices 150.25/150.50, neutral baseline 50, default 50% win rate, yfinance `.info` P/E without provenance); 10 ad-hoc root scripts; text copies of the initial code | Moved with `git mv` to `legacy/`, with a README giving the reason for each. Nothing imports them (checked by an import graph from the entry points) |
| Tests could reach the production database if a test removed the temporary-folder variables | `data_dir()` / `reports_dir()` refuse the production folders under pytest |
| Option open interest / volume: missing values summed as 0, so a side with no reported value gave a put/call ratio of 0 | Sums over reported values only. The ratio is None when a side has none. Missing quotes are counted |
| RSI of the heuristic: warm-up values filled; returns 50 when the average loss is 0 (Wilder: 100); seed uses period+1 deltas | **Not changed**: this RSI defines the frozen signal of stage 3 (protocol stage3-v1, pre-registered the same morning). The deviations are documented in `src/indicators.py`. Their effect on the last value of 150 closes is negligible (seed decayed by (13/14)^136; the zero-loss case needs 150 closes without a down day). The descriptive technical analysis (P2) uses a separate, reference-tested module |
| Dashboard showed "N/A — source unavailable" for features that do not exist | Now NOT IMPLEMENTED (model prediction, risk score) and NOT CALIBRATED (prediction confidence) |
| Daily report: "Form 4 filings / parsed (90d)" showed the count of the 111-day ingestion window | Two rows: filings in the scored 90-day window, documents ingested / read (111 days) |
| Redundant versions: `dedupe` removed 39,419 rows, then the next SEC ingestion re-created 39,381. Cause: each later filing repeats earlier values, and insertion only skipped an exact duplicate | Insertion now applies the same rule as `dedupe` (a version that repeats its predecessor in availability order, retrieved no earlier, is not stored). Live: 0 redundant versions after the audit's SEC re-ingestion (was 39,381) |
| Source format changes: collectors flagged an empty parse, but a partial drop was silent; most collectors did not record how many values a download produced | Every stored download records its parsed count. The audit flags an endpoint whose latest count is 0 or under half its usual count (stable sources only; calendars with a moving window excluded). Live: no endpoint flagged |

### SEC timestamps (plan and status)
- Handling corrected in P4.2: each company's acceptance-label convention is checked on EDGAR filing index pages,
  and labels are converted to the true acceptance instant. The audit re-checks 2 filings per ticker on every run:
  40 of 40 tickers PASS today. A future relabelling by the SEC (as between 2026-10-07 and 2026-10-10) shows up
  as an audit FAIL.
- Stages 1 and 2 kept the earlier reading (New York time): conservative, with no look-ahead (some filings are
  dated 4-5 h late). The original results stay as they are. A labelled recalculation
  (`python main.py research --stage 2 --recalc sec-calibrated`, several hours) would be exploratory only. It
  was not run: the confirmatory conclusion cannot change by protocol.

### Live check after the changes (cloud database)
- `dedupe`: database backed up first (`data/backups/`), 39,419 then 39,381 versions removed. 0 remain after re-ingestion.
- `audit`: 0 FAIL, 441 PASS, 8 WARN. The WARNs, checked one by one:
  - MP +50.6% on 2025-07-10: the real move after the Department of Defense agreement.
  - MU +256% revenue growth: matches the SEC 10-K (FY to 2026-09-03, $133.19B against $37.38B).
  - CRWD / LMT open-market transactions without a price: the value stays unknown.
  - DE / ISRG debt and XOM TTM revenue: XBRL tags not recognised (P1).

### Remaining after P0
- Several official hosts are refused by the environment's network policy: www.worldbank.org,
  data-api.ecb.europa.eu, home.treasury.gov, api.fiscaldata.treasury.gov, api.census.gov, www.usgs.gov,
  prices.lbma.org.uk, www.imf.org, api.nasdaq.com. FRED covers most of the same series (ECB deposit rate,
  Treasury yields, real yields, copper / aluminium / nickel from the IMF, Brent / WTI / Henry Hub from the EIA).
  Gold (LBMA, removed from FRED) and the ISM PMI (proprietary) have no allowed official source.
- The owner's PC database still holds the redundant versions created by the older code: `python main.py dedupe`
  once after pulling (already listed in `docs/HANDOFF.md`).

## P1 — Fundamental and macroeconomic analysis (2026-10-12)

### Files
- New: `src/fundamentals_ext.py`, `src/valuation.py`, `src/intrinsic.py`, `src/weekly/sections/valuation.py`,
  `src/weekly/sections/commodities.py`, `tests/test_p61_fundamentals_ext.py`.
- Changed: `src/sec_xbrl.py`, `src/sec_parser.py` (extended XBRL concepts stored),
  `src/weekly/sections/macro.py`, `catalysts.py` and `geopolitics.py`, `src/weekly/report.py` (2 sections),
  `scheduler_config.json` (explicit DCF assumptions).

### Regression risk handled
The stage 3 signal reads revenue, revenue growth and debt / equity through `src/sec_xbrl.py`. Those
definitions are unchanged; a test pins them. Extended concepts go into separate groups, used only by the
descriptive analysis.

### What exists now (all point-in-time, sourced, formulas in the module docstrings)

**Company fundamentals** (SEC XBRL, official):
- TTM and quarterly revenue with year-on-year growth;
- gross, operating, net and FCF margins, with their change over a year;
- diluted EPS: exact from a 12-month fact; otherwise approximate, refused across a suspected split or when
  its sign contradicts net income;
- cash, short-term investments, net debt, current ratio, EBITDA, interest coverage, R&D share;
- cash conversion (only above a 2% net margin); cash runway when free cash flow is negative;
- cover-page shares and their one-year change.

Company guidance is NOT IMPLEMENTED (unstructured text).

**Valuation** (yfinance close + SEC):
- Ratios: market cap, EV, P/E, P/B, ROE, P/S, P/FCF, EV/sales, EV/EBITDA, FCF yield.
- Not meaningful: a denominator that is not positive, or an earnings multiple whose denominator is under 2%
  of revenue.
- History: quarterly points over 5 years, each with the fundamentals known then. It stops at a suspected
  split rather than mixing split-adjusted prices with as-reported share counts.
- Peers: comparison with the medians of the pre-declared peers.

**Intrinsic value**:
- A two-stage FCF model with bear, base and bull scenarios.
- Sourced inputs: risk-free rate (FRED DGS10 at the cutoff), beta (weekly returns vs SPY), revenue growth
  (3-year CAGR, SEC).
- Assumptions in config, labelled as such: equity risk premium 5%, terminal growth 2.5%, 5 years.
- Also: a sensitivity grid and a reverse DCF (growth implied by the price).
- Reliability is never higher than ASSUMPTION-DRIVEN. FCF ≤ 0 → NOT RELIABLE, no value.

**Macro**: added the 10-year real yield, the 10-year breakeven, the ECB deposit rate, the IG credit spread,
EUR/USD, core PCE, industrial production and capacity utilisation. PMI: DATA UNAVAILABLE (proprietary).

**Commodities** (new section):
- Official sources: EIA oil and gas, IMF metals and agricultural prices, BLS steel and gold price indexes.
- Secondary source: COMEX/NYMEX front-month futures via yfinance, with the roll caveat.
- Unavailable with reasons: rare earths, lithium, cobalt, LBMA gold.
- A pre-declared company exposure map, marked as interpretation, with no estimated sensitivity.

**Calendar**: added PPI, industrial production, JOLTS, housing starts and trade (12 FRED release calendars in
total), plus a cross-check of the yfinance earnings date against the anniversary of last year's 8-K item 2.02.

**Geopolitics**: each Federal Register document of the window gets the seven points: what was published,
source and date, exposed sectors and companies, mechanism, horizon, evidence, uncertainties. Themes come from
a pre-declared keyword map (interpretation); no headline becomes a signal.

### Tests and live results
- Tests: 514 passed (13 new).
- Live examples (cloud database, close of 2026-10-09):

  | Ticker | Key result |
  |---|---|
  | MSFT | P/E 29.8, EV/EBITDA 20.3 (D&A $39B = Depreciation + AmortizationOfIntangibleAssets), ROE 34% |
  | NVDA | P/E 29.0, EV/EBITDA 27.5 |
  | CRWD | 4:1 split detected (yfinance split of 2026-07-02 matches the SEC cover counts 254.6M → 1,024M); EPS on a consistent share basis; P/E not meaningful (net margin 0.8%) |
  | PANW | GAAP P/E 1,047, which is genuine: FY to 2026-07-31 diluted EPS $0.40 |
  | XOM | Revenue and DE total debt unavailable: company-specific XBRL tags, outside the standard taxonomy |

- DCF base cases are far below market prices for growth companies (e.g. MSFT $159 against $535). That is
  what a 5-year fade to 2.5% at an 11% cost of equity gives. The reverse DCF shows the growth the price
  implies instead. These are never presented as fair values.
- Weekly report v6 for 2026-10-09: 102 strongly supported (86 before), 171 uncertain, 63 data unavailable.
  No section error.

### Remaining after P1
- Gold (LBMA) and PMI have no allowed official source.
- Several official hosts are blocked by the network policy (see P0).
- Company guidance and issuer-announced earnings dates in 8-K exhibits are not parsed.
- EV excludes minority interests, preferred stock and leases.
- The DCF treats FCF as free cash flow to equity and ignores net borrowing.

## P2 — Technical analysis and sentiment (2026-10-12)

### Files
- New: `src/technicals.py`, `src/weekly/sections/technicals.py`, `tests/test_p62_technicals.py`.
- Changed:
  - `src/market_data.py`: adjusted open, high and low kept and stored.
  - `src/pipeline_audit.py`: market-data checks.
  - `src/external_sources.py`: option skew and term structure.
  - `src/weekly/sections/positioning.py`, `news.py`, `quant.py`; `src/weekly/report.py`.
  - `src/scoring_signal_fixed.py`: news removed from the combined signal.

### Regression risk handled
`src/indicators.py`, the frozen heuristic's RSI / MACD / Bollinger, is unchanged: the new indicators are a
separate module. Price-feed columns were added; `close` is unchanged.

### What exists now

**Technical indicators** (reference implementations, warm-up values undefined, no filled bars):
- Moving averages: SMA and EMA 20/50/200.
- Oscillators and bands: Wilder RSI, MACD 12/26/9, Bollinger 20/2 (population standard deviation).
- Wilder ATR and ADX.
- Volatility: 20- and 60-day historical.
- Momentum: 1/3/6/12 months and 12-1.
- Drawdowns, relative volume, relative strength against SPY and against the sector ETF.
- A trend rule with persistence.

**Price action** (objective rules):
- Swing pivots, known only k bars later, so no look-ahead.
- Support and resistance from pivots clustered within half an ATR.
- 55-session breakouts, the 52-week range, the volatility regime (HV20 percentile over 3 years), five
  candle patterns.
- Dow theory, Elliott waves and SMC/ICT: NOT IMPLEMENTED (not reproducible).

**Market-data validation** (audit):
- OHLC consistency, sessions missing against the SPY calendar, zero volumes.
- Jumps in the adjusted/unadjusted ratio.
- yfinance splits checked against jumps in the SEC cover-page share count. Live: the CRWD 4:1 split (2026)
  and NVDA's 2021 and 2024 splits matched.

**Sentiment**:
- The word lexicon could not be validated: Hugging Face is blocked and third-party repositories are out of
  scope, so no labelled financial text was available. It also has no negation handling and uses ambiguous
  words.
- It is now descriptive only and **no longer part of the combined signal**. The daily signal is the ex-news
  variant, the one the walk-forward evaluated and stage 3 records. Weights and thresholds are unchanged.

**News**: per story cluster, pre-declared event classes, a materiality per class, and novelty against the
previous window's stored query. The existing deduplication (canonical URL, normalised titles, clusters)
is kept.

**Options**:
- New: skew (90% put IV minus 110% call IV at about 30 days) and term slope.
- ATM quotes must be within 5% of spot. Outside US hours Yahoo returns zero bid/ask, and those quotes are
  refused.
- IV percentile: DATA UNAVAILABLE until 252 daily snapshots exist (no historical option source).
- Already present: COT, put/call, short interest with days to cover, VIX.

### Tests and live results
- Tests: 530 passed. Indicators are checked against hand-computed values: the Wilder RSI of the classic
  20-close example, ATR, the seeded EMA, Bollinger, historical volatility.
- Weekly report v7 for 2026-10-09: 14 sections, none failed.
- Live CRWD on 2026-10-09: RSI 64.9, 3-month momentum +46%, trend rule "up" with a strong ADX, volatility
  regime normal (80th percentile).

### Remaining after P2
- Sentiment validation needs a labelled dataset reachable under the network policy.
- The IV percentile needs a year of snapshots.
- Option skew is only measured from snapshots taken while quotes are live (the evening run).
- A second independent price source (Stooq, Alpha Vantage) is blocked: only the SPY / FRED SP500
  cross-check exists.

## P3 — Quantitative models (2026-10-12)

### State
- **Stage 1** (148 stocks) and **stage 2** (242-stock holdout, 0 of 4 pre-registered hypotheses confirmed) are
  finished and preserved. The results files can no longer be overwritten (P0).
- **Stage 3** (prospective) has started.
- The research code already provides:
  - rank-IC tests with Newey-West t-statistics, 95% intervals, and Holm / Benjamini-Hochberg / Bonferroni
    corrections;
  - purged walk-forward models (training only on outcomes known before each test fold);
  - out-of-sample periods and AUC;
  - non-overlapping quintile portfolios, gross and net of 10 bps per unit of turnover, with Sharpe, Sortino,
    max drawdown, turnover, an equal-weight universe benchmark and SPY.

### Added
- `src/research/metrics.py`: AUC (Mann-Whitney), precision / recall / F1 with undefined ratios left as None,
  Brier score (probabilities only), calibration bins and expected calibration error.
- Research model tests (future runs or labelled recalculations) now also report precision / recall / F1 at 0.5,
  Brier and calibration of the model probabilities. The original stage 1 / 2 files are unchanged.
- `python main.py evaluate-heuristic` (`src/heuristic_evaluation.py`): metrics of the heuristic on the existing
  walk-forward sample. Classification against positive returns and against the cross-sectional median;
  top-quintile, long-short and benchmark portfolios net of costs. Descriptive, no new hypothesis. Output:
  `docs/research/HEURISTIC_EVALUATION.md`.
- A "predicted probability: NOT CALIBRATED" field next to "prediction confidence".

### Live results (`docs/research/HEURISTIC_EVALUATION.md`: 40 tickers, 8,800 observations, 2022-05 → 2026-09)

| Horizon | Top quintile net Sharpe | Equal-weight Sharpe | SPY Sharpe | Long-short net | Top quintile vs equal weight |
|---|---|---|---|---|---|
| 5 sessions | 0.97 | 1.32 | 1.12 | −3.2% a year | −2.9% a year |
| 20 sessions | 1.07 | 1.31 | 1.19 | −5.3% a year | −1.9% a year |

- AUC against beating the median: 0.507 (5 sessions) and 0.508 (20 sessions).
- POSITIVE label precision: 0.540 against a 0.532 base rate (5 sessions); 0.533 against 0.552 (20 sessions).
- Reading: in this sample the heuristic adds nothing over holding the universe; it does slightly worse after
  costs. This matches the walk-forward validation status: NOT DEMONSTRATED.

### Not done, and why
- No new factor or combination was tested. Each new test without pre-registration adds to the multiple-testing
  burden.
- Untested factor groups need a pre-registered stage first, like stage 2:
  - sector and macro factors;
  - events;
  - sentiment: no history;
  - analyst revisions: no source.
- No stage 2 recalculation: the panel cache is not in this container (rebuilding needs hours of SEC / yfinance
  downloads), and the original result cannot change by protocol.
- Survivorship: prices of delisted companies are not available from the allowed sources. Every study states
  the bias, since its universe is current members.

## P4 — Risk management, journals and paper trading (2026-10-12)

### Files
- New:
  - `src/risk.py`, `src/journal.py`, `src/paper.py`;
  - `docs/research/PAPER_STRATEGY_PT1.md`, the pre-registration, committed (9da5530) before any code or order;
  - `tests/test_p64_risk_paper.py`.
- Changed: `src/market_data.py` (as-traded open/high/low), `main.py` (`paper`), `scripts/daily_run.py`
  (paper step every day), `scheduler_config.json` (`risk` and `paper` settings, labelled assumptions).

### What exists now

**Risk engine**:
- Sizing: 1% of equity at risk to the stop (hard limit 2%), counting round-trip costs per share, then capped by
  20% of equity per position, 1% of the 20-session volume, available cash, and a minimum traded value.
- Portfolio limits: gross exposure, sector (SEC SIC major group), positions.
- Metrics: volatility, beta, pairwise correlation, downside deviation, drawdown, days to exit.
- Position risk is reported separately from the capital invested.
- No global risk score: NOT IMPLEMENTED, none validated.

**Journals** (hash-chained, append-only; an append is refused on a broken chain):
- `reports/paper/predictions.jsonl`: one prediction per ticker and week, with every field required by the
  mission; outcomes are appended later as separate entries, never by editing a prediction.
- `reports/paper/transactions.jsonl`: start, rebalances, orders, fills, rejections, stops, dividends, splits
  and daily marks with both benchmarks.

**Simulator**, following PT1:
- Orders come only from a valid stage 3 record, written before the open of its entry session.
- Fills happen at the next session's as-traded open, adjusted for slippage and the spread, plus commission.
- Stops are checked on session lows; a gap through the stop fills at the open, below the stop.
- Corporate actions are applied before the open: dividends credited to the previous close's holder, splits
  adjusting shares, stop and cost basis.
- State is rebuilt only from the journal.
- Paper only: no broker library, no network call that places an order.

### Tests and live results
- Tests: 546 passed.
- Synthetic full cycle tested: fills with costs; a gap-through stop filled at the open; a dividend; a 2:1 split
  with as-traded conversion; equity = cash + positions; idempotence; refusal after the entry open.
- Live, 2026-10-12 08:00 UTC: PT1 started from the stage 3 record of 2026-10-09.
  - Orders: 8 market-on-open buys for the 2026-10-12 open (XOM, NVDA, UBER, GOOGL, MSFT, AMD, COST, ISRG).
  - Predictions: 40.
  - Pushed before the open (commit 01f8116).
  - The fills are processed by the first `paper update` after Monday's session (the PC's evening run).

### Remaining after P4
- Risk metrics of the paper holdings are not yet in the weekly report or the dashboard (P5).
- Event risk for the paper holdings relies on earnings snapshots that `collect` stores only for the configured
  universe (4 tickers).
- Commission, slippage and spread are assumptions: no execution data exists to calibrate them.

## P5 — Weekly report integration and automation (2026-10-12)

### Files
- New:
  - `src/weekly/sections/regime.py`, `data_quality.py`, `track_record.py` and `synthesis.py`;
  - `tests/test_p65_report.py` (synthetic inputs only).
- Changed:
  - `src/weekly/report.py`: 22-part structure, report status, sections that read earlier results;
  - `src/weekly/core.py`: the manifest carries the status;
  - `main.py`: `weekly` exits with 3 when INCOMPLETE;
  - `scripts/daily_run.py`: the weekly report runs on Sunday;
  - `tests/test_daily_run.py`, `docs/LOCAL_RUN.md`, `docs/HANDOFF.md`, `scripts/install_windows_task.ps1`.

### Regression risk handled
- New sections run after the existing ones. Existing sections, their conclusions and evidence levels are
  unchanged. Two consecutive live runs on the same commit gave identical conclusions, tables and DATA
  UNAVAILABLE items. The only differences were the retrieval times of the yfinance earnings dates, which are
  shown for information and marked not admissible at T_c.
- The frozen stage 3 inputs (signal, indicators, SEC tags, weights) are not touched.

### What exists now

**Structure.** The report follows the mission's 22 parts:
- Fixed rules in `report.part_of` tag each table, conclusion and DATA UNAVAILABLE item with its part.
- A structure table gives, per part, the counts of tables, conclusions and unavailable items, with the status
  covered / DATA UNAVAILABLE / empty.
- The appendix keeps the method notes and questions Q12 to Q14.

**Status.**
- The report is INCOMPLETE when a critical section (market, sec_events, valuation, macro, risks, quant,
  synthesis) fails or is missing.
- The status and its reason are shown in the HTML, the JSON and the manifest. `python main.py weekly` then
  exits with 3 and the daily run reports the step as failed.
- A failed non-critical section is listed but keeps the status COMPLETE.

**Regime** (part 3; rules regime-v1-2026-10-12, conventions that are not validated, an interpretation):
- SPY trend rule.
- VIX percentile over 756 observations.
- High-yield spread change over 63 observations (±0.50 pp).
- 10y−2y curve sign.
- 10y TIPS yield change over 21 observations (±0.25 pp).

**Data quality** (part 20):
- Downloads logged in (T_p, T_c] per source.
- The pipeline audit, used as evidence only when computed at or before T_c.
- DATA UNAVAILABLE items and failed sections, per section of the same report.

**Prediction history and performance** (part 21), all read as known at T_c:
- Predictions and outcomes from the journal.
- PT1 marks: equity, return, drawdown, benchmarks, stops, costs.
- PT1 portfolio risk at the latest mark (part 18): volatility, downside deviation, beta, correlations, largest
  position and sector, days to exit. No global risk score.
- The heuristic evaluation, kept apart from the prospective figures.
- Nothing in this part is a test.

**Synthesis** (parts 1, 19 and 22; rules synthesis-v1-2026-10-12):
- Per asset: readings for fundamentals, valuation, technical, macro, sentiment (facts only), quant and risk.
  Any of them may be unknown; unknown is never filled.
- Agreement or conflict between the directional pillars, stated as a hypothesis that has not been tested.
- The 13 questions of the mission, each answered from the report with its part.
- Bull, base and bear conditions using the report's own DCF figures with their reliability and the reverse-DCF
  growth. No probability is given.
- An executive summary and the key uncertainties.

### Tests and live results
- Tests: 557 passed.
- Live run on the cloud database, cutoff 2026-10-10T05:00Z (week ending 2026-10-09), clean commit:
  - Status COMPLETE: 105 strongly supported conclusions, 188 uncertain, 71 DATA UNAVAILABLE.
  - Parts 1 to 20 and 22 are covered. Part 21 is DATA UNAVAILABLE, which is correct at this cutoff: the
    journals and PT1 started on 2026-10-12, and the heuristic evaluation was computed after the cutoff.
  - Regime: trend up; VIX normal (37th percentile); credit stable (+0.46 pp over 63 observations); curve
    positive (0.44 pp); real yield rising (+0.41 pp over 21 observations).
  - Synthesis example: CRWD pillars agree (fundamentals +, technical +, quant no direction).
    - The DCF base case is 26.42 USD per share, with reliability LOW.
    - The close is consistent with a starting growth of 158.8% under the same rates. The scenarios are shown
      as conditions, not price targets.
- The PT1 risk table was checked on real prices with a hypothetical mark held in memory only. This was a
  runtime check, not published.

### Remaining after P5
- Part 21 fills only once the journals and PT1 have entries known at a report cutoff. That is the report for
  the week ending 2026-10-16 (outcomes need 5 or 20 sessions).
- The dashboard does not show the 22-part structure or the PT1 risk table; the weekly report is the reference.
- Regime and synthesis rules are conventions that have not been validated. Changing them requires a new
  version label, never a silent edit.
