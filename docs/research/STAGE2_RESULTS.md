# Research study — stage 2 results

Computed 2026-10-11T13:21:34+00:00. Generated from `reports/research_stage2.json` by `src/research/experiment.py`; the protocol is fixed in code before results.

## Conclusion

- Confirmatory family (Holm-Bonferroni over 4 pre-registered tests, alpha 0.05, IC in the expected direction (docs/research/STAGE2_PREREGISTRATION.md)): 0 of 4 confirmed.
- 170 feature tests, 40 group tests, 15 model tests (225 in total).
- After Benjamini-Hochberg correction (q < 0.05) within each family: 0 feature, 0 group and 0 model results are significant (0, 0, 0 in the pre-registered direction).
- After Bonferroni correction: 0 significant.
- No group composite or model shows a statistically reliable predictive edge after correction.

## Reading of the result (written after the run, nothing changed in the protocol)

- **Decision rule of the pre-registration applies: none of C1–C4 is confirmed, so the study concludes that
  no statistically reliable predictive edge was found in these data.** The quantitative section keeps the
  "not demonstrated" label.
- C1 / C2 (accruals, 252 / 120 sessions): the IC is in the expected direction but about half of stage 1
  (C1 +0.026 vs +0.054 in stage 1), t = 1.28 / 1.04, Holm p = 0.81 / 0.90. The stage 1 lead did not replicate
  on new stocks; the most likely reading is that part of the stage 1 effect was selection (it was chosen
  because it looked best among 205 tests).
- C3 / C4 (insider net open-market purchases / market cap, 120 / 252 sessions): IC slightly in the
  opposite direction (-0.010 / -0.009), not significant. Insider data covered 84,365 / 78,324 stock-dates
  (Form 4 history from 2016-06-01, 242 stocks, one parse failure in the whole download).
- Exploratory (cannot confirm anything): the lowest uncorrected p-value is log_market_cap at 252 sessions
  (IC +0.058, p = 0.008, BH q = 0.90): large caps did better over 2017-2026 in this sample, a known period
  effect, not a forecastable edge. Random forest at 252 sessions has a significantly NEGATIVE uncorrected IC
  (-0.076, t = -2.47), BH-insignificant. No model has a positive out-of-sample edge; gradient boosting was
  not run (not justified).
- Limitations: the holdout is cross-sectional (new stocks, same years); survivorship (current S&P 500
  members); current GICS sectors. SEC acceptance timestamps: between 2026-10-07 and 2026-10-10 the SEC
  submissions feed relabelled about 16 % of acceptanceDateTime values by +4 h / +5 h (the New York offset).
  The code reads every label as New York time, so for the stage 2 download (labels of 2026-10-10/11) those
  filings are dated 4-5 h later than their true acceptance: conservative (no look-ahead), possibly a slight
  loss of power for filings accepted within hours of a weekly date; stage 1 used the previous labels.
  This is recorded, not corrected (the protocol forbids changes after the data were seen).
- Next step that could still show an edge without data mining: a prospective record (stage 3) of
  pre-declared signals evaluated on returns realised after today.

## Sample

- Universe: current S&P 500 members excl. Financials and Real Estate, one listing per company; holdout: every eligible stock not in the stage 1 sample; stock included from its date added to the index.
- Stocks: 242 with data of 244 requested; median 196 stocks per date.
- Observations: 90,691 stock-dates on 458 weekly dates, 2017-09-06 → 2026-10-09 (every 5 sessions).
- Biases: survivorship: members removed before today are absent; GICS sector is the current classification.
- Excluded stocks: HONA (82 usable sessions), Q (240 usable sessions).
- Not testable (no free point-in-time data) or deferred: analyst_revisions: no free point-in-time history of estimates or price targets; guidance_changes: no free machine-readable guidance history; insider: stage 1 only: added in stage 2 (INSIDER_FEATURES); macro: time-series hypothesis: identical for all stocks on a date (separate design); events: deferred (earnings dates / 8-K items).

## Confirmatory tests (pre-registered)

Holm-Bonferroni over 4 pre-registered tests, alpha 0.05, IC in the expected direction (docs/research/STAGE2_PREREGISTRATION.md).

| ID | Feature | H | IC | t | p | p (Holm) | 95 % CI | Dates | Observations | Confirmed |
|---|---|---|---|---|---|---|---|---|---|---|
| C1 | accruals | 252 | +0.0262 | +1.28 | 0.2020 | 0.8080 | [-0.014064, 0.066519] | 407 | 73775 | no |
| C2 | accruals | 120 | +0.0200 | +1.04 | 0.2993 | 0.8980 | [-0.017744, 0.057684] | 433 | 79649 | no |
| C3 | insider_net_buy_to_mcap | 120 | -0.0098 | -0.43 | 0.6669 | 1.0000 | [-0.054269, 0.034724] | 433 | 84365 | no |
| C4 | insider_net_buy_to_mcap | 252 | -0.0094 | -0.32 | 0.7501 | 1.0000 | [-0.067181, 0.048401] | 407 | 78324 | no |

## Group composites (no fitting) — mean daily rank IC in the pre-registered direction

Newey-West t; q = Benjamini-Hochberg within the 40 group tests. Portfolio: top minus bottom quintile, rebalanced every H sessions, net of 10 bp per unit of turnover, risk-free rate 0.

| Group | H | IC | t | p | q (BH) | 95 % CI | L/S net ann. | L/S Sharpe | L/S Sortino | L/S max DD | Top-Q net ann. | Equal-weight ann. | SPY ann. | Turnover | Periods |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| momentum | 5 | +0.0112 | +0.98 | 0.328 | 0.988 | [-0.011, +0.034] | -8.623 % | -0.273 | -0.229 | -68.093 % | 14.762 % | 15.664 % | 15.28 % | 0.345 | 456 |
| momentum | 20 | +0.0002 | +0.01 | 0.988 | 0.988 | [-0.030, +0.030] | 0.19 % | 0.088 | 0.093 | -38.71 % | 17.198 % | 15.016 % | 15.28 % | 0.685 | 114 |
| momentum | 60 | -0.0066 | -0.32 | 0.746 | 0.988 | [-0.046, +0.033] | -1.952 % | -0.091 | -0.096 | -40.278 % | 15.402 % | 14.852 % | 15.28 % | 1.07 | 38 |
| momentum | 120 | +0.0067 | +0.24 | 0.807 | 0.988 | [-0.047, +0.060] | -3.106 % | -0.184 | -0.202 | -41.068 % | 15.041 % | 15.02 % | 15.28 % | 1.32 | 19 |
| momentum | 252 | -0.0253 | -0.72 | 0.473 | 0.988 | [-0.094, +0.044] | -0.586 % | 0.017 | 0.023 | -31.931 % | 15.704 % | 15.675 % | 15.385 % | 1.516 | 9 |
| market_structure | 5 | -0.0090 | -0.73 | 0.463 | 0.988 | [-0.033, +0.015] | -18.25 % | -0.641 | -0.578 | -86.992 % | 9.6 % | 15.664 % | 15.28 % | 0.218 | 456 |
| market_structure | 20 | -0.0237 | -1.33 | 0.183 | 0.988 | [-0.059, +0.011] | -15.631 % | -0.777 | -0.676 | -80.369 % | 9.14 % | 15.016 % | 15.28 % | 0.51 | 114 |
| market_structure | 60 | -0.0408 | -1.47 | 0.142 | 0.988 | [-0.095, +0.014] | -12.571 % | -0.618 | -0.555 | -71.517 % | 10.654 % | 14.852 % | 15.28 % | 0.703 | 38 |
| market_structure | 120 | -0.0435 | -1.13 | 0.260 | 0.988 | [-0.119, +0.032] | -16.972 % | -0.691 | -0.551 | -82.294 % | 9.552 % | 15.02 % | 15.28 % | 0.835 | 19 |
| market_structure | 252 | -0.0337 | -0.58 | 0.560 | 0.988 | [-0.147, +0.080] | -15.391 % | -0.632 | -0.503 | -77.166 % | 8.994 % | 15.675 % | 15.385 % | 0.921 | 9 |
| quality | 5 | +0.0068 | +0.94 | 0.346 | 0.988 | [-0.007, +0.021] | -1.006 % | -0.025 | -0.024 | -26.392 % | 15.167 % | 15.728 % | 15.28 % | 0.042 | 456 |
| quality | 20 | +0.0083 | +0.72 | 0.469 | 0.988 | [-0.014, +0.031] | -1.598 % | -0.088 | -0.085 | -25.792 % | 14.052 % | 15.097 % | 15.28 % | 0.129 | 114 |
| quality | 60 | +0.0054 | +0.28 | 0.780 | 0.988 | [-0.032, +0.043] | -2.178 % | -0.178 | -0.169 | -27.693 % | 13.695 % | 14.946 % | 15.28 % | 0.297 | 38 |
| quality | 120 | +0.0027 | +0.10 | 0.918 | 0.988 | [-0.049, +0.055] | -0.433 % | 0.014 | 0.018 | -22.577 % | 14.449 % | 15.128 % | 15.28 % | 0.465 | 19 |
| quality | 252 | +0.0034 | +0.10 | 0.923 | 0.988 | [-0.065, +0.072] | -1.482 % | -0.037 | -0.032 | -31.702 % | 14.702 % | 15.777 % | 15.385 % | 0.751 | 9 |
| growth | 5 | +0.0036 | +0.61 | 0.539 | 0.988 | [-0.008, +0.015] | -0.846 % | -0.019 | -0.017 | -37.611 % | 17.178 % | 15.787 % | 15.28 % | 0.094 | 456 |
| growth | 20 | -0.0017 | -0.19 | 0.849 | 0.988 | [-0.019, +0.016] | -0.37 % | 0.012 | 0.012 | -32.867 % | 17.362 % | 15.145 % | 15.28 % | 0.291 | 114 |
| growth | 60 | -0.0093 | -0.59 | 0.558 | 0.988 | [-0.040, +0.022] | -1.712 % | -0.154 | -0.146 | -38.492 % | 15.972 % | 14.996 % | 15.28 % | 0.696 | 38 |
| growth | 120 | +0.0024 | +0.10 | 0.921 | 0.988 | [-0.045, +0.049] | 2.137 % | 0.251 | 0.272 | -20.219 % | 17.63 % | 15.191 % | 15.28 % | 1.035 | 19 |
| growth | 252 | +0.0331 | +0.99 | 0.321 | 0.988 | [-0.032, +0.099] | 1.298 % | 0.191 | 0.227 | -24.343 % | 17.554 % | 15.861 % | 15.385 % | 1.491 | 9 |
| value | 5 | -0.0051 | -0.58 | 0.561 | 0.988 | [-0.022, +0.012] | -0.776 % | 0.03 | 0.033 | -31.603 % | 16.525 % | 15.734 % | 15.28 % | 0.086 | 456 |
| value | 20 | -0.0003 | -0.02 | 0.984 | 0.988 | [-0.027, +0.027] | -2.356 % | -0.097 | -0.093 | -36.498 % | 14.578 % | 15.101 % | 15.28 % | 0.185 | 114 |
| value | 60 | -0.0012 | -0.05 | 0.958 | 0.988 | [-0.047, +0.044] | -3.124 % | -0.169 | -0.172 | -31.816 % | 13.902 % | 14.96 % | 15.28 % | 0.35 | 38 |
| value | 120 | -0.0065 | -0.22 | 0.829 | 0.988 | [-0.066, +0.053] | -3.116 % | -0.135 | -0.148 | -36.124 % | 14.034 % | 15.142 % | 15.28 % | 0.52 | 19 |
| value | 252 | -0.0100 | -0.21 | 0.832 | 0.988 | [-0.103, +0.083] | -2.711 % | -0.18 | -0.142 | -36.625 % | 14.849 % | 15.837 % | 15.385 % | 0.726 | 9 |
| sector | 5 | +0.0006 | +0.05 | 0.959 | 0.988 | [-0.022, +0.023] | -12.776 % | -0.427 | -0.356 | -76.448 % | 11.277 % | 15.664 % | 15.28 % | 0.409 | 456 |
| sector | 20 | -0.0133 | -0.89 | 0.374 | 0.988 | [-0.043, +0.016] | -2.625 % | -0.101 | -0.105 | -41.862 % | 15.476 % | 15.016 % | 15.28 % | 0.719 | 114 |
| sector | 60 | -0.0052 | -0.27 | 0.790 | 0.988 | [-0.044, +0.033] | 3.497 % | 0.315 | 0.369 | -14.18 % | 17.839 % | 14.852 % | 15.28 % | 1.114 | 38 |
| sector | 120 | +0.0232 | +0.93 | 0.350 | 0.988 | [-0.026, +0.072] | -0.762 % | 0.028 | 0.026 | -30.341 % | 17.313 % | 15.02 % | 15.28 % | 1.474 | 19 |
| sector | 252 | -0.0135 | -0.36 | 0.722 | 0.988 | [-0.087, +0.061] | -5.728 % | -0.287 | -0.29 | -48.099 % | 13.034 % | 15.675 % | 15.385 % | 1.442 | 9 |
| insider | 5 | -0.0049 | -0.74 | 0.456 | 0.988 | [-0.018, +0.008] | 1.038 % | 0.146 | 0.169 | -18.044 % | 17.022 % | 15.718 % | 15.28 % | 0.196 | 456 |
| insider | 20 | +0.0020 | +0.20 | 0.842 | 0.988 | [-0.017, +0.021] | 1.028 % | 0.154 | 0.168 | -16.483 % | 15.68 % | 15.091 % | 15.28 % | 0.556 | 114 |
| insider | 60 | +0.0031 | +0.21 | 0.835 | 0.988 | [-0.026, +0.032] | -2.114 % | -0.223 | -0.237 | -18.202 % | 14.034 % | 14.952 % | 15.28 % | 1.173 | 38 |
| insider | 120 | +0.0017 | +0.07 | 0.942 | 0.988 | [-0.044, +0.048] | 1.036 % | 0.157 | 0.176 | -17.557 % | 14.842 % | 15.128 % | 15.28 % | 1.244 | 19 |
| insider | 252 | +0.0016 | +0.05 | 0.961 | 0.988 | [-0.061, +0.064] | -2.657 % | -0.141 | -0.138 | -33.442 % | 16.444 % | 15.837 % | 15.385 % | 1.253 | 9 |
| all_groups | 5 | +0.0010 | +0.13 | 0.899 | 0.988 | [-0.015, +0.017] | -12.001 % | -0.595 | -0.528 | -71.548 % | 10.138 % | 15.664 % | 15.28 % | 0.312 | 456 |
| all_groups | 20 | -0.0082 | -0.72 | 0.470 | 0.988 | [-0.030, +0.014] | -4.321 % | -0.334 | -0.318 | -39.139 % | 12.283 % | 15.016 % | 15.28 % | 0.581 | 114 |
| all_groups | 60 | -0.0145 | -0.92 | 0.358 | 0.988 | [-0.045, +0.016] | -4.657 % | -0.306 | -0.243 | -38.092 % | 12.975 % | 14.852 % | 15.28 % | 0.958 | 38 |
| all_groups | 120 | +0.0013 | +0.06 | 0.951 | 0.988 | [-0.039, +0.042] | -3.693 % | -0.182 | -0.155 | -34.088 % | 14.229 % | 15.02 % | 15.28 % | 1.154 | 19 |
| all_groups | 252 | -0.0199 | -0.62 | 0.535 | 0.988 | [-0.083, +0.043] | -3.766 % | -0.265 | -0.279 | -42.496 % | 13.736 % | 15.675 % | 15.385 % | 1.366 | 9 |

## Models — strict walk-forward, out-of-sample only

Yearly test folds; each fitted on samples whose outcome was known before the fold (purged), with at least 3 years of history; hyperparameters fixed a priori (no validation set). q = BH within the model tests.

| Model | H | Training (first fold) | OOS period | IC | t | p | q (BH) | AUC | L/S net ann. | L/S Sharpe | L/S Sortino | L/S max DD | Turnover | Baseline (all groups) IC same dates |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| logistic | 5 | 2017-09-06 → 2020-12-22 | 2021-01-07 → 2026-10-09 | +0.0075 | +0.65 | 0.513 | 0.882 | 0.5045 | -1.969 % | -0.044 | -0.045 | -38.728 % | 0.365 | +0.0065 |
| logistic_l2 | 5 | 2017-09-06 → 2020-12-22 | 2021-01-07 → 2026-10-09 | +0.0077 | +0.65 | 0.514 | 0.882 | 0.5048 | -3.294 % | -0.122 | -0.122 | -41.881 % | 0.366 | +0.0065 |
| random_forest | 5 | 2017-09-06 → 2020-12-22 | 2021-01-07 → 2026-10-09 | +0.0086 | +0.68 | 0.494 | 0.882 | 0.5059 | -5.439 % | -0.234 | -0.22 | -45.354 % | 0.426 | +0.0065 |
| logistic | 20 | 2017-09-06 → 2020-12-01 | 2021-01-07 → 2026-10-09 | +0.0086 | +0.53 | 0.598 | 0.882 | 0.5035 | 1.077 % | 0.146 | 0.157 | -30.467 % | 0.66 | +0.0036 |
| logistic_l2 | 20 | 2017-09-06 → 2020-12-01 | 2021-01-07 → 2026-10-09 | +0.0086 | +0.51 | 0.607 | 0.882 | 0.5033 | 1.2 % | 0.154 | 0.157 | -27.653 % | 0.679 | +0.0036 |
| random_forest | 20 | 2017-09-06 → 2020-12-01 | 2021-01-07 → 2026-10-09 | +0.0104 | +0.57 | 0.571 | 0.882 | 0.5041 | -0.68 % | 0.041 | 0.041 | -38.566 % | 0.618 | +0.0036 |
| logistic | 60 | 2017-09-06 → 2020-10-05 | 2021-01-07 → 2026-10-09 | +0.0122 | +0.44 | 0.659 | 0.882 | 0.5108 | -2.718 % | -0.112 | -0.104 | -31.13 % | 0.868 | +0.0096 |
| logistic_l2 | 60 | 2017-09-06 → 2020-10-05 | 2021-01-07 → 2026-10-09 | +0.0081 | +0.28 | 0.778 | 0.898 | 0.5095 | -4.768 % | -0.252 | -0.238 | -35.392 % | 0.839 | +0.0096 |
| random_forest | 60 | 2017-09-06 → 2020-10-05 | 2021-01-07 → 2026-10-09 | -0.0122 | -0.38 | 0.705 | 0.882 | 0.4966 | 0.595 % | 0.12 | 0.12 | -37.66 % | 0.703 | +0.0096 |
| logistic | 120 | 2017-09-06 → 2020-07-10 | 2021-01-07 → 2026-10-09 | +0.0028 | +0.09 | 0.928 | 0.928 | 0.5016 | 0.13 % | 0.087 | 0.087 | -26.365 % | 1.05 | +0.0393 |
| logistic_l2 | 120 | 2017-09-06 → 2020-07-10 | 2021-01-07 → 2026-10-09 | -0.0034 | -0.10 | 0.917 | 0.928 | 0.499 | -1.913 % | -0.031 | -0.03 | -31.874 % | 1.03 | +0.0393 |
| random_forest | 120 | 2017-09-06 → 2020-07-10 | 2021-01-07 → 2026-10-09 | -0.0324 | -0.80 | 0.424 | 0.882 | 0.4838 | 0.937 % | 0.146 | 0.189 | -34.017 % | 0.942 | +0.0393 |
| logistic | 252 | 2017-09-06 → 2020-01-03 | 2021-01-07 → 2026-10-09 | -0.0215 | -0.70 | 0.486 | 0.882 | 0.4996 | -7.086 % | -0.58 | -0.539 | -19.597 % | 1.209 | +0.0347 |
| logistic_l2 | 252 | 2017-09-06 → 2020-01-03 | 2021-01-07 → 2026-10-09 | -0.0272 | -0.81 | 0.417 | 0.882 | 0.4978 | -9.3 % | -0.65 | -0.563 | -24.008 % | 1.163 | +0.0347 |
| random_forest | 252 | 2017-09-06 → 2020-01-03 | 2021-01-07 → 2026-10-09 | -0.0762 | -2.47 | 0.014 | 0.204 | 0.4698 | -13.89 % | -1.075 | -0.7 | -42.32 % | 1.125 | +0.0347 |

Gradient boosting: not justified: no simpler model has a BH-significant positive out-of-sample IC.

## Individual features — mean daily rank IC in the pre-registered direction

q = BH within the 170 feature tests.

| Feature | Group | Sign | Basis | H | IC | t | p | q (BH) | Coverage |
|---|---|---|---|---|---|---|---|---|---|
| mom_1m | momentum | -1 | short-term reversal (Jegadeesh 1990) | 5 | +0.0091 | +0.92 | 0.3577 | 0.898 | 100.0 % |
| mom_1m | momentum | -1 | short-term reversal (Jegadeesh 1990) | 20 | +0.0206 | +1.67 | 0.0956 | 0.898 | 100.0 % |
| mom_1m | momentum | -1 | short-term reversal (Jegadeesh 1990) | 60 | +0.0268 | +1.86 | 0.0626 | 0.898 | 100.0 % |
| mom_1m | momentum | -1 | short-term reversal (Jegadeesh 1990) | 120 | +0.0125 | +1.06 | 0.2876 | 0.898 | 100.0 % |
| mom_1m | momentum | -1 | short-term reversal (Jegadeesh 1990) | 252 | +0.0001 | +0.01 | 0.9911 | 0.999 | 100.0 % |
| mom_3m | momentum | +1 | intermediate momentum (Jegadeesh & Titman 1993) | 5 | -0.0117 | -1.12 | 0.2607 | 0.898 | 100.0 % |
| mom_3m | momentum | +1 | intermediate momentum (Jegadeesh & Titman 1993) | 20 | -0.0187 | -1.29 | 0.1957 | 0.898 | 100.0 % |
| mom_3m | momentum | +1 | intermediate momentum (Jegadeesh & Titman 1993) | 60 | -0.0274 | -1.49 | 0.1376 | 0.898 | 100.0 % |
| mom_3m | momentum | +1 | intermediate momentum (Jegadeesh & Titman 1993) | 120 | +0.0018 | +0.10 | 0.9186 | 0.988 | 100.0 % |
| mom_3m | momentum | +1 | intermediate momentum (Jegadeesh & Titman 1993) | 252 | -0.0032 | -0.17 | 0.8643 | 0.988 | 100.0 % |
| mom_6m | momentum | +1 | momentum (Jegadeesh & Titman 1993) | 5 | +0.0045 | +0.40 | 0.6884 | 0.988 | 100.0 % |
| mom_6m | momentum | +1 | momentum (Jegadeesh & Titman 1993) | 20 | -0.0095 | -0.63 | 0.5274 | 0.925 | 100.0 % |
| mom_6m | momentum | +1 | momentum (Jegadeesh & Titman 1993) | 60 | -0.0052 | -0.26 | 0.7939 | 0.988 | 100.0 % |
| mom_6m | momentum | +1 | momentum (Jegadeesh & Titman 1993) | 120 | +0.0186 | +0.81 | 0.4149 | 0.898 | 100.0 % |
| mom_6m | momentum | +1 | momentum (Jegadeesh & Titman 1993) | 252 | -0.0152 | -0.50 | 0.6178 | 0.988 | 100.0 % |
| mom_12_1 | momentum | +1 | 12-1 month momentum (Carhart 1997) | 5 | +0.0167 | +1.42 | 0.1562 | 0.898 | 100.0 % |
| mom_12_1 | momentum | +1 | 12-1 month momentum (Carhart 1997) | 20 | +0.0019 | +0.12 | 0.9072 | 0.988 | 100.0 % |
| mom_12_1 | momentum | +1 | 12-1 month momentum (Carhart 1997) | 60 | -0.0109 | -0.46 | 0.6430 | 0.988 | 100.0 % |
| mom_12_1 | momentum | +1 | 12-1 month momentum (Carhart 1997) | 120 | -0.0068 | -0.21 | 0.8328 | 0.988 | 100.0 % |
| mom_12_1 | momentum | +1 | 12-1 month momentum (Carhart 1997) | 252 | -0.0355 | -0.87 | 0.3846 | 0.898 | 100.0 % |
| risk_adj_mom | momentum | +1 | volatility-scaled momentum (Barroso & Santa-Clara 2015) | 5 | +0.0157 | +1.37 | 0.1696 | 0.898 | 100.0 % |
| risk_adj_mom | momentum | +1 | volatility-scaled momentum (Barroso & Santa-Clara 2015) | 20 | +0.0017 | +0.11 | 0.9136 | 0.988 | 100.0 % |
| risk_adj_mom | momentum | +1 | volatility-scaled momentum (Barroso & Santa-Clara 2015) | 60 | -0.0082 | -0.35 | 0.7277 | 0.988 | 100.0 % |
| risk_adj_mom | momentum | +1 | volatility-scaled momentum (Barroso & Santa-Clara 2015) | 120 | -0.0034 | -0.11 | 0.9157 | 0.988 | 100.0 % |
| risk_adj_mom | momentum | +1 | volatility-scaled momentum (Barroso & Santa-Clara 2015) | 252 | -0.0341 | -0.83 | 0.4085 | 0.898 | 100.0 % |
| vol_3m | market_structure | -1 | low-volatility anomaly (Ang et al. 2006) | 5 | -0.0125 | -0.95 | 0.3410 | 0.898 | 100.0 % |
| vol_3m | market_structure | -1 | low-volatility anomaly (Ang et al. 2006) | 20 | -0.0296 | -1.56 | 0.1181 | 0.898 | 100.0 % |
| vol_3m | market_structure | -1 | low-volatility anomaly (Ang et al. 2006) | 60 | -0.0520 | -1.70 | 0.0887 | 0.898 | 100.0 % |
| vol_3m | market_structure | -1 | low-volatility anomaly (Ang et al. 2006) | 120 | -0.0624 | -1.45 | 0.1463 | 0.898 | 100.0 % |
| vol_3m | market_structure | -1 | low-volatility anomaly (Ang et al. 2006) | 252 | -0.0633 | -1.06 | 0.2880 | 0.898 | 100.0 % |
| beta_1y | market_structure | -1 | betting against beta (Frazzini & Pedersen 2014) | 5 | -0.0166 | -1.05 | 0.2934 | 0.898 | 100.0 % |
| beta_1y | market_structure | -1 | betting against beta (Frazzini & Pedersen 2014) | 20 | -0.0344 | -1.52 | 0.1273 | 0.898 | 100.0 % |
| beta_1y | market_structure | -1 | betting against beta (Frazzini & Pedersen 2014) | 60 | -0.0544 | -1.50 | 0.1326 | 0.898 | 100.0 % |
| beta_1y | market_structure | -1 | betting against beta (Frazzini & Pedersen 2014) | 120 | -0.0678 | -1.37 | 0.1704 | 0.898 | 100.0 % |
| beta_1y | market_structure | -1 | betting against beta (Frazzini & Pedersen 2014) | 252 | -0.0853 | -1.20 | 0.2316 | 0.898 | 100.0 % |
| idio_vol_1y | market_structure | -1 | idiosyncratic volatility puzzle (Ang et al. 2006) | 5 | -0.0085 | -0.85 | 0.3958 | 0.898 | 100.0 % |
| idio_vol_1y | market_structure | -1 | idiosyncratic volatility puzzle (Ang et al. 2006) | 20 | -0.0215 | -1.43 | 0.1525 | 0.898 | 100.0 % |
| idio_vol_1y | market_structure | -1 | idiosyncratic volatility puzzle (Ang et al. 2006) | 60 | -0.0319 | -1.36 | 0.1746 | 0.898 | 100.0 % |
| idio_vol_1y | market_structure | -1 | idiosyncratic volatility puzzle (Ang et al. 2006) | 120 | -0.0351 | -1.08 | 0.2792 | 0.898 | 100.0 % |
| idio_vol_1y | market_structure | -1 | idiosyncratic volatility puzzle (Ang et al. 2006) | 252 | -0.0215 | -0.47 | 0.6397 | 0.988 | 100.0 % |
| log_dollar_volume | market_structure | -1 | illiquidity premium (Amihud 2002) | 5 | -0.0007 | -0.12 | 0.9038 | 0.988 | 100.0 % |
| log_dollar_volume | market_structure | -1 | illiquidity premium (Amihud 2002) | 20 | +0.0016 | +0.19 | 0.8525 | 0.988 | 100.0 % |
| log_dollar_volume | market_structure | -1 | illiquidity premium (Amihud 2002) | 60 | +0.0041 | +0.36 | 0.7203 | 0.988 | 100.0 % |
| log_dollar_volume | market_structure | -1 | illiquidity premium (Amihud 2002) | 120 | +0.0059 | +0.33 | 0.7382 | 0.988 | 100.0 % |
| log_dollar_volume | market_structure | -1 | illiquidity premium (Amihud 2002) | 252 | +0.0217 | +0.85 | 0.3971 | 0.898 | 100.0 % |
| volume_trend | market_structure | -1 | high turnover, lower returns (Lee & Swaminathan 2000) | 5 | +0.0023 | +0.46 | 0.6484 | 0.988 | 100.0 % |
| volume_trend | market_structure | -1 | high turnover, lower returns (Lee & Swaminathan 2000) | 20 | -0.0001 | -0.02 | 0.9849 | 0.999 | 100.0 % |
| volume_trend | market_structure | -1 | high turnover, lower returns (Lee & Swaminathan 2000) | 60 | -0.0073 | -0.71 | 0.4759 | 0.909 | 100.0 % |
| volume_trend | market_structure | -1 | high turnover, lower returns (Lee & Swaminathan 2000) | 120 | -0.0078 | -0.76 | 0.4490 | 0.898 | 100.0 % |
| volume_trend | market_structure | -1 | high turnover, lower returns (Lee & Swaminathan 2000) | 252 | -0.0073 | -1.16 | 0.2472 | 0.898 | 100.0 % |
| dist_high_1y | market_structure | +1 | 52-week-high momentum (George & Hwang 2004) | 5 | -0.0041 | -0.36 | 0.7195 | 0.988 | 100.0 % |
| dist_high_1y | market_structure | +1 | 52-week-high momentum (George & Hwang 2004) | 20 | -0.0215 | -1.28 | 0.2004 | 0.898 | 100.0 % |
| dist_high_1y | market_structure | +1 | 52-week-high momentum (George & Hwang 2004) | 60 | -0.0388 | -1.71 | 0.0879 | 0.898 | 100.0 % |
| dist_high_1y | market_structure | +1 | 52-week-high momentum (George & Hwang 2004) | 120 | -0.0261 | -0.95 | 0.3395 | 0.898 | 100.0 % |
| dist_high_1y | market_structure | +1 | 52-week-high momentum (George & Hwang 2004) | 252 | -0.0344 | -0.87 | 0.3842 | 0.898 | 100.0 % |
| log_market_cap | market_structure | -1 | size effect (Banz 1981; Fama & French 1993) | 5 | +0.0069 | +1.20 | 0.2298 | 0.898 | 99.6 % |
| log_market_cap | market_structure | -1 | size effect (Banz 1981; Fama & French 1993) | 20 | +0.0179 | +2.12 | 0.0337 | 0.898 | 99.6 % |
| log_market_cap | market_structure | -1 | size effect (Banz 1981; Fama & French 1993) | 60 | +0.0298 | +2.52 | 0.0116 | 0.898 | 99.6 % |
| log_market_cap | market_structure | -1 | size effect (Banz 1981; Fama & French 1993) | 120 | +0.0385 | +2.27 | 0.0229 | 0.898 | 99.6 % |
| log_market_cap | market_structure | -1 | size effect (Banz 1981; Fama & French 1993) | 252 | +0.0576 | +2.64 | 0.0084 | 0.898 | 99.6 % |
| gross_profitability | quality | +1 | gross profits / assets (Novy-Marx 2013) | 5 | +0.0084 | +1.28 | 0.2016 | 0.898 | 67.0 % |
| gross_profitability | quality | +1 | gross profits / assets (Novy-Marx 2013) | 20 | +0.0130 | +1.24 | 0.2150 | 0.898 | 67.0 % |
| gross_profitability | quality | +1 | gross profits / assets (Novy-Marx 2013) | 60 | +0.0172 | +1.02 | 0.3068 | 0.898 | 67.0 % |
| gross_profitability | quality | +1 | gross profits / assets (Novy-Marx 2013) | 120 | +0.0178 | +0.74 | 0.4561 | 0.901 | 67.0 % |
| gross_profitability | quality | +1 | gross profits / assets (Novy-Marx 2013) | 252 | +0.0288 | +0.77 | 0.4443 | 0.898 | 67.0 % |
| operating_margin | quality | +1 | profitability (Fama & French 2015, RMW) | 5 | -0.0033 | -0.63 | 0.5277 | 0.925 | 87.4 % |
| operating_margin | quality | +1 | profitability (Fama & French 2015, RMW) | 20 | -0.0117 | -1.27 | 0.2024 | 0.898 | 87.4 % |
| operating_margin | quality | +1 | profitability (Fama & French 2015, RMW) | 60 | -0.0230 | -1.49 | 0.1355 | 0.898 | 87.4 % |
| operating_margin | quality | +1 | profitability (Fama & French 2015, RMW) | 120 | -0.0254 | -1.22 | 0.2232 | 0.898 | 87.4 % |
| operating_margin | quality | +1 | profitability (Fama & French 2015, RMW) | 252 | -0.0212 | -0.84 | 0.4015 | 0.898 | 87.4 % |
| roe | quality | +1 | return on equity (Fama & French 2015; Hou, Xue & Zhang 2015) | 5 | +0.0050 | +0.82 | 0.4145 | 0.898 | 88.1 % |
| roe | quality | +1 | return on equity (Fama & French 2015; Hou, Xue & Zhang 2015) | 20 | +0.0059 | +0.59 | 0.5554 | 0.944 | 88.1 % |
| roe | quality | +1 | return on equity (Fama & French 2015; Hou, Xue & Zhang 2015) | 60 | +0.0036 | +0.24 | 0.8136 | 0.988 | 88.1 % |
| roe | quality | +1 | return on equity (Fama & French 2015; Hou, Xue & Zhang 2015) | 120 | -0.0008 | -0.04 | 0.9684 | 0.999 | 88.1 % |
| roe | quality | +1 | return on equity (Fama & French 2015; Hou, Xue & Zhang 2015) | 252 | -0.0075 | -0.26 | 0.7932 | 0.988 | 88.1 % |
| roa | quality | +1 | return on assets (Haugen & Baker 1996) | 5 | +0.0024 | +0.34 | 0.7334 | 0.988 | 95.3 % |
| roa | quality | +1 | return on assets (Haugen & Baker 1996) | 20 | +0.0013 | +0.11 | 0.9139 | 0.988 | 95.3 % |
| roa | quality | +1 | return on assets (Haugen & Baker 1996) | 60 | -0.0064 | -0.33 | 0.7426 | 0.988 | 95.3 % |
| roa | quality | +1 | return on assets (Haugen & Baker 1996) | 120 | -0.0143 | -0.54 | 0.5918 | 0.988 | 95.3 % |
| roa | quality | +1 | return on assets (Haugen & Baker 1996) | 252 | -0.0269 | -0.68 | 0.4978 | 0.925 | 95.3 % |
| fcf_margin | quality | +1 | cash profitability (Ball et al. 2016) | 5 | +0.0058 | +0.76 | 0.4468 | 0.898 | 77.0 % |
| fcf_margin | quality | +1 | cash profitability (Ball et al. 2016) | 20 | +0.0072 | +0.61 | 0.5393 | 0.926 | 77.0 % |
| fcf_margin | quality | +1 | cash profitability (Ball et al. 2016) | 60 | +0.0033 | +0.17 | 0.8687 | 0.988 | 77.0 % |
| fcf_margin | quality | +1 | cash profitability (Ball et al. 2016) | 120 | -0.0082 | -0.30 | 0.7647 | 0.988 | 77.0 % |
| fcf_margin | quality | +1 | cash profitability (Ball et al. 2016) | 252 | -0.0140 | -0.41 | 0.6858 | 0.988 | 77.0 % |
| accruals | quality | -1 | accrual anomaly (Sloan 1996) | 5 | +0.0064 | +1.39 | 0.1643 | 0.898 | 94.3 % |
| accruals | quality | -1 | accrual anomaly (Sloan 1996) | 20 | +0.0118 | +1.60 | 0.1091 | 0.898 | 94.3 % |
| accruals | quality | -1 | accrual anomaly (Sloan 1996) | 60 | +0.0176 | +1.36 | 0.1724 | 0.898 | 94.3 % |
| accruals | quality | -1 | accrual anomaly (Sloan 1996) | 120 | +0.0200 | +1.04 | 0.2993 | 0.898 | 94.3 % |
| accruals | quality | -1 | accrual anomaly (Sloan 1996) | 252 | +0.0262 | +1.28 | 0.2020 | 0.898 | 94.3 % |
| debt_to_equity | quality | -1 | balance-sheet quality (Asness, Frazzini & Pedersen 2019) | 5 | +0.0027 | +0.41 | 0.6814 | 0.988 | 85.2 % |
| debt_to_equity | quality | -1 | balance-sheet quality (Asness, Frazzini & Pedersen 2019) | 20 | +0.0040 | +0.41 | 0.6815 | 0.988 | 85.2 % |
| debt_to_equity | quality | -1 | balance-sheet quality (Asness, Frazzini & Pedersen 2019) | 60 | +0.0025 | +0.14 | 0.8911 | 0.988 | 85.2 % |
| debt_to_equity | quality | -1 | balance-sheet quality (Asness, Frazzini & Pedersen 2019) | 120 | +0.0004 | +0.01 | 0.9896 | 0.999 | 85.2 % |
| debt_to_equity | quality | -1 | balance-sheet quality (Asness, Frazzini & Pedersen 2019) | 252 | -0.0020 | -0.06 | 0.9555 | 0.999 | 85.2 % |
| revenue_growth | growth | +1 | sales growth persistence (hypothesis; evidence mixed) | 5 | +0.0088 | +1.14 | 0.2565 | 0.898 | 95.9 % |
| revenue_growth | growth | +1 | sales growth persistence (hypothesis; evidence mixed) | 20 | +0.0018 | +0.15 | 0.8807 | 0.988 | 95.9 % |
| revenue_growth | growth | +1 | sales growth persistence (hypothesis; evidence mixed) | 60 | -0.0137 | -0.67 | 0.5010 | 0.925 | 95.9 % |
| revenue_growth | growth | +1 | sales growth persistence (hypothesis; evidence mixed) | 120 | -0.0099 | -0.36 | 0.7208 | 0.988 | 95.9 % |
| revenue_growth | growth | +1 | sales growth persistence (hypothesis; evidence mixed) | 252 | +0.0086 | +0.27 | 0.7873 | 0.988 | 95.9 % |
| eps_growth | growth | +1 | earnings momentum (Chan, Jegadeesh & Lakonishok 1996) | 5 | +0.0061 | +1.05 | 0.2934 | 0.898 | 91.4 % |
| eps_growth | growth | +1 | earnings momentum (Chan, Jegadeesh & Lakonishok 1996) | 20 | +0.0050 | +0.51 | 0.6073 | 0.988 | 91.4 % |
| eps_growth | growth | +1 | earnings momentum (Chan, Jegadeesh & Lakonishok 1996) | 60 | -0.0031 | -0.16 | 0.8737 | 0.988 | 91.4 % |
| eps_growth | growth | +1 | earnings momentum (Chan, Jegadeesh & Lakonishok 1996) | 120 | -0.0079 | -0.26 | 0.7926 | 0.988 | 91.4 % |
| eps_growth | growth | +1 | earnings momentum (Chan, Jegadeesh & Lakonishok 1996) | 252 | -0.0003 | -0.01 | 0.9941 | 0.999 | 91.4 % |
| fcf_growth | growth | +1 | cash-flow growth (hypothesis) | 5 | +0.0078 | +1.45 | 0.1476 | 0.898 | 73.8 % |
| fcf_growth | growth | +1 | cash-flow growth (hypothesis) | 20 | +0.0131 | +1.46 | 0.1447 | 0.898 | 73.8 % |
| fcf_growth | growth | +1 | cash-flow growth (hypothesis) | 60 | +0.0212 | +1.17 | 0.2408 | 0.898 | 73.8 % |
| fcf_growth | growth | +1 | cash-flow growth (hypothesis) | 120 | +0.0343 | +1.24 | 0.2148 | 0.898 | 73.8 % |
| fcf_growth | growth | +1 | cash-flow growth (hypothesis) | 252 | +0.0602 | +1.83 | 0.0672 | 0.898 | 73.8 % |
| asset_growth | growth | -1 | asset growth anomaly (Cooper, Gulen & Schill 2008) | 5 | -0.0104 | -1.70 | 0.0891 | 0.898 | 99.4 % |
| asset_growth | growth | -1 | asset growth anomaly (Cooper, Gulen & Schill 2008) | 20 | -0.0149 | -1.47 | 0.1406 | 0.898 | 99.4 % |
| asset_growth | growth | -1 | asset growth anomaly (Cooper, Gulen & Schill 2008) | 60 | -0.0119 | -0.71 | 0.4743 | 0.909 | 99.4 % |
| asset_growth | growth | -1 | asset growth anomaly (Cooper, Gulen & Schill 2008) | 120 | +0.0028 | +0.12 | 0.9002 | 0.988 | 99.4 % |
| asset_growth | growth | -1 | asset growth anomaly (Cooper, Gulen & Schill 2008) | 252 | +0.0274 | +0.87 | 0.3825 | 0.898 | 99.4 % |
| earnings_yield | value | +1 | E/P (Basu 1977) | 5 | -0.0021 | -0.29 | 0.7720 | 0.988 | 95.3 % |
| earnings_yield | value | +1 | E/P (Basu 1977) | 20 | +0.0005 | +0.05 | 0.9624 | 0.999 | 95.3 % |
| earnings_yield | value | +1 | E/P (Basu 1977) | 60 | -0.0034 | -0.20 | 0.8442 | 0.988 | 95.3 % |
| earnings_yield | value | +1 | E/P (Basu 1977) | 120 | -0.0133 | -0.65 | 0.5177 | 0.925 | 95.3 % |
| earnings_yield | value | +1 | E/P (Basu 1977) | 252 | -0.0249 | -0.82 | 0.4129 | 0.898 | 95.3 % |
| sales_to_ev | value | +1 | EV/sales, inverted (value; Loughran & Wellman 2011 for EBITDA/EV) | 5 | +0.0007 | +0.09 | 0.9318 | 0.990 | 90.9 % |
| sales_to_ev | value | +1 | EV/sales, inverted (value; Loughran & Wellman 2011 for EBITDA/EV) | 20 | +0.0139 | +0.98 | 0.3275 | 0.898 | 90.9 % |
| sales_to_ev | value | +1 | EV/sales, inverted (value; Loughran & Wellman 2011 for EBITDA/EV) | 60 | +0.0278 | +1.10 | 0.2717 | 0.898 | 90.9 % |
| sales_to_ev | value | +1 | EV/sales, inverted (value; Loughran & Wellman 2011 for EBITDA/EV) | 120 | +0.0322 | +0.92 | 0.3565 | 0.898 | 90.9 % |
| sales_to_ev | value | +1 | EV/sales, inverted (value; Loughran & Wellman 2011 for EBITDA/EV) | 252 | +0.0408 | +0.78 | 0.4333 | 0.898 | 90.9 % |
| fcf_yield | value | +1 | cash-flow yield (Lakonishok, Shleifer & Vishny 1994) | 5 | +0.0007 | +0.09 | 0.9306 | 0.990 | 78.0 % |
| fcf_yield | value | +1 | cash-flow yield (Lakonishok, Shleifer & Vishny 1994) | 20 | +0.0102 | +0.79 | 0.4308 | 0.898 | 78.0 % |
| fcf_yield | value | +1 | cash-flow yield (Lakonishok, Shleifer & Vishny 1994) | 60 | +0.0143 | +0.67 | 0.5012 | 0.925 | 78.0 % |
| fcf_yield | value | +1 | cash-flow yield (Lakonishok, Shleifer & Vishny 1994) | 120 | +0.0099 | +0.41 | 0.6802 | 0.988 | 78.0 % |
| fcf_yield | value | +1 | cash-flow yield (Lakonishok, Shleifer & Vishny 1994) | 252 | +0.0045 | +0.12 | 0.9010 | 0.988 | 78.0 % |
| ebitda_to_ev | value | +1 | enterprise multiple, inverted (Loughran & Wellman 2011) | 5 | -0.0030 | -0.33 | 0.7412 | 0.988 | 78.6 % |
| ebitda_to_ev | value | +1 | enterprise multiple, inverted (Loughran & Wellman 2011) | 20 | +0.0023 | +0.17 | 0.8685 | 0.988 | 78.6 % |
| ebitda_to_ev | value | +1 | enterprise multiple, inverted (Loughran & Wellman 2011) | 60 | +0.0029 | +0.12 | 0.9068 | 0.988 | 78.6 % |
| ebitda_to_ev | value | +1 | enterprise multiple, inverted (Loughran & Wellman 2011) | 120 | +0.0056 | +0.18 | 0.8536 | 0.988 | 78.6 % |
| ebitda_to_ev | value | +1 | enterprise multiple, inverted (Loughran & Wellman 2011) | 252 | +0.0153 | +0.32 | 0.7472 | 0.988 | 78.6 % |
| book_to_market | value | +1 | B/M (Fama & French 1992) | 5 | -0.0101 | -1.28 | 0.2001 | 0.898 | 99.6 % |
| book_to_market | value | +1 | B/M (Fama & French 1992) | 20 | -0.0124 | -1.00 | 0.3158 | 0.898 | 99.6 % |
| book_to_market | value | +1 | B/M (Fama & French 1992) | 60 | -0.0207 | -0.96 | 0.3356 | 0.898 | 99.6 % |
| book_to_market | value | +1 | B/M (Fama & French 1992) | 120 | -0.0279 | -0.90 | 0.3706 | 0.898 | 99.6 % |
| book_to_market | value | +1 | B/M (Fama & French 1992) | 252 | -0.0314 | -0.72 | 0.4690 | 0.909 | 99.6 % |
| earnings_yield_vs_sector | value | +1 | within-industry value (Asness, Porter & Stevens 2000) | 5 | -0.0049 | -0.80 | 0.4242 | 0.898 | 95.3 % |
| earnings_yield_vs_sector | value | +1 | within-industry value (Asness, Porter & Stevens 2000) | 20 | -0.0060 | -0.64 | 0.5211 | 0.925 | 95.3 % |
| earnings_yield_vs_sector | value | +1 | within-industry value (Asness, Porter & Stevens 2000) | 60 | -0.0094 | -0.61 | 0.5393 | 0.926 | 95.3 % |
| earnings_yield_vs_sector | value | +1 | within-industry value (Asness, Porter & Stevens 2000) | 120 | -0.0160 | -0.78 | 0.4357 | 0.898 | 95.3 % |
| earnings_yield_vs_sector | value | +1 | within-industry value (Asness, Porter & Stevens 2000) | 252 | -0.0258 | -0.86 | 0.3879 | 0.898 | 95.3 % |
| sector_mom_6m | sector | +1 | industry momentum (Moskowitz & Grinblatt 1999) | 5 | -0.0083 | -0.80 | 0.4244 | 0.898 | 100.0 % |
| sector_mom_6m | sector | +1 | industry momentum (Moskowitz & Grinblatt 1999) | 20 | -0.0190 | -1.39 | 0.1638 | 0.898 | 100.0 % |
| sector_mom_6m | sector | +1 | industry momentum (Moskowitz & Grinblatt 1999) | 60 | -0.0006 | -0.03 | 0.9735 | 0.999 | 100.0 % |
| sector_mom_6m | sector | +1 | industry momentum (Moskowitz & Grinblatt 1999) | 120 | +0.0333 | +1.25 | 0.2103 | 0.898 | 100.0 % |
| sector_mom_6m | sector | +1 | industry momentum (Moskowitz & Grinblatt 1999) | 252 | +0.0097 | +0.23 | 0.8190 | 0.988 | 100.0 % |
| mom_6m_vs_sector | sector | +1 | within-industry momentum (Asness, Porter & Stevens 2000) | 5 | +0.0076 | +0.88 | 0.3804 | 0.898 | 100.0 % |
| mom_6m_vs_sector | sector | +1 | within-industry momentum (Asness, Porter & Stevens 2000) | 20 | -0.0023 | -0.18 | 0.8554 | 0.988 | 100.0 % |
| mom_6m_vs_sector | sector | +1 | within-industry momentum (Asness, Porter & Stevens 2000) | 60 | -0.0084 | -0.44 | 0.6568 | 0.988 | 100.0 % |
| mom_6m_vs_sector | sector | +1 | within-industry momentum (Asness, Porter & Stevens 2000) | 120 | -0.0007 | -0.03 | 0.9725 | 0.999 | 100.0 % |
| mom_6m_vs_sector | sector | +1 | within-industry momentum (Asness, Porter & Stevens 2000) | 252 | -0.0287 | -1.47 | 0.1404 | 0.898 | 100.0 % |
| insider_buyers_90d | insider | +1 | insider purchases (Lakonishok & Lee 2001) | 5 | +0.0010 | +0.25 | 0.8006 | 0.988 | 99.6 % |
| insider_buyers_90d | insider | +1 | insider purchases (Lakonishok & Lee 2001) | 20 | +0.0047 | +0.87 | 0.3839 | 0.898 | 99.6 % |
| insider_buyers_90d | insider | +1 | insider purchases (Lakonishok & Lee 2001) | 60 | +0.0080 | +1.09 | 0.2777 | 0.898 | 99.6 % |
| insider_buyers_90d | insider | +1 | insider purchases (Lakonishok & Lee 2001) | 120 | +0.0125 | +1.31 | 0.1892 | 0.898 | 99.6 % |
| insider_buyers_90d | insider | +1 | insider purchases (Lakonishok & Lee 2001) | 252 | +0.0000 | +0.00 | 0.9991 | 0.999 | 99.6 % |
| insider_net_buy_to_mcap | insider | +1 | net insider buying (Lakonishok & Lee 2001; Cohen, Malloy & Pomorski 2012) | 5 | -0.0062 | -1.00 | 0.3185 | 0.898 | 99.6 % |
| insider_net_buy_to_mcap | insider | +1 | net insider buying (Lakonishok & Lee 2001; Cohen, Malloy & Pomorski 2012) | 20 | -0.0014 | -0.14 | 0.8848 | 0.988 | 99.6 % |
| insider_net_buy_to_mcap | insider | +1 | net insider buying (Lakonishok & Lee 2001; Cohen, Malloy & Pomorski 2012) | 60 | -0.0054 | -0.36 | 0.7152 | 0.988 | 99.6 % |
| insider_net_buy_to_mcap | insider | +1 | net insider buying (Lakonishok & Lee 2001; Cohen, Malloy & Pomorski 2012) | 120 | -0.0098 | -0.43 | 0.6669 | 0.988 | 99.6 % |
| insider_net_buy_to_mcap | insider | +1 | net insider buying (Lakonishok & Lee 2001; Cohen, Malloy & Pomorski 2012) | 252 | -0.0094 | -0.32 | 0.7501 | 0.988 | 99.6 % |
| insider_disc_sellers_90d | insider | -1 | discretionary insider selling (Cohen, Malloy & Pomorski 2012) | 5 | -0.0042 | -0.66 | 0.5068 | 0.925 | 99.6 % |
| insider_disc_sellers_90d | insider | -1 | discretionary insider selling (Cohen, Malloy & Pomorski 2012) | 20 | +0.0034 | +0.34 | 0.7319 | 0.988 | 99.6 % |
| insider_disc_sellers_90d | insider | -1 | discretionary insider selling (Cohen, Malloy & Pomorski 2012) | 60 | +0.0074 | +0.47 | 0.6422 | 0.988 | 99.6 % |
| insider_disc_sellers_90d | insider | -1 | discretionary insider selling (Cohen, Malloy & Pomorski 2012) | 120 | +0.0080 | +0.32 | 0.7501 | 0.988 | 99.6 % |
| insider_disc_sellers_90d | insider | -1 | discretionary insider selling (Cohen, Malloy & Pomorski 2012) | 252 | +0.0147 | +0.46 | 0.6464 | 0.988 | 99.6 % |
