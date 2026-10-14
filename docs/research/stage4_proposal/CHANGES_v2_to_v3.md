# Stage 4 proposal: changes from v2 to v3 (2026-10-14)

**Files.** v1 and v2 are kept unchanged:

| Version | File | SHA-256 |
|---|---|---|
| v1 | `STAGE4_PREREGISTRATION_PROPOSAL_v1.md` | `d4c42d9918a5df9cc62210436af81a5a4691b4ede33980275abd73dfca43372f` |
| v2 | `STAGE4_PREREGISTRATION_PROPOSAL_v2.md` | `65b95d4c58eb3cb92ccc4a5ef5a055b5420281a1ed3b8cfad97f3c040afc644b` (commit 8971b80) |
| v3 | `STAGE4_PREREGISTRATION_PROPOSAL_v3.md` | submitted for approval |

**Why.** The owner's second clarification request of 2026-10-14 covered five points: classification without
release times, the A1 assumption, the statistical consequences of timestamp errors, the after-close gate, and the
smallest necessary correction.

**Status.** Nothing was run. No price was downloaded and no outcome was computed.

**New data read (filings only).** `feasibility_v3.py` timed a seeded subset of 300 of the v1 feasibility events on
their EDGAR index pages and read the cover-page `reportDate` from the SEC feed. Results are in
`feasibility_v3.json`.

**New files.**
- `timing_rule.py`: the reference implementation of the rule, with no network access.
- `tests/test_p78_stage4_timing_rule.py`: tests of the rule on a synthetic calendar and on XNYS.

## Unchanged

- The research question, H1 and H0, the 40-session horizon, the universe, the period, the primary statistic and
  its test (section 11), and the four verdicts.
- The validity minima (10,000 events; 32 quarters with at least 100) and the exploratory family E1–E5 under Holm.
- Gate G2, the 5% and 20% study-level thresholds, and the costs.
- Gates G1a and G1c.

## Changed: the smallest correction found

| # | Owner's point | v2 | v3 | Section |
|---|---|---|---|---|
| 1 | Classification without release times | Anchor t_A; the announcement day came only from the exhibit 99 dateline, detected for about half of events. Without a dateline, assumption A1 was used. | The announcement day D_R is the earlier of the 8-K cover-page `reportDate` (present for every event) and the dateline. The release lies in I = [00:00 of D_R, t_A]. Six classes are defined by whether trading hours fall inside I. 13 hypothetical worked examples are computed by the reference code. | 4, 5 |
| 2 | A1 | Applied to every event (PRE, POST and undetected datelines) | Only POST events need A1, and they are **excluded from the primary test** (descriptive only, labelled "timing unverified"). The primary set relies on A2 only: the announcement was not made before the company's own stated announcement date. The audit checks A2. | 4 |
| 3 | Statistical consequences | "Misalignment can only attenuate" | **Withdrawn.** Timing errors cannot create look-ahead and are one-sided in time (always "public earlier than assumed"). But the bias on the correlation is about π·(ρ_M − ρ_A) and can have either sign. Attenuation holds only under classical errors-in-variables, which serial correlation of returns around announcements violates. | 13 |
| 4 | After-close gate | G1b-POST: a class-level exclusion decided from about 30 audited POST events, unable to identify affected events individually and imprecise (2 of 30 gives a 95% upper bound near 20%) | **Removed.** POST events are excluded a priori; this is the conservative rule. The audit now samples only primary-set events. | 13 |
| 5 | Validity gate | G1b: INVALID above 10% misaligned | G1b: INVALID if 2 or more of 100 audited events are misaligned (one-sided 95% upper bound of π above 5%). With the stated assumption \|ρ_M − ρ_A\| ≤ 0.20, the bias is then at most 0.010, under half the detectable effect. | 13 |
| — | Feasibility and power | About 15,900 events; detectable effect 0.023–0.039 | Primary set about 57% of candidates (172 of 300): about 9,100 events (95% interval 8,200–10,000) before price exclusions. Detectable effect 0.030–0.045. | 2, 10 |
| — | Consequence for the verdict | — | With the unchanged 10,000 minimum, the expected outcome is INSUFFICIENT DATA. Three options are given for the owner (A: freeze as is; B: a v4 replacing the total minimum with a precision criterion; C: obtain licensed release times). None is applied. | 15 |

## What remains assumed

- **A2.** The company's cover-page announcement date and press-release dateline are not later than the actual
  release day. Bounded by the audit.
- **|ρ_M − ρ_A| ≤ 0.20.** Used only to translate the audit bound into a bias bound. Stated as an assumption.
- **EDGAR dissemination at acceptance.** The 8-K is public at t_A.
