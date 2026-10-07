# Changelog

## P1.6 — Fixes from the weekly-report scouting critic

- **News component had a hidden neutral 50**: articles without any lexicon word scored exactly 50
  (56–86 % of real articles), pulling every average to ~50. Now such articles carry no sentiment;
  the score averages scored articles only; none scored → DATA UNAVAILABLE. Fixed 7-day window
  (`from`), coverage = returned / totalResults with a partial-coverage flag, status PROVISIONAL
  (naive lexicon, never validated).
- **Joint Form 4 filers** (a fund and its affiliates on one filing) counted as several insiders in
  the live tracker; now one insider per filing (primary reporting owner), as in the research code.
- **Validation statement** now says that the walk-forward tested the signal WITHOUT news, that the
  live signal's news component has never been validated, and cites the research stages from their
  results files. `walk_forward.latest_summary(now=)` evaluates at a given instant (a run computed
  after it is not visible).
- **DATA_POLICY**: 4 components, walk-forward universe, S&P list rank 3, weekly cadence (14 days),
  and the evidence levels STRONGLY SUPPORTED / UNCERTAIN / DATA UNAVAILABLE used by the weekly report.
- Tests: `tests/test_p16_news_insider_fixes.py` (6). Total 215.

## P2.1 — Expanded predictive-edge study, stage 1 (148 stocks, 2017-09 → 2026-09)

**Framework** (`src/research/`, `python main.py research --stage 1`): S&P 500 universe excl.
Financials / Real Estate (third-party list, provenance logged), seeded sample of 150, membership
from date added, one listing per company; point-in-time panel (prices, SEC XBRL replayed by
acceptance time, market cap with split unit conversion); 31 features in 6 groups with expected
sign and literature basis fixed in `factors.py` before any result; Newey-West IC tests,
Benjamini-Hochberg and Bonferroni corrections per family; non-overlapping quintile portfolios net
of 10 bp (turnover, Sharpe, Sortino, max drawdown, SPY and equal-weight benchmarks); strict
walk-forward logistic / L2 logistic / random forest (yearly folds, purged, ≥ 3 years history,
fixed hyperparameters); gradient boosting gated on a significant simpler model.

**Result** (full tables: `docs/research/STAGE1_RESULTS.md`): 58,348 stock-dates, 457 weekly dates,
205 tests. **0 significant after BH or Bonferroni.** Only 3 of 155 feature tests have uncorrected
p < 0.05, fewer than the ~7.8 expected by chance alone. Largest: accruals at 252d (IC +0.054 in the
expected direction, t = 2.87, p = 0.004, q = 0.63). Group composites: |t| ≤ 1.73; market structure
(low beta / low vol / small size) and value ran opposite to the literature (not significant).
Models out-of-sample 2021-2026: IC −0.044 … +0.019, |t| ≤ 1.26, AUC 0.47–0.51; L/S net Sharpe
−0.19 … 0.47 with 24–40 % drawdowns. Gradient boosting not run (not justified). Excluded: PSKY
(Yahoo returns 7 sessions in 10 years), Q (237 sessions, recent listing).

**Limits**: survivorship (current members only), current GICS sectors, 252-session portfolios have
9 periods, insider / macro / events / analyst revisions not in stage 1.

## P1.5 — Debt / equity XBRL mapping fixed

**Diagnosis** (40 tickers, 720 quarterly point-in-time checks 2022-05 → 2026-09): debt-to-equity
was missing in 33 % of walk-forward samples because the parser knew 3 debt concepts and one
equity concept, and only looked at the latest equity date. Real filers use others:
`LongTermNotesAndLoans` + `NotesPayableCurrent` (ORCL), `DebtLongtermAndShorttermCombinedAmount`
(GE, AMD), `LongTermDebtAndCapitalLeaseObligations` (HD, NUE, MU), `ConvertibleLongTermNotesPayable`
(DDOG), equity only including noncontrolling interests (CAT), debt tagged only in the 10-K (CAT, CVX).

**Fix** (`src/sec_xbrl.py`): 6 documented debt definitions in priority order, each stating how its
current portion is found and whether short-term borrowings are added (first of ShortTermBorrowings
/ CommercialPaper, never both; never on top of DebtCurrent, which includes them). Checked against
reported totals (ORCL 2024-05-31: 76.26 + 10.61 = 86.87 B combined; GE 2023-09-30: 19.49 + 1.33 =
20.82 B). Finance-lease-inclusive definition flagged (`debt_includes_finance_leases`). Equity falls
back to equity incl. NCI (flagged). D/E uses the latest date where both debt and equity are
reported (≤ 400 days before the latest equity date); outputs `balance_sheet_date`,
`latest_equity_date`, `debt_definition`, `equity_tag`.

**Result**: missing 33 % → 10.7 % (77 / 720). Every remaining gap is genuine and stays
DATA UNAVAILABLE (no estimate): negative equity, ratio not meaningful (BA 2022-25, ORCL 2022-23,
HD 2022); no debt concept because the company had no debt (ISRG; META before its first bond in
2022-08; PANW after its convertibles were retired); debt only in company-specific extension tags
absent from SEC company facts (DE; XOM except 2 dates). XOM revenue is also unavailable (only 4
standard revenue facts, no annual value).

**Tests**: `tests/test_p15_debt_mapping.py` (8). Total 177.

**Pipeline audit** (`python main.py audit`, `src/pipeline_audit.py`, `reports/pipeline_audit.json`):
PASS / WARN / FAIL checks on storage (publication after retrieval, raw SHA-256 sample, secrets),
prices (non-positive, gaps, |move| > 40 %, staleness), SEC (no look-ahead around the latest
10-K/10-Q acceptance, TTM vs 4 reported quarters, D/E reasons), Form 4 (unparsed documents,
P/S without price) and walk-forward timing. Exit code 1 on any FAIL.
Run on the 40 tickers: **0 FAIL**, 396 PASS, 8 WARN, all explained — MP +50.6 % on
2025-07-10 is a real move; 29 of 3,601 stored P/S transactions have their price only in a
footnote (value left unknown, so USD totals of LMT / CAT are understated); DE / ISRG D/E and XOM
revenue are the genuine gaps above. Limitation: the TTM cross-check against four 3-month facts
was possible for 1 ticker only (Q4 is usually reported only within the annual figure).
Tests: `tests/test_p15_pipeline_audit.py` (4). Total 183.

## P1.4 — Signals relabelled: quantitative signals, not trade recommendations

- Labels BUY / HOLD / SELL → POSITIVE / NEUTRAL / NEGATIVE (direction of a heuristic score)
  in every active module (technical, fundamentals, insider, news, combined, backtest check,
  walk-forward classes). Combined output keys: `quantitative_signal`, `signal_strength`,
  `signal_summary` (formerly `signal`, `combined_score`, `recommendation`), plus `disclaimer`.
- New per-ticker blocks: `validation` (walk-forward evidence: cross-sectional IC of the combined
  score, two-sided p, Bonferroni over horizons, IC > 0, not stale), `data_reliability`
  (coverage, freshness, source rank per input), and `model_prediction`,
  `prediction_confidence`, `risk_score` = NOT IMPLEMENTED with their reason. No score is
  turned into a probability.
- Report: banner stating whether predictive power was demonstrated (currently NOT
  DEMONSTRATED: p = 0.43 at 5d and 20d, 40 tickers), "Quantitative assessment (not a trade
  recommendation)" table per ticker; dashboard and console summary use the same terms.
- Tests: `tests/test_p14_relabel.py` (7, incl. no trade words in HTML / dashboard). Total 168.

## P1.3 — Continuous features and walk-forward-fitted model

- `src/features.py`: 12 point-in-time features (momentum 1/3/6/12-1 months, 3-month
  volatility, distance to 1-year high, revenue growth, log revenue, debt/equity, insider
  buyers, open-market and discretionary sale values). Missing stays `None`.
- `src/model.py`: ridge regression of cross-sectional return ranks on feature ranks; missing
  feature = median rank (contributes nothing); penalty fixed a priori. Refitted for each
  half-year fold on samples whose outcome was known before the fold (purged); scored
  out-of-sample with the cross-sectional IC and the top-minus-bottom quintile spread.
- Walk-forward output adds per-feature IC and the model; the daily report shows the model's
  out-of-sample IC. Tests: `tests/test_p13_model.py` (10, incl. no leakage of test-fold
  outcomes, recovery of a planted signal, no signal found in noise). Total 160.

**Results, 40 tickers, 8,800 weekly samples (2022-05 → 2026-09; model tested 2023-07 → 2026-09)**
- No feature has a significant cross-sectional IC (largest: 3-month volatility 0.059 at 20d,
  t = 1.44).
- Fitted model out-of-sample IC: −0.0002 (5d), −0.0045 (20d); positive in 3–4 of 7 folds.
  Fixed heuristic on the same dates: 0.016 / 0.030 (t ≤ 1.0). Neither has demonstrated skill.
- Heuristic BUY vs always long: +0.15 pp (5d), +0.45 pp (20d), not significant; no SELL issued.
- Debt/equity is missing for 33 % of samples (debt tags not reported in the recognised form).

## P1.2b — Wider validation universe

- `scheduler_config.json` → `validation_universe` (40 US domestic filers across software,
  semis, internet, industrials, materials, consumer, healthcare, energy; financials and REITs
  excluded) used by `python main.py walkforward`; the daily `stocks` list is unchanged.
  Tickers can also be passed on the command line. Chosen in 2026: selection / survivorship bias.
- Cross-sectional IC: Spearman across tickers on each date (≥ 10 tickers), averaged over dates
  with a t statistic from the dispersion of daily ICs (overlap-adjusted).
- SEC requests: one process-wide rate limiter (≤ 9 req/s); `SECParser.prefetch()` downloads
  Form 4 documents with 4 threads under it, storage and parsing stay single-threaded.
- One failing ticker is reported (`DATA UNAVAILABLE` + reason) and the run continues.
- Tests: 4 more in `tests/test_p12_walk_forward.py`. Total 148.

## P1.2 — Walk-forward validation (point-in-time, out-of-sample)

**New command** `python main.py walkforward` (`src/walk_forward.py`), results in
`reports/walk_forward.json`; the daily report shows a summary (stale after 7 days).
- Every 5 sessions over 5 years of prices (after 150 sessions of history), the signal is
  rebuilt as it would have been at that session's close: technical from closes up to T,
  fundamentals from XBRL facts accepted by T, insider from Form 4 filed in (T − 90 d, T].
  News is excluded (NewsAPI has no history). Insider is `None` (not "no trade") when the
  window is not covered by the downloaded filing history or contains an unreadable filing.
- Outcome: close T+1 → close T+1+H (H = 5, 20 sessions): the decision is made after T's close.
- Metrics: rank IC (Spearman) per component, pooled and per ticker, with an overlap-adjusted
  t statistic; combined-signal classes vs always-long; IC per calendar half-year fold.
- Nothing is fitted (fixed heuristics), so every date is out-of-sample.
- `PriceTechnical.score_closes()` and `ScoringFundamentals.score_inputs()` extracted so the
  production scoring is reused unchanged; SEC feed truncation (`coverage_start`) recorded.

**First result (2022-05 → 2026-09, 4 tickers, 880 dates)**: no component has a significant IC
(all |t| < 1): combined 0.004 (5d) / 0.031 (20d), insider slightly negative, combined IC > 0 in
4–5 of 10 folds. The heuristic signal has no demonstrated ranking skill yet.

**Performance**: first run ≈ 5.5 min (≈1,500 Form 4 documents downloaded once), then ≈ 45 s.

**Tests**: `tests/test_p12_walk_forward.py` (11 tests, offline) including a no-look-ahead test
(rewriting future prices leaves earlier scores unchanged). Total 144 tests.

## P0.3 — SEC XBRL fundamentals and Form 4 insider transactions

**Fundamentals (`src/sec_xbrl.py`, `SECParser.fundamentals`)**
- Source: SEC XBRL company facts (`data.sec.gov/api/xbrl/companyfacts`), 10-K / 10-Q facts in USD.
  Each fact is an observation (`xbrl:<Tag>` for balance-sheet values, `xbrl:<Tag>:<m>M` for
  3/6/9/12-month periods, period start in `value_text`) published at the filing's acceptance
  time (accession matched in the submissions feed), else the end of the `filed` date.
- Revenue TTM = 12M fact, else FY + YTD − prior-year YTD (tags never mixed); growth = TTM vs
  TTM one year earlier; debt = first reported definition (`LongTermDebt`, else
  `LongTermDebtNoncurrent` + current portion, else convertible debt), leases excluded;
  D/E unavailable when equity ≤ 0 or no debt tag is reported (never 0).
- Point-in-time: `fundamentals(known_at=T)` uses only facts public at T; restatements are new
  versions. Fundamental score has 3 components (revenue scale, revenue growth, leverage).

**Insider (`src/insider_tracker.py`)**
- Form 4 XML documents of the last 90 days parsed (owners, Rule 10b5-1 box, non-derivative
  transactions), each transaction stored as an event `form4:transaction` with the filing's
  acceptance time. Only open-market purchases (P) and sales (S) are scored; 10b5-1 planned
  sales are neutral. Heuristic score (60–90 for buys by 1–4+ insiders, 45 / 35 for
  discretionary sales by 1–2 / ≥3 insiders, else 50). Partial document failures →
  `PROVISIONAL`; all failed or SEC unreachable → `DATA UNAVAILABLE`.

**Combined signal**: insider is a 4th component (technical 0.25, fundamentals 0.40, news 0.20,
insider 0.15); coverage is now reported out of 4.

**Efficiency**: `Database.latest_fetch()` lets SEC documents be reused: ticker file 24 h,
company facts 12 h, Form 4 XML forever (immutable). A reused document keeps its original
fetch (and retrieval time) in the provenance. Second run of the day ≈ 2× faster.

**Report**: TTM revenue, growth, D/E with balance-sheet date; new "Insider activity" section;
Insider column in the summary.

**Tests**: `tests/test_p03_sec_fundamentals_insider.py` (21 tests, offline). Total 131 tests.

**Not changed in P0.3**: Form 4/A amendments and derivative transactions are not used;
other XBRL metrics (margins, cash flow) and vintage-consistent transforms are P0.4+.

## P0.2 — Provenance layer (database.py)

**Schema v2, single owner (`src/database.py`)**
- `source_fetches`: one row per call to a source (success or failure): endpoint and parameters
  with secrets removed, request / completion time (UTC), status, HTTP code, redacted error,
  record count, raw payload path, SHA-256 and size.
- `observations`: one row per value version: entity, metric, `as_of_date` (period the value
  refers to), `published_at` (when it became public at the source) + `published_at_basis`,
  `retrieved_at`, `fetch_id`, `source` + `source_rank`, `value_revisable`. Re-ingesting an
  identical value adds nothing; a revised value is stored as a new version (history never
  overwritten). Enforced: `published_at <= retrieved_at`.
- `backtest_results` rebuilt with `outcome_date` (session resolving the outcome),
  `price_fetch_id`, `method`, `computed_at`; enforced `signal_date < outcome_date`.
- Point-in-time access: `series()`, `get_point_in_time()`, `events()` only return values
  available at `known_at` (`COALESCE(published_at, retrieved_at) <= known_at`);
  `strict_vintage=True` also requires the stored version to have been retrieved by then.
- Freshness (`FRESH` / `STALE` / `UNKNOWN`) per update cadence, fixed source ranks
  (SEC, FRED = 1; yfinance = 2; NewsAPI = 3), conflicts between sources reported.

**Migration** (automatic on first run): the database is copied with the SQLite backup API and
every table exported to JSON in `data/backups/` (row counts verified) **before** the legacy
tables `sec_data`, `macro_data`, `backtest_results`, `backtest_fixed`, `insider_transactions`
(and the unused `fundamentals`, `prices`, `calendar_events`, `macro_indicators`) are dropped:
their publication times cannot be established and some carried invented `confidence` values.
They are refilled from the real sources by the next run. Unknown tables are left untouched.

**Raw payloads**: `data/raw/<source>/<sha[:2]>/<sha256>.<ext>.gz` (content-addressed, deduplicated,
SHA-256 checked on read). Secrets are redacted before writing and a payload still containing a
key is refused. `data/` is excluded from git.

**Sources**
- SEC: every filing of the submissions feed stored as an event (`filing:<form>`, accession number)
  timestamped from `acceptanceDateTime`. That field is labelled UTC but is inconsistent with
  `filingDate` on real data in both readings; it is read as New York time, which is never earlier
  than the UTC reading (conservative). The 90-day Form 4 count is computed point-in-time.
  The `sec_data` cache is removed.
- FRED: all vintages requested (`realtime_start` = window start), stored with
  `published_at` = end of the vintage day (New York, conservative). Displayed values use the
  current vintage; earlier releases remain queryable (61 revised values kept on the first run).
- yfinance: new `src/market_data.PriceFeed`, one download per ticker and run shared by the
  technical, backtest and base-rate modules (previously 3 separate downloads, nothing stored).
  Sessions whose close (21:00 UTC) is after retrieval are dropped (no intraday price used as a close).
  Adjusted prices are flagged `value_revisable` (Yahoo rewrites history after splits / dividends).
- NewsAPI: each article stored as an event with its `publishedAt`.
- Module outputs carry a `provenance` block; the HTML report has a "Data provenance" table.

**Secrets**
- FRED errors used to include the request URL, i.e. the API key, in the console and in
  `reports/analysis.*`. Errors now carry FRED's own message only; `redact()` masks keys in every
  reason, error, fetch log, raw payload and report.
- `secret_env()` rejects placeholder values such as `<key>` with an explicit reason (this was the
  cause of FRED HTTP 400 / NewsAPI HTTP 401) instead of calling the API.

**Tests**: `tests/test_p02_provenance.py` (35 tests, offline): migration + backup, constraints,
raw storage without secrets, point-in-time / no look-ahead, versioning, events, source rank,
freshness, SEC / FRED / NewsAPI / prices provenance, end-to-end report. Total 108 tests.

**Not changed in P0.2**: legacy modules not used by the pipeline (`backtester_fixed.py`,
`scoring_signal.py`, `scoring_confidence.py`, `scoring_reliability.py`) still reference the old
tables; vintage-consistent transforms (e.g. YoY as known at a past date) and anti-leakage tests
of the full pipeline are P0.4; XBRL / Form 4 transactions are P0.3.

## P0.1 — Remove invented data, explicit unavailability, runnable pipeline

**Removed invented or misleading values**
- `sec_parser`: hardcoded revenue and debt-to-equity removed (were presented as "SEC EDGAR, confidence 95").
  Previously cached invented values are purged from `sec_data`. Revenue / D/E are `DATA UNAVAILABLE` until P0.3.
- `sec_parser`: CIKs resolved from the official SEC ticker file (the hardcoded table pointed to wrong companies);
  `SEC_USER_AGENT` required; failures return `None` instead of `0`; cache expiry fixed.
- `insider_tracker`: always-NEUTRAL placeholder replaced by `DATA UNAVAILABLE`.
- `dashboard`: hardcoded recommendations, alerts and performance metrics removed; renders run results only.
- `integration`: fake walk-forward ("Data leakage: PREVENTED", `no_leakage`) removed -> `NOT IMPLEMENTED` (P1.2).
- `prediction_engine`: outputs relabelled as unconditional historical base rates (`is_model_prediction: false`);
  mean return now averages all returns (was: positive returns only); sample sizes and insufficient-sample flags added.
- `backtester`: invalid Sharpe / drawdown / total P&L / "win rate" removed; accuracy shown next to the
  majority-class baseline; status `PROVISIONAL` until P1.1.
- `macro_fred`: CPI shown as YoY % (was the raw index level shown as "310% inflation"); FRED REST API
  replaces `pandas_datareader` (broken on Python 3.12+); `FRED_API_KEY` required.

**Missing data handling**
- Technical, news and fundamental scores return `None` (not 50 / HOLD) when data is missing.
- Combined signal uses available components only (weights renormalized), requires 2/3 components,
  reports `coverage` and missing components; otherwise `INSUFFICIENT DATA`.
- News: zero articles or missing key -> unavailable; query uses company name (not "NET"/"MP");
  whole-word sentiment matching; publication date range reported.

**Robustness**
- `src/common.py`: shared status constants, paths (`data/`, `reports/` created automatically), config, UTC timestamps.
- Tickers read from `scheduler_config.json`; every module failure becomes an explicit unavailable payload.
- yfinance MultiIndex columns handled; `earnings_nlp.py` repaired (did not compile).
- `report_generator`: no crash on missing values, data-availability table, HTML escaping.
- `requirements.txt` updated for Python 3.10+; `.env.example` added.

**Tests**: `tests/` (pytest, fully offline, network blocked): 74 tests.
Run with `python -m pytest`.

**Not changed in P0.1** (planned): database schema / provenance (P0.2), XBRL + Form 4 parsing (P0.3),
point-in-time access and anti-leakage tests (P0.4), backtest / models (P1).
