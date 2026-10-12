# Heuristic signal: descriptive evaluation on the walk-forward sample

Computed 2026-10-12T07:49:31+00:00 by `python main.py evaluate-heuristic` from `reports/walk_forward.json` (walk-forward computed 2026-10-07T09:15:12+00:00, sha256 98e1f88fc6856500e71a1971c85bb1f71efdbda92ed63369bc1eed4995610f0e).

**Nature**: descriptive, in-sample of one walk-forward run; nothing fitted; no new hypothesis tested; the confirmatory evidence is the walk-forward criterion and the pre-registered stage 3 test.

Sample: 40 tickers, 8800 observations (8800 with a combined score), 220 dates from 2022-05-12 to 2026-09-24. Costs: 10.0 bps per unit of turnover; risk-free rate 0. Biases: universe chosen in 2026 (current large caps): selection and survivorship bias; no delisted company; adjusted prices of the current vintage; ex-news combined score (the news lexicon has no history and is not validated).

## Horizon 5d

- Label POSITIVE as a prediction of a positive return: precision 0.54 vs base rate 0.532, recall 0.1933, F1 0.2847; AUC of the score 0.4987.
- As a prediction of beating the cross-sectional median: precision 0.5095 (base rate 0.5), AUC 0.5066.
- Probabilities: NOT CALIBRATED: the heuristic outputs a 0-100 score, not a probability (Brier score and calibration not applicable).

| portfolio | periods | annualised return | volatility | Sharpe | Sortino | max drawdown |
|---|---|---|---|---|---|---|
| long only top quintile net | 220 | +25.98% | +27.81% | 0.972 | 0.938 | -27.29% |
| long short net | 220 | -3.23% | +21.82% | -0.041 | -0.041 | -36.33% |
| long only net minus equal weight | 220 | -2.85% | +13.41% | -0.149 | -0.152 | -24.69% |
| benchmark equal weight universe | 220 | +30.36% | +22.04% | 1.316 | 1.286 | -21.27% |
| benchmark spy | 220 | +17.68% | +15.63% | 1.121 | 1.085 | -16.88% |

Mean turnover per rebalance 0.719; rebalancing every 5 sessions.

## Horizon 20d

- Label POSITIVE as a prediction of a positive return: precision 0.5331 vs base rate 0.5515, recall 0.1834, F1 0.2729; AUC of the score 0.4944.
- As a prediction of beating the cross-sectional median: precision 0.5058 (base rate 0.5), AUC 0.508.
- Probabilities: NOT CALIBRATED: the heuristic outputs a 0-100 score, not a probability (Brier score and calibration not applicable).

| portfolio | periods | annualised return | volatility | Sharpe | Sortino | max drawdown |
|---|---|---|---|---|---|---|
| long only top quintile net | 55 | +28.41% | +26.88% | 1.067 | 1.46 | -21.55% |
| long short net | 55 | -5.31% | +17.76% | -0.22 | -0.236 | -25.80% |
| long only net minus equal weight | 55 | -1.85% | +12.05% | -0.095 | -0.09 | -14.76% |
| benchmark equal weight universe | 55 | +31.09% | +22.76% | 1.311 | 1.661 | -13.22% |
| benchmark spy | 55 | +17.68% | +14.70% | 1.186 | 1.276 | -11.30% |

Mean turnover per rebalance 0.914; rebalancing every 20 sessions.

These figures describe one historical run of a heuristic whose weights were never fitted. They are not evidence of a future edge: see the validation status and the stage 3 pre-registration.
