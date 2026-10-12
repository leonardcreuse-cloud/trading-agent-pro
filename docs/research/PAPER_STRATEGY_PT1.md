# Paper strategy PT1 — pre-registration (paper only, no real orders)

Written on 2026-10-12, before any paper order. The git commit that adds this file timestamps the rules; the code
(`src/paper.py`, `src/risk.py`, `src/journal.py`) implements them and the settings are in `scheduler_config.json`
(`risk`, `paper`). **No broker is connected and no real order can be sent**: the simulator only writes to its
journals.

## Why, and what to expect

The descriptive evaluation of the heuristic on the walk-forward sample (`docs/research/HEURISTIC_EVALUATION.md`)
found that its top quintile did **worse** than the equal-weight universe after costs (about -2.9% a year at 5
sessions) and that its ranking AUC was about 0.51. The prior expectation is therefore **no edge**. PT1 exists to
measure, prospectively and net of realistic costs, what an implementable version of the system's own signal does,
and to exercise the risk engine, the journals and the execution simulator. Its result alone can never justify
real money (out of scope of the mission); the statistical test of the signal is the pre-registered stage 3.

## Rules (frozen)

| Item | Rule |
|---|---|
| Universe | the 40 tickers of stage 3 (`src/prospective.py` UNIVERSE) |
| Signal | the stage 3 weekly record: ex-news combined score at the close of s0; only records valid by the stage 3 rules (ledger, generated before the open of s1) |
| Selection | top quintile = the 8 highest combined scores among the scored tickers (at least 10 scored, else no rebalance that week); ties by ticker name |
| Orders | written to the journal when the record is used, before the open of s1; market-on-open orders for the first session whose open (13:30 UTC at the earliest) is after the order time |
| Entry price | as-traded (split-adjusted) open of that session x (1 + slippage + half-spread), plus commission |
| Size | risk engine: 1% of equity at risk to the stop (hard limit 2%), at most 20% of equity per position, at most 1% of the 20-session average volume, sectors (SEC SIC major group) at most 40%, gross exposure at most 100%, cash only (no leverage, no shorting) |
| Stop | entry - 2 x ATR14 (Wilder, as-traded bars up to s0); checked on every session's low; a stop hit exits at min(open, stop) x (1 - slippage - half-spread) (a gap through the stop fills at the open: worse than the stop) |
| Exit | stop, or the name is no longer in the top quintile of a later valid record (sold at that record's s1 open) |
| Holding | kept while in the top quintile; not resized |
| Costs | commission 1 bp, slippage 5 bps, half-spread 2 bps, each side (assumptions, `risk` settings) |
| Corporate actions | dividends credited in cash on the ex-date for shares held at the previous close; splits adjust shares, stop and cost basis on the split date (yfinance actions, rank 2) |
| Capital | 100,000 USD paper |
| Benchmarks | SPY total return (adjusted closes) and the equal-weight 40-ticker universe (adjusted closes, rebalanced at each s1) from the same start |

## Evaluation (after at least 52 weekly rebalances; interim figures are descriptive)

Net total and annualised return, volatility, Sharpe and Sortino (risk-free 0), maximum drawdown, turnover, total
costs, number of stops, and the differences with both benchmarks; weekly excess returns over the equal-weight
universe with a t-statistic (secondary, descriptive: the confirmatory test of the signal is stage 3). The
backtest-style descriptive figures and the prospective paper figures are always reported separately.

## Not allowed

Changing any rule, setting, universe or benchmark after the first paper order. A change starts a new strategy (PT2,
new pre-registration); journals of different strategies are never pooled. Real-money deployment would require, at a
minimum, 12 months of paper trading, credible out-of-sample evidence (stage 3) and the other controls of the
mission; it is not part of this work.

## Implementation deviation log (append-only)

**2026-10-12. Sector lookup bug (week 1).**
- **What happened.** The sector lookup in `src/paper.py` (`Paper._sector`) read a `sic` key at the top level of the
  SEC submissions result. The code is actually in `get_filings(...)['raw']['sic']`, so every ticker came back
  `unknown`. All 8 names were pooled into a single "sector" capped at 40%.
- **Effect on the first rebalance** (orders of the 2026-10-09 record, filled at the 2026-10-12 open):
  - 3 orders filled: XOM, NVDA, UBER;
  - 5 orders rejected with "sector unknown already at 40.0% of equity";
  - about 60% of equity left in cash.
- **What was not changed.**
  - The frozen rule is still "sectors (SEC SIC major group) at most 40%".
  - The journals are append-only and stay as written: week 1 is not replayed or corrected. Its under-investment is
    part of the PT1 record and is reported as is.
- **Correction (code only).**
  - `_sector` now reads the SIC code where the feed holds it.
  - A ticker whose SIC cannot be read is its own group (`unknown <ticker>`), never pooled with others.
  - Checked against the live SEC feed: XOM 29, NVDA 36, AMD 36, UBER 73, GOOGL 73, MSFT 73, COST 53, ISRG 38.
  - Test: `tests/test_p77_paper_sector.py`.
- **When it applies.** From the next valid stage 3 record onwards.
- **Classification.** A bug fix that makes the code follow the pre-registered rule, not a rule change. The owner may
  instead decide to close PT1 and start PT2. That decision is recorded here if taken.
