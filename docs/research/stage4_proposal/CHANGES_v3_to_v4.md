# Stage 4 proposal: changes from v3 to v4 (2026-10-14)

## Version history (all kept unchanged)

| Version | File | SHA-256 | What it settled |
|---|---|---|---|
| v1 (2026-10-12) | `STAGE4_PREREGISTRATION_PROPOSAL_v1.md` | `d4c42d9918a5df9cc62210436af81a5a4691b4ede33980275abd73dfca43372f` | Question, hypothesis, 40-session horizon, universe, period, statistic, verdicts |
| v2 (2026-10-14) | `STAGE4_PREREGISTRATION_PROPOSAL_v2.md` | `65b95d4c58eb3cb92ccc4a5ef5a055b5420281a1ed3b8cfad97f3c040afc644b` | Timestamps vs sessions, intraday exclusion, alignment audit, exact test (`CHANGES_v1_to_v2.md`) |
| v3 (2026-10-14) | `STAGE4_PREREGISTRATION_PROPOSAL_v3.md` | `3033bcf68bb3c50369a9710c4ec5fe083d364dc2d52af16880578fbca46b9d2b` | SEC-verified alignment only, two-sided bias of timing errors, stricter audit gate (`CHANGES_v2_to_v3.md`) |
| v4 (2026-10-14) | `STAGE4_PREREGISTRATION_PROPOSAL_v4.md` | given in the commit and the owner's report | Sample-size and precision rule, power, corrected standard error (this file) |

**Why v4.**
- The owner chose option B of v3 section 15, with eight requirements:
  - preserve the hypotheses, horizon, universe, period, benchmark, statistic and verdicts;
  - replace the 10,000-event minimum with a justified rule based on counts and assumptions only;
  - document power, the detectable effect, α and the assumptions;
  - evaluate the power of the actual test;
  - state any power limitation;
  - keep v1–v3;
  - download no price;
  - do not touch the signal, stage 3 or PT1.

**Status.**
- Nothing was run: no price was downloaded and no outcome was computed.
- The only new computation is `power_v4.py`. Its inputs are the event counts of `feasibility.json` and
  `feasibility_v3.json`, and its simulations use synthetic data.

## Unchanged

- H1, H0, the 40-session horizon, the universe (S&P 500 list, frozen at approval), the 2016–2025 period, the SPY
  benchmark, and the primary statistic ρ̄ (the mean of quarterly Spearman correlations).
- The four verdicts and their sign rules.
- Events, timestamps, the timing rule and classes, windows, entry and exclusions (sections 2–9, except one pointer
  added in section 2).
- Gates G1a, G1b and G1c, gate G2 and the study-level thresholds.
- The exploratory family E1–E5 under Holm, and the costs.

## Changed

| # | Requirement | v3 | v4 | Section |
|---|---|---|---|---|
| 1 | Replace the arbitrary minimum | At least 10,000 eligible events in total, plus at least 32 quarters with 100 or more events | **10,000 total removed.** V1 (kept): at least 32 quarters with 100 or more events, now justified by simulation. **V2 (new): planned 95% CI half-width ≤ δ* = 0.03**, computed from the realized per-quarter counts under fixed planning assumptions. It is evaluated twice, on counts only: a pre-check on SEC-only counts before the audit and any price, and a final check after all exclusions, before any EAR, DRIFT or correlation. | 10, order of execution |
| 2 | Justified threshold | — | h ≤ δ* gives about 50% power at δ*, and at least a 50% chance of excluding δ* when the truth is 0 (Rothman & Greenland, 2018). Equivalent to about 221 events per quarter (8,840 in total). | 10 |
| 3 | Power, detectable effect, α, assumptions | Detectable effect 0.030–0.045; power 0.29 / 0.56 / 0.81 at 0.02 / 0.03 / 0.04 (analytic, test of v1–v3) | Effect of interest δ* = 0.03, fixed now; α = 0.05 two-sided; the planning assumptions are listed with their sensitivity ranges. Analytic power of the corrected test at the planning counts: 0.26 / **0.50** / 0.74 / 0.91 at 0.02 / 0.03 / 0.04 / 0.05. Simulated: 0.28 / **0.53** / 0.77 / 0.92. 80%-power detectable effect 0.043 (0.033–0.054 across scenarios). **Power at 0.03 is only about 50–56%.** | 10 |
| 4 | Power of the actual test | Total-events heuristic | Computed from per-quarter counts with the HAC structure and the degrees of freedom of the test, then checked by Monte Carlo of the exact procedure: per-quarter Spearman on synthetic pairs, the mean, the HAC SE and Student t. | 10, `power_v4.py` |
| 4b | (found by 4) **Standard error** | Newey–West, Bartlett, lag 1: (γ̂_0 + γ̂_1)/M with t(M − 1). **Simulated false-positive rate 0.084 under the protocol's own dependence assumption** (0.054–0.065 with no dependence). | Lag-1 HAC with truncated kernel, γ̂_1 floored at 0, × M/(M − 2), with t(⌊M/2⌋ − 1). The CI uses the same SE and t. Simulated false-positive rate 0.052 (planning), 0.050 with 32 quarters, 0.029–0.037 with no dependence; 0.059–0.092 under persistent AR(1) stress. The corrections were calibrated on synthetic data before any outcome. **Needs the owner's explicit approval.** The v1–v3 test can be kept instead, though this is not recommended. | 11, 12 |
| 5 | State the limitation | — | Section 10 "Power limitation": adequate power for δ* is not achievable. NOT SUPPORTED does not exclude an effect of 0.03, and the CI is reported against δ*. V2 is expected to be met only at the margin (h = 0.0303 at the planning counts), so INSUFFICIENT DATA has roughly even odds. V2 will not be relaxed. | 10, 14, 15, risks 2 and 11 |
| — | Wording that depended on the old detectable effect | The bias bound was compared with "the detectable effect (0.030)" | Compared with δ* = 0.03 and with the 80%-power detectable effect of 0.043. The numbers of the bound are unchanged. | 13 |
| — | Verdict table | "A gate or minimum fails" | "A gate fails (INVALID) or V1 / V2 fails (INSUFFICIENT DATA)". NOT SUPPORTED also reports whether the CI excludes 0.03. | 14 |
| — | Section 15 | v3's options A, B and C | Testability under v4: alignment for a subset, expected counts, V2 at the margin, power limitation | 15 |
| — | Risks | — | Risk 2 rewritten (power and odds of INSUFFICIENT DATA). Risk 11 added (calibration of the test; persistent dependence). | Risks |

## Expected sample (from counts; `power_v4.json`)

| Scenario | Events | Per quarter | V2 half-width | Power at 0.03 |
|---|---|---|---|---|
| Central share 57.3%, 5% price exclusions (planning) | 8,664 | 183–248 (mean 217) | 0.0303 (fails by 0.0003) | 0.50 |
| Central share, 0% exclusions | 9,124 | 192–261 | 0.0297 (passes) | 0.52 |
| Share 95% bounds 51.7–62.9%, exclusions 0–10% | 7,412–10,016 | 156–287 | 0.0286–0.0324 | 0.45–0.55 |

## Owner decisions requested before freezing

1. Approve v4 as written, including the corrected standard error of section 11.
2. Or approve v4 with the v1–v3 standard error. That test gives about 8% false positives under the planning
   dependence. It would become v5, with its own change log.
3. Or do not freeze.

After an explicit approval:
- the approved text is copied to `docs/research/STAGE4_PREREGISTRATION.md` and committed with its SHA-256;
- `exchange_calendars` is pinned;
- the SEC-only event table is built, and the V1 / V2 pre-check runs, all before any price download.
