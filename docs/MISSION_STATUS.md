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
