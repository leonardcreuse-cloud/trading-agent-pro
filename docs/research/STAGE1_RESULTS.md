# Research study — stage 1 results

Computed 2026-10-07T12:15:45+00:00. Generated from `reports/research_stage1.json` by `src/research/experiment.py`; the protocol is fixed in code before results.

## Conclusion

- 155 feature tests, 35 group tests, 15 model tests (205 in total).
- After Benjamini-Hochberg correction (q < 0.05) within each family: 0 feature, 0 group and 0 model results are significant (0, 0, 0 in the pre-registered direction).
- After Bonferroni correction: 0 significant.
- No group composite or model shows a statistically reliable predictive edge after correction.

## Sample

- Universe: current S&P 500 members excl. Financials and Real Estate; seeded random sample (seed 2026) of 150; stock included from its date added to the index.
- Stocks: 148 with data of 150 requested; median 129 stocks per date.
- Observations: 58,348 stock-dates on 457 weekly dates, 2017-09-01 → 2026-09-30 (every 5 sessions).
- Biases: survivorship: members removed before today are absent; GICS sector is the current classification.
- Excluded stocks: PSKY (7 usable sessions), Q (237 usable sessions).
- Not testable (no free point-in-time data) or deferred: analyst_revisions: no free point-in-time history of estimates or price targets; guidance_changes: no free machine-readable guidance history; insider: deferred to stage 2 (Form 4 history download); macro: time-series hypothesis: identical for all stocks on a date (separate design); events: deferred (earnings dates / 8-K items).

## Group composites (no fitting) — mean daily rank IC in the pre-registered direction

Newey-West t; q = Benjamini-Hochberg within the 35 group tests. Portfolio: top minus bottom quintile, rebalanced every H sessions, net of 10 bp per unit of turnover, risk-free rate 0.

| Group | H | IC | t | p | q (BH) | 95 % CI | L/S net ann. | L/S Sharpe | L/S Sortino | L/S max DD | Top-Q net ann. | Equal-weight ann. | SPY ann. | Turnover | Periods |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| momentum | 5 | +0.0017 | +0.15 | 0.880 | 0.986 | [-0.020, +0.024] | -6.8 % | -0.256 | -0.231 | -65.329 % | 14.456 % | 14.769 % | 15.143 % | 0.349 | 456 |
| momentum | 20 | -0.0051 | -0.33 | 0.740 | 0.986 | [-0.035, +0.025] | -4.816 % | -0.175 | -0.159 | -61.458 % | 14.756 % | 14.639 % | 15.143 % | 0.682 | 114 |
| momentum | 60 | -0.0010 | -0.05 | 0.962 | 0.986 | [-0.042, +0.040] | -3.287 % | -0.146 | -0.133 | -54.654 % | 14.546 % | 14.418 % | 15.143 % | 1.073 | 38 |
| momentum | 120 | +0.0239 | +0.86 | 0.392 | 0.986 | [-0.031, +0.078] | 0.439 % | 0.093 | 0.132 | -32.229 % | 17.613 % | 14.537 % | 15.143 % | 1.28 | 19 |
| momentum | 252 | -0.0029 | -0.09 | 0.933 | 0.986 | [-0.069, +0.063] | 2.021 % | 0.207 | 0.282 | -30.888 % | 17.998 % | 16.234 % | 15.583 % | 1.507 | 9 |
| market_structure | 5 | -0.0208 | -1.73 | 0.083 | 0.986 | [-0.044, +0.003] | -17.404 % | -0.8 | -0.786 | -82.167 % | 7.268 % | 14.769 % | 15.143 % | 0.22 | 456 |
| market_structure | 20 | -0.0279 | -1.50 | 0.134 | 0.986 | [-0.065, +0.009] | -16.62 % | -0.779 | -0.698 | -81.204 % | 8.985 % | 14.639 % | 15.143 % | 0.493 | 114 |
| market_structure | 60 | -0.0430 | -1.45 | 0.148 | 0.986 | [-0.101, +0.015] | -15.6 % | -0.743 | -0.634 | -78.326 % | 8.761 % | 14.418 % | 15.143 % | 0.695 | 38 |
| market_structure | 120 | -0.0482 | -1.18 | 0.239 | 0.986 | [-0.128, +0.032] | -17.359 % | -0.747 | -0.564 | -82.785 % | 7.955 % | 14.537 % | 15.143 % | 0.777 | 19 |
| market_structure | 252 | -0.0300 | -0.47 | 0.636 | 0.986 | [-0.154, +0.094] | -15.697 % | -0.57 | -0.474 | -80.558 % | 10.133 % | 16.234 % | 15.583 % | 0.926 | 9 |
| quality | 5 | +0.0083 | +1.11 | 0.268 | 0.986 | [-0.006, +0.023] | 1.567 % | 0.184 | 0.18 | -30.273 % | 18.078 % | 14.78 % | 15.143 % | 0.042 | 456 |
| quality | 20 | +0.0119 | +1.04 | 0.299 | 0.986 | [-0.011, +0.034] | 1.304 % | 0.164 | 0.147 | -32.503 % | 17.868 % | 14.652 % | 15.143 % | 0.121 | 114 |
| quality | 60 | +0.0144 | +0.73 | 0.466 | 0.986 | [-0.024, +0.053] | 1.42 % | 0.173 | 0.147 | -33.979 % | 17.316 % | 14.467 % | 15.143 % | 0.288 | 38 |
| quality | 120 | +0.0235 | +0.79 | 0.427 | 0.986 | [-0.035, +0.082] | 1.797 % | 0.195 | 0.151 | -39.389 % | 17.787 % | 14.621 % | 15.143 % | 0.436 | 19 |
| quality | 252 | +0.0233 | +0.61 | 0.544 | 0.986 | [-0.052, +0.099] | 0.455 % | 0.106 | 0.097 | -36.926 % | 16.589 % | 16.297 % | 15.583 % | 0.731 | 9 |
| growth | 5 | +0.0039 | +0.56 | 0.573 | 0.986 | [-0.010, +0.017] | 1.762 % | 0.199 | 0.194 | -41.109 % | 19.693 % | 14.787 % | 15.143 % | 0.092 | 456 |
| growth | 20 | -0.0007 | -0.06 | 0.954 | 0.986 | [-0.024, +0.022] | 0.759 % | 0.125 | 0.111 | -44.334 % | 18.87 % | 14.652 % | 15.143 % | 0.279 | 114 |
| growth | 60 | -0.0052 | -0.23 | 0.819 | 0.986 | [-0.049, +0.039] | 2.318 % | 0.229 | 0.226 | -40.336 % | 17.822 % | 14.441 % | 15.143 % | 0.678 | 38 |
| growth | 120 | +0.0006 | +0.02 | 0.986 | 0.986 | [-0.065, +0.066] | 6.895 % | 0.492 | 0.907 | -15.901 % | 20.096 % | 14.59 % | 15.143 % | 1.034 | 19 |
| growth | 252 | -0.0013 | -0.03 | 0.976 | 0.986 | [-0.084, +0.082] | 1.65 % | 0.16 | 0.253 | -41.914 % | 18.388 % | 16.268 % | 15.583 % | 1.492 | 9 |
| value | 5 | -0.0067 | -0.76 | 0.447 | 0.986 | [-0.024, +0.011] | -4.745 % | -0.222 | -0.242 | -44.169 % | 12.258 % | 14.782 % | 15.143 % | 0.095 | 456 |
| value | 20 | -0.0060 | -0.46 | 0.646 | 0.986 | [-0.031, +0.019] | -3.928 % | -0.186 | -0.182 | -43.035 % | 13.016 % | 14.646 % | 15.143 % | 0.191 | 114 |
| value | 60 | -0.0111 | -0.52 | 0.605 | 0.986 | [-0.053, +0.031] | -3.115 % | -0.13 | -0.118 | -31.564 % | 13.649 % | 14.444 % | 15.143 % | 0.375 | 38 |
| value | 120 | -0.0303 | -1.08 | 0.281 | 0.986 | [-0.085, +0.025] | -3.978 % | -0.148 | -0.143 | -37.367 % | 13.742 % | 14.562 % | 15.143 % | 0.548 | 19 |
| value | 252 | -0.0445 | -1.18 | 0.236 | 0.986 | [-0.118, +0.029] | -1.828 % | -0.092 | -0.095 | -28.486 % | 16.706 % | 16.281 % | 15.583 % | 0.848 | 9 |
| sector | 5 | +0.0014 | +0.13 | 0.900 | 0.986 | [-0.021, +0.023] | -3.553 % | -0.083 | -0.077 | -60.343 % | 14.947 % | 14.769 % | 15.143 % | 0.389 | 456 |
| sector | 20 | -0.0042 | -0.27 | 0.789 | 0.986 | [-0.035, +0.026] | 1.13 % | 0.151 | 0.161 | -41.068 % | 17.585 % | 14.639 % | 15.143 % | 0.698 | 114 |
| sector | 60 | +0.0047 | +0.21 | 0.836 | 0.986 | [-0.040, +0.049] | 4.249 % | 0.323 | 0.423 | -38.64 % | 17.565 % | 14.418 % | 15.143 % | 1.095 | 38 |
| sector | 120 | +0.0381 | +1.25 | 0.212 | 0.986 | [-0.022, +0.098] | 4.439 % | 0.38 | 0.393 | -30.285 % | 17.498 % | 14.537 % | 15.143 % | 1.458 | 19 |
| sector | 252 | -0.0012 | -0.03 | 0.974 | 0.986 | [-0.071, +0.069] | 4.838 % | 0.348 | 0.544 | -26.113 % | 20.837 % | 16.234 % | 15.583 % | 1.483 | 9 |
| all_groups | 5 | -0.0024 | -0.26 | 0.797 | 0.986 | [-0.020, +0.016] | -8.171 % | -0.425 | -0.412 | -68.907 % | 12.46 % | 14.769 % | 15.143 % | 0.272 | 456 |
| all_groups | 20 | -0.0080 | -0.61 | 0.543 | 0.986 | [-0.034, +0.018] | -6.099 % | -0.308 | -0.264 | -58.805 % | 14.015 % | 14.639 % | 15.143 % | 0.506 | 114 |
| all_groups | 60 | -0.0096 | -0.53 | 0.596 | 0.986 | [-0.045, +0.026] | -3.236 % | -0.124 | -0.11 | -54.676 % | 13.991 % | 14.418 % | 15.143 % | 0.895 | 38 |
| all_groups | 120 | +0.0136 | +0.53 | 0.597 | 0.986 | [-0.037, +0.064] | 0.762 % | 0.121 | 0.122 | -25.979 % | 14.231 % | 14.537 % | 15.143 % | 1.159 | 19 |
| all_groups | 252 | -0.0137 | -0.42 | 0.671 | 0.986 | [-0.077, +0.050] | -0.749 % | 0.021 | 0.021 | -42.675 % | 16.506 % | 16.234 % | 15.583 % | 1.333 | 9 |

## Models — strict walk-forward, out-of-sample only

Yearly test folds; each fitted on samples whose outcome was known before the fold (purged), with at least 3 years of history; hyperparameters fixed a priori (no validation set). q = BH within the model tests.

| Model | H | Training (first fold) | OOS period | IC | t | p | q (BH) | AUC | L/S net ann. | L/S Sharpe | L/S Sortino | L/S max DD | Turnover | Baseline (all groups) IC same dates |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| logistic | 5 | 2017-09-01 → 2020-12-18 | 2021-01-05 → 2026-09-30 | +0.0163 | +1.26 | 0.209 | 0.951 | 0.5068 | 0.952 % | 0.143 | 0.144 | -36.748 % | 0.297 | +0.0089 |
| logistic_l2 | 5 | 2017-09-01 → 2020-12-18 | 2021-01-05 → 2026-09-30 | +0.0148 | +1.10 | 0.270 | 0.951 | 0.5057 | 2.195 % | 0.209 | 0.208 | -36.194 % | 0.278 | +0.0089 |
| random_forest | 5 | 2017-09-01 → 2020-12-18 | 2021-01-05 → 2026-09-30 | +0.0188 | +1.26 | 0.206 | 0.951 | 0.5047 | 4.195 % | 0.298 | 0.298 | -40.031 % | 0.237 | +0.0089 |
| logistic | 20 | 2017-09-01 → 2020-11-27 | 2021-01-05 → 2026-09-30 | +0.0154 | +0.73 | 0.467 | 0.951 | 0.504 | 7.313 % | 0.474 | 0.559 | -32.519 % | 0.592 | +0.0102 |
| logistic_l2 | 20 | 2017-09-01 → 2020-11-27 | 2021-01-05 → 2026-09-30 | +0.0102 | +0.48 | 0.632 | 0.951 | 0.5019 | 5.988 % | 0.397 | 0.453 | -31.842 % | 0.547 | +0.0102 |
| random_forest | 20 | 2017-09-01 → 2020-11-27 | 2021-01-05 → 2026-09-30 | +0.0049 | +0.23 | 0.814 | 0.951 | 0.5007 | 2.496 % | 0.223 | 0.242 | -35.837 % | 0.537 | +0.0102 |
| logistic | 60 | 2017-09-01 → 2020-10-01 | 2021-01-05 → 2026-09-30 | +0.0189 | +0.57 | 0.567 | 0.951 | 0.5066 | 4.199 % | 0.302 | 0.367 | -29.904 % | 0.881 | +0.0277 |
| logistic_l2 | 60 | 2017-09-01 → 2020-10-01 | 2021-01-05 → 2026-09-30 | +0.0056 | +0.17 | 0.864 | 0.951 | 0.5002 | 0.511 % | 0.118 | 0.154 | -34.041 % | 0.861 | +0.0277 |
| random_forest | 60 | 2017-09-01 → 2020-10-01 | 2021-01-05 → 2026-09-30 | -0.0238 | -0.68 | 0.497 | 0.951 | 0.4844 | 0.19 % | 0.095 | 0.12 | -38.631 % | 0.762 | +0.0277 |
| logistic | 120 | 2017-09-01 → 2020-07-08 | 2021-01-05 → 2026-09-30 | +0.0095 | +0.20 | 0.844 | 0.951 | 0.5034 | 5.17 % | 0.342 | 0.321 | -30.94 % | 0.879 | +0.0506 |
| logistic_l2 | 120 | 2017-09-01 → 2020-07-08 | 2021-01-05 → 2026-09-30 | -0.0030 | -0.06 | 0.951 | 0.951 | 0.4978 | 3.39 % | 0.257 | 0.268 | -32.587 % | 0.842 | +0.0506 |
| random_forest | 120 | 2017-09-01 → 2020-07-08 | 2021-01-05 → 2026-09-30 | +0.0031 | +0.07 | 0.944 | 0.951 | 0.498 | -1.256 % | 0.034 | 0.037 | -35.745 % | 0.819 | +0.0506 |
| logistic | 252 | 2017-09-01 → 2019-12-31 | 2021-01-05 → 2026-09-30 | -0.0278 | -0.43 | 0.670 | 0.951 | 0.4841 | -2.894 % | -0.11 | -0.12 | -26.073 % | 1.067 | +0.0121 |
| logistic_l2 | 252 | 2017-09-01 → 2019-12-31 | 2021-01-05 → 2026-09-30 | -0.0368 | -0.54 | 0.591 | 0.951 | 0.4807 | -5.143 % | -0.183 | -0.188 | -33.98 % | 1.076 | +0.0121 |
| random_forest | 252 | 2017-09-01 → 2019-12-31 | 2021-01-05 → 2026-09-30 | -0.0442 | -1.17 | 0.243 | 0.951 | 0.4721 | -3.778 % | -0.191 | -0.195 | -23.969 % | 0.929 | +0.0121 |

Gradient boosting: not justified: no simpler model has a BH-significant positive out-of-sample IC.

## Individual features — mean daily rank IC in the pre-registered direction

q = BH within the 155 feature tests.

| Feature | Group | Sign | Basis | H | IC | t | p | q (BH) | Coverage |
|---|---|---|---|---|---|---|---|---|---|
| mom_1m | momentum | -1 | short-term reversal (Jegadeesh 1990) | 5 | +0.0076 | +0.81 | 0.4179 | 0.993 | 100.0 % |
| mom_1m | momentum | -1 | short-term reversal (Jegadeesh 1990) | 20 | +0.0042 | +0.34 | 0.7363 | 0.993 | 100.0 % |
| mom_1m | momentum | -1 | short-term reversal (Jegadeesh 1990) | 60 | +0.0214 | +1.49 | 0.1354 | 0.828 | 100.0 % |
| mom_1m | momentum | -1 | short-term reversal (Jegadeesh 1990) | 120 | +0.0058 | +0.37 | 0.7141 | 0.993 | 100.0 % |
| mom_1m | momentum | -1 | short-term reversal (Jegadeesh 1990) | 252 | -0.0047 | -0.39 | 0.6961 | 0.993 | 100.0 % |
| mom_3m | momentum | +1 | intermediate momentum (Jegadeesh & Titman 1993) | 5 | -0.0170 | -1.80 | 0.0720 | 0.828 | 100.0 % |
| mom_3m | momentum | +1 | intermediate momentum (Jegadeesh & Titman 1993) | 20 | -0.0238 | -1.65 | 0.0998 | 0.828 | 100.0 % |
| mom_3m | momentum | +1 | intermediate momentum (Jegadeesh & Titman 1993) | 60 | -0.0301 | -1.60 | 0.1092 | 0.828 | 100.0 % |
| mom_3m | momentum | +1 | intermediate momentum (Jegadeesh & Titman 1993) | 120 | +0.0047 | +0.20 | 0.8374 | 0.993 | 100.0 % |
| mom_3m | momentum | +1 | intermediate momentum (Jegadeesh & Titman 1993) | 252 | -0.0017 | -0.10 | 0.9218 | 0.993 | 100.0 % |
| mom_6m | momentum | +1 | momentum (Jegadeesh & Titman 1993) | 5 | -0.0027 | -0.25 | 0.8021 | 0.993 | 100.0 % |
| mom_6m | momentum | +1 | momentum (Jegadeesh & Titman 1993) | 20 | -0.0110 | -0.72 | 0.4689 | 0.993 | 100.0 % |
| mom_6m | momentum | +1 | momentum (Jegadeesh & Titman 1993) | 60 | -0.0074 | -0.35 | 0.7246 | 0.993 | 100.0 % |
| mom_6m | momentum | +1 | momentum (Jegadeesh & Titman 1993) | 120 | +0.0242 | +0.92 | 0.3591 | 0.993 | 100.0 % |
| mom_6m | momentum | +1 | momentum (Jegadeesh & Titman 1993) | 252 | -0.0034 | -0.11 | 0.9122 | 0.993 | 100.0 % |
| mom_12_1 | momentum | +1 | 12-1 month momentum (Carhart 1997) | 5 | +0.0083 | +0.71 | 0.4783 | 0.993 | 100.0 % |
| mom_12_1 | momentum | +1 | 12-1 month momentum (Carhart 1997) | 20 | +0.0029 | +0.17 | 0.8616 | 0.993 | 100.0 % |
| mom_12_1 | momentum | +1 | 12-1 month momentum (Carhart 1997) | 60 | +0.0002 | +0.01 | 0.9931 | 0.993 | 100.0 % |
| mom_12_1 | momentum | +1 | 12-1 month momentum (Carhart 1997) | 120 | +0.0174 | +0.57 | 0.5697 | 0.993 | 100.0 % |
| mom_12_1 | momentum | +1 | 12-1 month momentum (Carhart 1997) | 252 | -0.0082 | -0.20 | 0.8386 | 0.993 | 100.0 % |
| risk_adj_mom | momentum | +1 | volatility-scaled momentum (Barroso & Santa-Clara 2015) | 5 | +0.0085 | +0.75 | 0.4555 | 0.993 | 100.0 % |
| risk_adj_mom | momentum | +1 | volatility-scaled momentum (Barroso & Santa-Clara 2015) | 20 | +0.0052 | +0.31 | 0.7533 | 0.993 | 100.0 % |
| risk_adj_mom | momentum | +1 | volatility-scaled momentum (Barroso & Santa-Clara 2015) | 60 | +0.0076 | +0.32 | 0.7521 | 0.993 | 100.0 % |
| risk_adj_mom | momentum | +1 | volatility-scaled momentum (Barroso & Santa-Clara 2015) | 120 | +0.0256 | +0.83 | 0.4045 | 0.993 | 100.0 % |
| risk_adj_mom | momentum | +1 | volatility-scaled momentum (Barroso & Santa-Clara 2015) | 252 | -0.0031 | -0.08 | 0.9343 | 0.993 | 100.0 % |
| vol_3m | market_structure | -1 | low-volatility anomaly (Ang et al. 2006) | 5 | -0.0236 | -1.84 | 0.0661 | 0.828 | 100.0 % |
| vol_3m | market_structure | -1 | low-volatility anomaly (Ang et al. 2006) | 20 | -0.0309 | -1.52 | 0.1276 | 0.828 | 100.0 % |
| vol_3m | market_structure | -1 | low-volatility anomaly (Ang et al. 2006) | 60 | -0.0466 | -1.41 | 0.1574 | 0.828 | 100.0 % |
| vol_3m | market_structure | -1 | low-volatility anomaly (Ang et al. 2006) | 120 | -0.0691 | -1.55 | 0.1215 | 0.828 | 100.0 % |
| vol_3m | market_structure | -1 | low-volatility anomaly (Ang et al. 2006) | 252 | -0.0666 | -1.08 | 0.2799 | 0.924 | 100.0 % |
| beta_1y | market_structure | -1 | betting against beta (Frazzini & Pedersen 2014) | 5 | -0.0303 | -1.95 | 0.0512 | 0.828 | 100.0 % |
| beta_1y | market_structure | -1 | betting against beta (Frazzini & Pedersen 2014) | 20 | -0.0443 | -1.86 | 0.0632 | 0.828 | 100.0 % |
| beta_1y | market_structure | -1 | betting against beta (Frazzini & Pedersen 2014) | 60 | -0.0675 | -1.73 | 0.0830 | 0.828 | 100.0 % |
| beta_1y | market_structure | -1 | betting against beta (Frazzini & Pedersen 2014) | 120 | -0.0833 | -1.56 | 0.1193 | 0.828 | 100.0 % |
| beta_1y | market_structure | -1 | betting against beta (Frazzini & Pedersen 2014) | 252 | -0.0914 | -1.22 | 0.2214 | 0.903 | 100.0 % |
| idio_vol_1y | market_structure | -1 | idiosyncratic volatility puzzle (Ang et al. 2006) | 5 | -0.0150 | -1.47 | 0.1416 | 0.828 | 100.0 % |
| idio_vol_1y | market_structure | -1 | idiosyncratic volatility puzzle (Ang et al. 2006) | 20 | -0.0207 | -1.29 | 0.1955 | 0.842 | 100.0 % |
| idio_vol_1y | market_structure | -1 | idiosyncratic volatility puzzle (Ang et al. 2006) | 60 | -0.0300 | -1.18 | 0.2396 | 0.905 | 100.0 % |
| idio_vol_1y | market_structure | -1 | idiosyncratic volatility puzzle (Ang et al. 2006) | 120 | -0.0357 | -1.04 | 0.2998 | 0.941 | 100.0 % |
| idio_vol_1y | market_structure | -1 | idiosyncratic volatility puzzle (Ang et al. 2006) | 252 | -0.0208 | -0.45 | 0.6553 | 0.993 | 100.0 % |
| log_dollar_volume | market_structure | -1 | illiquidity premium (Amihud 2002) | 5 | -0.0044 | -0.62 | 0.5320 | 0.993 | 100.0 % |
| log_dollar_volume | market_structure | -1 | illiquidity premium (Amihud 2002) | 20 | -0.0010 | -0.10 | 0.9214 | 0.993 | 100.0 % |
| log_dollar_volume | market_structure | -1 | illiquidity premium (Amihud 2002) | 60 | -0.0014 | -0.09 | 0.9281 | 0.993 | 100.0 % |
| log_dollar_volume | market_structure | -1 | illiquidity premium (Amihud 2002) | 120 | -0.0011 | -0.04 | 0.9671 | 0.993 | 100.0 % |
| log_dollar_volume | market_structure | -1 | illiquidity premium (Amihud 2002) | 252 | +0.0199 | +0.45 | 0.6510 | 0.993 | 100.0 % |
| volume_trend | market_structure | -1 | high turnover, lower returns (Lee & Swaminathan 2000) | 5 | -0.0020 | -0.37 | 0.7086 | 0.993 | 100.0 % |
| volume_trend | market_structure | -1 | high turnover, lower returns (Lee & Swaminathan 2000) | 20 | -0.0008 | -0.10 | 0.9177 | 0.993 | 100.0 % |
| volume_trend | market_structure | -1 | high turnover, lower returns (Lee & Swaminathan 2000) | 60 | -0.0093 | -0.89 | 0.3715 | 0.993 | 100.0 % |
| volume_trend | market_structure | -1 | high turnover, lower returns (Lee & Swaminathan 2000) | 120 | -0.0136 | -1.37 | 0.1713 | 0.830 | 100.0 % |
| volume_trend | market_structure | -1 | high turnover, lower returns (Lee & Swaminathan 2000) | 252 | -0.0130 | -1.24 | 0.2140 | 0.897 | 100.0 % |
| dist_high_1y | market_structure | +1 | 52-week-high momentum (George & Hwang 2004) | 5 | -0.0097 | -0.89 | 0.3738 | 0.993 | 100.0 % |
| dist_high_1y | market_structure | +1 | 52-week-high momentum (George & Hwang 2004) | 20 | -0.0182 | -1.08 | 0.2802 | 0.924 | 100.0 % |
| dist_high_1y | market_structure | +1 | 52-week-high momentum (George & Hwang 2004) | 60 | -0.0245 | -1.12 | 0.2628 | 0.905 | 100.0 % |
| dist_high_1y | market_structure | +1 | 52-week-high momentum (George & Hwang 2004) | 120 | -0.0047 | -0.18 | 0.8588 | 0.993 | 100.0 % |
| dist_high_1y | market_structure | +1 | 52-week-high momentum (George & Hwang 2004) | 252 | -0.0070 | -0.19 | 0.8479 | 0.993 | 100.0 % |
| log_market_cap | market_structure | -1 | size effect (Banz 1981; Fama & French 1993) | 5 | +0.0024 | +0.35 | 0.7233 | 0.993 | 98.9 % |
| log_market_cap | market_structure | -1 | size effect (Banz 1981; Fama & French 1993) | 20 | +0.0071 | +0.63 | 0.5303 | 0.993 | 98.9 % |
| log_market_cap | market_structure | -1 | size effect (Banz 1981; Fama & French 1993) | 60 | +0.0125 | +0.70 | 0.4824 | 0.993 | 98.9 % |
| log_market_cap | market_structure | -1 | size effect (Banz 1981; Fama & French 1993) | 120 | +0.0113 | +0.43 | 0.6703 | 0.993 | 98.9 % |
| log_market_cap | market_structure | -1 | size effect (Banz 1981; Fama & French 1993) | 252 | +0.0292 | +0.74 | 0.4570 | 0.993 | 98.9 % |
| gross_profitability | quality | +1 | gross profits / assets (Novy-Marx 2013) | 5 | +0.0012 | +0.18 | 0.8562 | 0.993 | 71.5 % |
| gross_profitability | quality | +1 | gross profits / assets (Novy-Marx 2013) | 20 | -0.0036 | -0.34 | 0.7352 | 0.993 | 71.5 % |
| gross_profitability | quality | +1 | gross profits / assets (Novy-Marx 2013) | 60 | -0.0083 | -0.47 | 0.6404 | 0.993 | 71.5 % |
| gross_profitability | quality | +1 | gross profits / assets (Novy-Marx 2013) | 120 | -0.0044 | -0.16 | 0.8733 | 0.993 | 71.5 % |
| gross_profitability | quality | +1 | gross profits / assets (Novy-Marx 2013) | 252 | +0.0004 | +0.01 | 0.9933 | 0.993 | 71.5 % |
| operating_margin | quality | +1 | profitability (Fama & French 2015, RMW) | 5 | +0.0012 | +0.19 | 0.8465 | 0.993 | 86.7 % |
| operating_margin | quality | +1 | profitability (Fama & French 2015, RMW) | 20 | +0.0021 | +0.21 | 0.8339 | 0.993 | 86.7 % |
| operating_margin | quality | +1 | profitability (Fama & French 2015, RMW) | 60 | -0.0004 | -0.02 | 0.9806 | 0.993 | 86.7 % |
| operating_margin | quality | +1 | profitability (Fama & French 2015, RMW) | 120 | +0.0057 | +0.28 | 0.7783 | 0.993 | 86.7 % |
| operating_margin | quality | +1 | profitability (Fama & French 2015, RMW) | 252 | +0.0031 | +0.15 | 0.8840 | 0.993 | 86.7 % |
| roe | quality | +1 | return on equity (Fama & French 2015; Hou, Xue & Zhang 2015) | 5 | +0.0058 | +0.86 | 0.3908 | 0.993 | 87.3 % |
| roe | quality | +1 | return on equity (Fama & French 2015; Hou, Xue & Zhang 2015) | 20 | +0.0062 | +0.57 | 0.5679 | 0.993 | 87.3 % |
| roe | quality | +1 | return on equity (Fama & French 2015; Hou, Xue & Zhang 2015) | 60 | +0.0099 | +0.60 | 0.5477 | 0.993 | 87.3 % |
| roe | quality | +1 | return on equity (Fama & French 2015; Hou, Xue & Zhang 2015) | 120 | +0.0138 | +0.64 | 0.5196 | 0.993 | 87.3 % |
| roe | quality | +1 | return on equity (Fama & French 2015; Hou, Xue & Zhang 2015) | 252 | +0.0104 | +0.35 | 0.7268 | 0.993 | 87.3 % |
| roa | quality | +1 | return on assets (Haugen & Baker 1996) | 5 | +0.0058 | +0.81 | 0.4207 | 0.993 | 94.3 % |
| roa | quality | +1 | return on assets (Haugen & Baker 1996) | 20 | +0.0071 | +0.59 | 0.5563 | 0.993 | 94.3 % |
| roa | quality | +1 | return on assets (Haugen & Baker 1996) | 60 | +0.0074 | +0.38 | 0.7036 | 0.993 | 94.3 % |
| roa | quality | +1 | return on assets (Haugen & Baker 1996) | 120 | +0.0106 | +0.38 | 0.7054 | 0.993 | 94.3 % |
| roa | quality | +1 | return on assets (Haugen & Baker 1996) | 252 | +0.0012 | +0.03 | 0.9775 | 0.993 | 94.3 % |
| fcf_margin | quality | +1 | cash profitability (Ball et al. 2016) | 5 | +0.0100 | +1.42 | 0.1562 | 0.828 | 75.3 % |
| fcf_margin | quality | +1 | cash profitability (Ball et al. 2016) | 20 | +0.0166 | +1.52 | 0.1282 | 0.828 | 75.3 % |
| fcf_margin | quality | +1 | cash profitability (Ball et al. 2016) | 60 | +0.0209 | +1.13 | 0.2595 | 0.905 | 75.3 % |
| fcf_margin | quality | +1 | cash profitability (Ball et al. 2016) | 120 | +0.0320 | +1.30 | 0.1935 | 0.842 | 75.3 % |
| fcf_margin | quality | +1 | cash profitability (Ball et al. 2016) | 252 | +0.0304 | +1.13 | 0.2574 | 0.905 | 75.3 % |
| accruals | quality | -1 | accrual anomaly (Sloan 1996) | 5 | +0.0073 | +1.31 | 0.1900 | 0.842 | 93.4 % |
| accruals | quality | -1 | accrual anomaly (Sloan 1996) | 20 | +0.0120 | +1.39 | 0.1653 | 0.828 | 93.4 % |
| accruals | quality | -1 | accrual anomaly (Sloan 1996) | 60 | +0.0209 | +1.57 | 0.1161 | 0.828 | 93.4 % |
| accruals | quality | -1 | accrual anomaly (Sloan 1996) | 120 | +0.0372 | +2.05 | 0.0406 | 0.828 | 93.4 % |
| accruals | quality | -1 | accrual anomaly (Sloan 1996) | 252 | +0.0544 | +2.87 | 0.0041 | 0.634 | 93.4 % |
| debt_to_equity | quality | -1 | balance-sheet quality (Asness, Frazzini & Pedersen 2019) | 5 | +0.0070 | +1.03 | 0.3036 | 0.941 | 82.9 % |
| debt_to_equity | quality | -1 | balance-sheet quality (Asness, Frazzini & Pedersen 2019) | 20 | +0.0118 | +1.12 | 0.2605 | 0.905 | 82.9 % |
| debt_to_equity | quality | -1 | balance-sheet quality (Asness, Frazzini & Pedersen 2019) | 60 | +0.0138 | +0.82 | 0.4146 | 0.993 | 82.9 % |
| debt_to_equity | quality | -1 | balance-sheet quality (Asness, Frazzini & Pedersen 2019) | 120 | +0.0094 | +0.36 | 0.7181 | 0.993 | 82.9 % |
| debt_to_equity | quality | -1 | balance-sheet quality (Asness, Frazzini & Pedersen 2019) | 252 | +0.0052 | +0.15 | 0.8828 | 0.993 | 82.9 % |
| revenue_growth | growth | +1 | sales growth persistence (hypothesis; evidence mixed) | 5 | +0.0126 | +1.42 | 0.1552 | 0.828 | 94.1 % |
| revenue_growth | growth | +1 | sales growth persistence (hypothesis; evidence mixed) | 20 | +0.0110 | +0.74 | 0.4574 | 0.993 | 94.1 % |
| revenue_growth | growth | +1 | sales growth persistence (hypothesis; evidence mixed) | 60 | +0.0128 | +0.50 | 0.6141 | 0.993 | 94.1 % |
| revenue_growth | growth | +1 | sales growth persistence (hypothesis; evidence mixed) | 120 | +0.0269 | +0.80 | 0.4238 | 0.993 | 94.1 % |
| revenue_growth | growth | +1 | sales growth persistence (hypothesis; evidence mixed) | 252 | +0.0405 | +0.94 | 0.3481 | 0.993 | 94.1 % |
| eps_growth | growth | +1 | earnings momentum (Chan, Jegadeesh & Lakonishok 1996) | 5 | +0.0062 | +0.95 | 0.3436 | 0.993 | 90.2 % |
| eps_growth | growth | +1 | earnings momentum (Chan, Jegadeesh & Lakonishok 1996) | 20 | +0.0038 | +0.35 | 0.7223 | 0.993 | 90.2 % |
| eps_growth | growth | +1 | earnings momentum (Chan, Jegadeesh & Lakonishok 1996) | 60 | +0.0018 | +0.09 | 0.9292 | 0.993 | 90.2 % |
| eps_growth | growth | +1 | earnings momentum (Chan, Jegadeesh & Lakonishok 1996) | 120 | +0.0006 | +0.02 | 0.9857 | 0.993 | 90.2 % |
| eps_growth | growth | +1 | earnings momentum (Chan, Jegadeesh & Lakonishok 1996) | 252 | -0.0154 | -0.34 | 0.7330 | 0.993 | 90.2 % |
| fcf_growth | growth | +1 | cash-flow growth (hypothesis) | 5 | +0.0113 | +1.53 | 0.1249 | 0.828 | 71.4 % |
| fcf_growth | growth | +1 | cash-flow growth (hypothesis) | 20 | +0.0161 | +1.32 | 0.1873 | 0.842 | 71.4 % |
| fcf_growth | growth | +1 | cash-flow growth (hypothesis) | 60 | +0.0166 | +0.77 | 0.4423 | 0.993 | 71.4 % |
| fcf_growth | growth | +1 | cash-flow growth (hypothesis) | 120 | +0.0247 | +0.75 | 0.4554 | 0.993 | 71.4 % |
| fcf_growth | growth | +1 | cash-flow growth (hypothesis) | 252 | +0.0248 | +0.59 | 0.5570 | 0.993 | 71.4 % |
| asset_growth | growth | -1 | asset growth anomaly (Cooper, Gulen & Schill 2008) | 5 | -0.0148 | -2.45 | 0.0143 | 0.828 | 98.4 % |
| asset_growth | growth | -1 | asset growth anomaly (Cooper, Gulen & Schill 2008) | 20 | -0.0176 | -1.80 | 0.0722 | 0.828 | 98.4 % |
| asset_growth | growth | -1 | asset growth anomaly (Cooper, Gulen & Schill 2008) | 60 | -0.0257 | -1.64 | 0.1010 | 0.828 | 98.4 % |
| asset_growth | growth | -1 | asset growth anomaly (Cooper, Gulen & Schill 2008) | 120 | -0.0239 | -1.06 | 0.2882 | 0.931 | 98.4 % |
| asset_growth | growth | -1 | asset growth anomaly (Cooper, Gulen & Schill 2008) | 252 | -0.0126 | -0.38 | 0.7041 | 0.993 | 98.4 % |
| earnings_yield | value | +1 | E/P (Basu 1977) | 5 | -0.0055 | -0.76 | 0.4469 | 0.993 | 94.3 % |
| earnings_yield | value | +1 | E/P (Basu 1977) | 20 | -0.0070 | -0.63 | 0.5270 | 0.993 | 94.3 % |
| earnings_yield | value | +1 | E/P (Basu 1977) | 60 | -0.0127 | -0.70 | 0.4826 | 0.993 | 94.3 % |
| earnings_yield | value | +1 | E/P (Basu 1977) | 120 | -0.0308 | -1.60 | 0.1099 | 0.828 | 94.3 % |
| earnings_yield | value | +1 | E/P (Basu 1977) | 252 | -0.0488 | -1.92 | 0.0547 | 0.828 | 94.3 % |
| sales_to_ev | value | +1 | EV/sales, inverted (value; Loughran & Wellman 2011 for EBITDA/EV) | 5 | -0.0044 | -0.50 | 0.6170 | 0.993 | 87.3 % |
| sales_to_ev | value | +1 | EV/sales, inverted (value; Loughran & Wellman 2011 for EBITDA/EV) | 20 | -0.0009 | -0.07 | 0.9470 | 0.993 | 87.3 % |
| sales_to_ev | value | +1 | EV/sales, inverted (value; Loughran & Wellman 2011 for EBITDA/EV) | 60 | +0.0016 | +0.07 | 0.9453 | 0.993 | 87.3 % |
| sales_to_ev | value | +1 | EV/sales, inverted (value; Loughran & Wellman 2011 for EBITDA/EV) | 120 | -0.0100 | -0.33 | 0.7411 | 0.993 | 87.3 % |
| sales_to_ev | value | +1 | EV/sales, inverted (value; Loughran & Wellman 2011 for EBITDA/EV) | 252 | -0.0009 | -0.02 | 0.9827 | 0.993 | 87.3 % |
| fcf_yield | value | +1 | cash-flow yield (Lakonishok, Shleifer & Vishny 1994) | 5 | -0.0015 | -0.20 | 0.8450 | 0.993 | 76.8 % |
| fcf_yield | value | +1 | cash-flow yield (Lakonishok, Shleifer & Vishny 1994) | 20 | +0.0053 | +0.46 | 0.6426 | 0.993 | 76.8 % |
| fcf_yield | value | +1 | cash-flow yield (Lakonishok, Shleifer & Vishny 1994) | 60 | +0.0115 | +0.64 | 0.5253 | 0.993 | 76.8 % |
| fcf_yield | value | +1 | cash-flow yield (Lakonishok, Shleifer & Vishny 1994) | 120 | +0.0133 | +0.58 | 0.5648 | 0.993 | 76.8 % |
| fcf_yield | value | +1 | cash-flow yield (Lakonishok, Shleifer & Vishny 1994) | 252 | +0.0233 | +0.74 | 0.4565 | 0.993 | 76.8 % |
| ebitda_to_ev | value | +1 | enterprise multiple, inverted (Loughran & Wellman 2011) | 5 | -0.0016 | -0.17 | 0.8674 | 0.993 | 70.0 % |
| ebitda_to_ev | value | +1 | enterprise multiple, inverted (Loughran & Wellman 2011) | 20 | -0.0005 | -0.03 | 0.9725 | 0.993 | 70.0 % |
| ebitda_to_ev | value | +1 | enterprise multiple, inverted (Loughran & Wellman 2011) | 60 | -0.0015 | -0.06 | 0.9517 | 0.993 | 70.0 % |
| ebitda_to_ev | value | +1 | enterprise multiple, inverted (Loughran & Wellman 2011) | 120 | -0.0166 | -0.52 | 0.6044 | 0.993 | 70.0 % |
| ebitda_to_ev | value | +1 | enterprise multiple, inverted (Loughran & Wellman 2011) | 252 | -0.0172 | -0.38 | 0.7016 | 0.993 | 70.0 % |
| book_to_market | value | +1 | B/M (Fama & French 1992) | 5 | -0.0109 | -1.40 | 0.1625 | 0.828 | 98.9 % |
| book_to_market | value | +1 | B/M (Fama & French 1992) | 20 | -0.0139 | -1.19 | 0.2331 | 0.903 | 98.9 % |
| book_to_market | value | +1 | B/M (Fama & French 1992) | 60 | -0.0251 | -1.20 | 0.2297 | 0.903 | 98.9 % |
| book_to_market | value | +1 | B/M (Fama & French 1992) | 120 | -0.0443 | -1.39 | 0.1657 | 0.828 | 98.9 % |
| book_to_market | value | +1 | B/M (Fama & French 1992) | 252 | -0.0601 | -1.48 | 0.1386 | 0.828 | 98.9 % |
| earnings_yield_vs_sector | value | +1 | within-industry value (Asness, Porter & Stevens 2000) | 5 | -0.0002 | -0.03 | 0.9773 | 0.993 | 94.3 % |
| earnings_yield_vs_sector | value | +1 | within-industry value (Asness, Porter & Stevens 2000) | 20 | -0.0007 | -0.07 | 0.9403 | 0.993 | 94.3 % |
| earnings_yield_vs_sector | value | +1 | within-industry value (Asness, Porter & Stevens 2000) | 60 | -0.0027 | -0.18 | 0.8595 | 0.993 | 94.3 % |
| earnings_yield_vs_sector | value | +1 | within-industry value (Asness, Porter & Stevens 2000) | 120 | -0.0131 | -0.69 | 0.4894 | 0.993 | 94.3 % |
| earnings_yield_vs_sector | value | +1 | within-industry value (Asness, Porter & Stevens 2000) | 252 | -0.0358 | -1.40 | 0.1616 | 0.828 | 94.3 % |
| sector_mom_6m | sector | +1 | industry momentum (Moskowitz & Grinblatt 1999) | 5 | +0.0060 | +0.56 | 0.5758 | 0.993 | 100.0 % |
| sector_mom_6m | sector | +1 | industry momentum (Moskowitz & Grinblatt 1999) | 20 | +0.0046 | +0.31 | 0.7586 | 0.993 | 100.0 % |
| sector_mom_6m | sector | +1 | industry momentum (Moskowitz & Grinblatt 1999) | 60 | +0.0205 | +0.99 | 0.3222 | 0.979 | 100.0 % |
| sector_mom_6m | sector | +1 | industry momentum (Moskowitz & Grinblatt 1999) | 120 | +0.0536 | +1.79 | 0.0738 | 0.828 | 100.0 % |
| sector_mom_6m | sector | +1 | industry momentum (Moskowitz & Grinblatt 1999) | 252 | -0.0013 | -0.04 | 0.9709 | 0.993 | 100.0 % |
| mom_6m_vs_sector | sector | +1 | within-industry momentum (Asness, Porter & Stevens 2000) | 5 | -0.0028 | -0.35 | 0.7286 | 0.993 | 100.0 % |
| mom_6m_vs_sector | sector | +1 | within-industry momentum (Asness, Porter & Stevens 2000) | 20 | -0.0078 | -0.66 | 0.5085 | 0.993 | 100.0 % |
| mom_6m_vs_sector | sector | +1 | within-industry momentum (Asness, Porter & Stevens 2000) | 60 | -0.0118 | -0.68 | 0.4988 | 0.993 | 100.0 % |
| mom_6m_vs_sector | sector | +1 | within-industry momentum (Asness, Porter & Stevens 2000) | 120 | +0.0014 | +0.06 | 0.9496 | 0.993 | 100.0 % |
| mom_6m_vs_sector | sector | +1 | within-industry momentum (Asness, Porter & Stevens 2000) | 252 | -0.0002 | -0.01 | 0.9924 | 0.993 | 100.0 % |
