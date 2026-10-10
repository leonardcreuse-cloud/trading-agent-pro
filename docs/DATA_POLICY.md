# Data policy and metric definitions

## Absolute rule: no invented data

No price, financial value, macro figure, event, sentiment, probability or performance
number may be invented, mocked or simulated in an analysis output.

- Missing value: `None` in code, `DATA UNAVAILABLE` as status, `N/A — source unavailable` in reports.
- A failed source is reported with its reason (`reason`, `error`), never replaced silently.
- Never fall back to a "neutral" number (e.g. 50) when an input is missing.
- Synthetic data is allowed only inside `tests/` to check calculation logic.

## Status vocabulary (module outputs)

| Status | Meaning |
|---|---|
| `OK` | Value computed from data actually retrieved |
| `PROVISIONAL` | Computed from real data, but the methodology is known to be incomplete (see `warning`) |
| `DATA UNAVAILABLE` | Source unreachable, key missing, or data not ingested yet (see `reason`) |
| `NOT IMPLEMENTED` | Feature does not exist yet; nothing is computed |
| `INSUFFICIENT DATA` | Signal not produced: fewer than 2 of the 4 component scores (technical, fundamentals, news, insider) available |

## Quantitative signal terminology (P1.4)

Outputs are **quantitative signals**, never trade recommendations. POSITIVE / NEUTRAL / NEGATIVE
describe the direction of a heuristic score (thresholds 65 / 40). `validation.status` is
`DEMONSTRATED` only when the walk-forward cross-sectional IC of the combined score is positive and
significant (two-sided p < 0.05 / number of horizons) in a run less than 7 days old; otherwise
`NOT DEMONSTRATED` (or `NOT VALIDATED` when no run exists), and the report says so. The live signal
includes news (weight 0.20), which the walk-forward cannot evaluate: the live signal itself is therefore
never "validated", only its ex-news variant is tested.

## Evidence levels for conclusions (weekly report, P3.0)

Every conclusion in the weekly report carries exactly one level, decided by these rules (the weakest
necessary premise decides; weak premises never add up to a strong conclusion):

| Level | Rule |
|---|---|
| `STRONGLY SUPPORTED` | Admissible at the cutoff (published before it, correct vintage), fresh at the cutoff, no unresolved conflict, and one of: (a) a rank-1 source authoritative for that fact type (SEC filings and XBRL facts, FRED official series and release dates); (b) at least two independent rank <= 2 sources agreeing; (c) a statement about the system's own deterministic output, reproducible from stored inputs. Change claims also need a change beyond the pre-declared threshold. |
| `UNCERTAIN` | Admissible evidence exists but: only rank-3 / aggregator sources (any number of copies); a single rank-2 source (e.g. yfinance prices) without a second source; stale or unknown freshness; a first print within revision noise; conflicting sources; partial coverage; an interpretation, estimate or heuristic threshold; any model output whose predictive power is not demonstrated. |
| `DATA UNAVAILABLE` | No admissible evidence; a reason is mandatory (blocked host, key missing, HTTP error, history limit, not ingested). Never listed as "uncertain" and never filled. |

Additional rules: timing is reported as "coincided with", never as a cause; a negative fact ("no 8-K this
week") needs a successful fetch made after the cutoff covering the whole window; freshness and staleness
are evaluated at the cutoff, never with the wall clock; independent sources must have different
originators (an issuer's press release and its 8-K are one originator; syndicated copies count once).

## Separate concepts (never mix them)

| Concept | Current definition | Status |
|---|---|---|
| **Data reliability** | Coverage of sources (`coverage`, `data_availability`), freshness, source rank | Coverage (P0.1); freshness and source rank (P0.2) |
| **Signal strength** | Heuristic 0-100 score (`combined_score`) and `signal_agreement` (dispersion of sources) | Heuristic, weights not validated |
| **Prediction probability** | P(up) from a model trained and calibrated out-of-sample | Not available until P1.6 |
| **Prediction confidence** | Calibration quality and effective sample size of the model | Not available until P1.5 |
| **Risk score** | Output of the risk engine | Not available until P3.1 |

`historical_up_frequency_pct` (module `prediction_engine`) is an unconditional historical
base rate. It is **not** a P(up) prediction.

## Provenance and time (P0.2)

Every stored value has a source, a fetch (`source_fetches`), a raw payload (`data/raw/`) and three times:

| Field | Meaning |
|---|---|
| `as_of_date` | Date / period the value refers to |
| `published_at` | When the value became public at the source; `NULL` if unknown |
| `retrieved_at` | When this version was obtained |

**No look-ahead**: a value may be used at instant T only if `COALESCE(published_at, retrieved_at) <= T`.
When in doubt, the later plausible time is used:

| Source | `published_at` |
|---|---|
| SEC EDGAR | `acceptanceDateTime` read as New York time (>= the feed's UTC label); else end of filing date |
| FRED | Vintage date (`realtime_start`), end of day New York |
| yfinance | Session date 21:00 UTC; adjusted prices are `value_revisable` (use `strict_vintage`) |
| NewsAPI | Article `publishedAt` |

A publication time later than retrieval is clamped to retrieval. Revised values are stored as new
versions; history is never overwritten. Unverifiable legacy data is not migrated: it is backed up
(`data/backups/`) and refilled from the sources.

**Source rank** (lower = more authoritative): SEC EDGAR 1, FRED 1, yfinance 2, NewsAPI 3, S&P 500 list (datasets/s-and-p-500-companies, third-party compilation) 3.
**Freshness**: `FRESH` if the age of `as_of_date` (publication date for filings) is within the cadence (weekly series: 14 days)
limit: market sessions 5 days, daily series 7, monthly series 80, 10-K/10-Q 120, news 7.

## SEC financials and insider activity (P0.3)

| Metric | Definition |
|---|---|
| Revenue TTM | 12-month fact, else FY + YTD − prior-year YTD, from one XBRL tag (see `sec_xbrl.py`) |
| Revenue growth | Revenue TTM / revenue TTM one year earlier − 1 |
| Debt | First reported definition: `LongTermDebt`; else non-current + current long-term debt; else convertible debt. Leases excluded |
| Debt / equity | Debt / `StockholdersEquity` at the same balance-sheet date; unavailable if equity ≤ 0 or no debt tag |
| Insider score | Heuristic 0–100 from open-market Form 4 purchases (P) and discretionary sales (S) over 90 days; 10b5-1 planned sales, grants, exercises and tax withholding are not scored |

An insider score of 50 is computed ("no informative transaction observed"); it is not a default:
when SEC or the Form 4 documents cannot be read, the score is `None`.

## Walk-forward validation (P1.2)

| Metric | Definition |
|---|---|
| Rank IC | Spearman correlation between a score at T and the return close T+1 → close T+1+H |
| n_effective | n × min(1, step / H): overlapping windows are not independent |
| t statistic | IC × √((n_eff − 2) / (1 − IC²)); `significant` when \|t\| ≥ 2 |
| Always long | Mean return and up-rate over all evaluation dates (baseline) |

Walk-forward results describe past ranking skill of the fixed heuristics on the validation universe (40 tickers in the latest run) **without the news component**, which has no history; they are
not a probability and do not include costs (full backtest: P1.1).

## Weekly report rules (P3.1)

These rules are applied by the weekly report sections (`src/weekly/sections/`). Thresholds live in
`scheduler_config.json` → `weekly.thresholds` (version `thresholds_version`); they are pre-declared
heuristics, never fitted, and every crossing carries the `HEURISTIC_THRESHOLD` reason code.

| Rule | Definition |
|---|---|
| Drawdown | drawdown vs the 252-session high at T_c <= `drawdown_new_low_pct` (−20 %) and deeper than at T_p |
| Volume | 5-session volume ratio at T_c >= `volume_ratio` (2.0) and higher than at T_p |
| Volatility | relative change of 20-session volatility between T_p and T_c >= `sigma20_change_rel` (0.25) |
| FRED stress rows | change > 1 sample standard deviation of Friday-to-Friday changes as known at T_p |
| Red flag | 8-K item 4.01, 4.02, 1.05, 3.01, 2.05 or 2.06, or an NT 10-K / NT 10-Q, accepted in (T_p, T_c] |
| Macro materiality | \|change\| at or above `macro_abs_change[series]`, compared with a tolerance of 1e-9 × max(1, threshold); a series without a threshold is reported as a fact, "materiality not assessed" — never compared with 0 |
| Revision noise | a change is beyond revision noise only if \|change\| > max(largest revision of the change, largest revision of the level) observed in the stored vintages (level revision in % of the first print for percent-change series); otherwise `FIRST_PRINT_WITHIN_REVISION_NOISE` |
| Historical vintages | an item "as known at T_p" has its freshness evaluated at T_p; a FRED revision is a publication event dated by its vintage date (cadence `event`, 14 days) |
| End-of-day series | for daily end-of-day FRED series, a version whose vintage date is earlier than its own observation date is not used, and snapshots stop at s_0 (T_c) and s_-5 (T_p) |
| Target range | "no change" covers effective dates after d_p up to the last date known at T_c; FRED dates changes by their effective date, so a decision announced on s_0 is not ruled out (`PARTIAL_COVERAGE`) |
| Geopolitical news | pre-declared topics `geo-topics-v1-2026-10-07`: sanctions, export controls, tariffs, armed conflict, elections, government shutdown; syndicated copies count once (canonical URL, normalized title, token-set Jaccard >= 0.6); news is always `UNCERTAIN` (aggregator) |

**Synthetic data**: synthetic values exist only inside `tests/` with the isolated data directory of
`tests/conftest.py`. Test helpers must never be imported to write into `data/` (it happened once, on
2026-10-07 and 2026-10-10: 43 synthetic fetch rows, deleted after a backup); `python main.py audit`
flags backdated fetch rows and FRED calls logged without their api_key parameter.

## Configuration

Secrets go in `.env` (see `.env.example`): `SEC_USER_AGENT`, `FRED_API_KEY`, `NEWSAPI_KEY`.
Paste raw values only: a placeholder-shaped value such as `<abc123>` is rejected as `DATA UNAVAILABLE`.
API keys are never written to logs, the database, raw payloads or reports (`common.redact`).
