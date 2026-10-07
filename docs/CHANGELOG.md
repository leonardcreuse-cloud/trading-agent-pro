# Changelog

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
