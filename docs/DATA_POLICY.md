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
| **Data reliability** | Coverage of sources (`coverage`, `data_availability`), freshness, source rank | Coverage implemented (P0.1); freshness / source rank in P0.2 |
| **Signal strength** | Heuristic 0-100 score (`combined_score`) and `signal_agreement` (dispersion of sources) | Heuristic, weights not validated |
| **Prediction probability** | P(up) from a model trained and calibrated out-of-sample | Not available until P1.6 |
| **Prediction confidence** | Calibration quality and effective sample size of the model | Not available until P1.5 |
| **Risk score** | Output of the risk engine | Not available until P3.1 |

`historical_up_frequency_pct` (module `prediction_engine`) is an unconditional historical
base rate. It is **not** a P(up) prediction.

## Configuration

Secrets go in `.env` (see `.env.example`): `SEC_USER_AGENT`, `FRED_API_KEY`, `NEWSAPI_KEY`.
