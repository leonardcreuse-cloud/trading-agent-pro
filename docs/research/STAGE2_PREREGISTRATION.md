# Stage 2 pre-registration — holdout replication

Written after stage 1 (`docs/research/STAGE1_RESULTS.md`) and **before any stage 2 data was
downloaded or analysed**. The git commit that adds this file is the timestamp of the
pre-registration; the hypotheses are also fixed in code (`src/research/factors.py`:
`INSIDER_FEATURES`, `CONFIRMATORY`).

## Sample

- **Holdout universe**: every eligible stock (current S&P 500 members excluding Financials and
  Real Estate, one listing per company) that was **not** in the stage 1 seeded sample: 244 stocks.
  No stage 1 stock is used in the confirmatory tests.
- Same period (2017-09 → 2026-09), same weekly dates, same point-in-time rules, same costs.
  The holdout is cross-sectional: the stocks are new, the years are not. Market-wide regimes are
  therefore shared with stage 1; a time-out-of-sample check needs data after 2026-10-07
  (stage 3, prospective).

## Confirmatory hypotheses (family of 4, Holm-Bonferroni, α = 0.05)

A hypothesis is **confirmed** only if its mean daily rank IC is in the stated direction and its
Holm-adjusted two-sided p-value (Newey-West t, lag = ceil(H / 5) − 1) is below 0.05.

| ID | Feature | Expected sign | Horizon | Why it is in the family |
|---|---|---|---|---|
| C1 | accruals | − (low accruals → higher returns) | 252 sessions | stage 1: IC +0.054 in the expected direction, t = 2.87, p = 0.004 (q = 0.63); Sloan (1996) |
| C2 | accruals | − | 120 sessions | stage 1: IC +0.037, t = 2.05, p = 0.041; Sloan (1996) |
| C3 | insider_net_buy_to_mcap | + | 120 sessions | not testable in stage 1; Lakonishok & Lee (2001), Cohen, Malloy & Pomorski (2012) |
| C4 | insider_net_buy_to_mcap | + | 252 sessions | idem |

Selection rule used for C1–C2: every stage 1 feature test with uncorrected p < 0.05 **in the
pre-registered direction**. Excluded by that rule: asset_growth at 5 sessions (p = 0.014, but
opposite to the literature — reversing its sign after seeing the data would be data mining).

## Insider features (new in stage 2, fixed now)

Window: Form 4 filings accepted in (T − 90 days, T]; open-market transactions only (codes P and S);
sales on filings that tick the Rule 10b5-1 box are "planned", other sales "discretionary".

| Feature | Definition | Expected sign |
|---|---|---|
| insider_buyers_90d | distinct insiders with open-market purchases | + |
| insider_net_buy_to_mcap | (purchase value − discretionary sale value) / market cap at T | + |
| insider_disc_sellers_90d | distinct insiders with discretionary sales | − |

Unavailable (None, never 0) when the window is not fully covered by the downloaded filing
history (submissions feed incl. its older files, from 2016-06-01) or contains a Form 4 that could
not be read, or when the market cap is unavailable (for the ratio).

## Secondary (exploratory, not confirmatory)

The full stage 1 battery on the holdout, plus the insider group: every feature × horizon,
every group composite, and the walk-forward models, with Benjamini-Hochberg and Bonferroni
within each family. These results are reported but **cannot confirm** anything.

## Decision rule

- Any confirmatory hypothesis confirmed → report it as a replicated, out-of-sample effect, with its
  effect size, portfolio metrics net of costs and limitations; it still needs the prospective
  stage 3 before being used in the weekly report's quantitative section.
- None confirmed → the study concludes that no statistically reliable predictive edge was found in
  these data, and the quantitative section keeps the "not demonstrated" label.
- No hypothesis, horizon, feature definition, cost or sample rule will be changed after stage 2
  data is seen. Any later change is a new, separately labelled exploratory analysis.

## Amendment 1 — before any stage 2 analysis (implementation of "distinct insiders")

Found while smoke-testing the Form 4 loader on two companies, before any holdout outcome was
computed: a single Form 4 jointly filed by a fund and its affiliated entities (8 reporting owners
for one $99.8 M purchase) was counted as 8 "distinct insiders". A joint filing is one economic
decision, so **each filing counts as one insider, identified by its primary (first) reporting
owner (CIK when present)**. Transaction values were already counted once and are unchanged. No
hypothesis, horizon, sign, window or threshold changes.
