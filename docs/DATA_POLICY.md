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
| `INSUFFICIENT DATA` | Signal not produced: fewer than 2 of 3 component scores available |

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

**Source rank** (lower = more authoritative): SEC EDGAR 1, FRED 1, yfinance 2, NewsAPI 3.
**Freshness**: `FRESH` if the age of `as_of_date` (publication date for filings) is within the cadence
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

## Configuration

Secrets go in `.env` (see `.env.example`): `SEC_USER_AGENT`, `FRED_API_KEY`, `NEWSAPI_KEY`.
Paste raw values only: a placeholder-shaped value such as `<abc123>` is rejected as `DATA UNAVAILABLE`.
API keys are never written to logs, the database, raw payloads or reports (`common.redact`).
