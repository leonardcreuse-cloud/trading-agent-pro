# Changelog

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
