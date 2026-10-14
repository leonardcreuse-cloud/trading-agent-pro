# Stage 4 proposal: changes from v1 to v2 (2026-10-14)

**Files.**
- `STAGE4_PREREGISTRATION_PROPOSAL_v1.md` (`stage4-proposal-v1`, 2026-10-12): unchanged, renamed from
  `STAGE4_PREREGISTRATION_PROPOSAL.md`. SHA-256 `d4c42d9918a5df9cc62210436af81a5a4691b4ede33980275abd73dfca43372f`,
  identical to commit 72bd52b.
- `STAGE4_PREREGISTRATION_PROPOSAL_v2.md` (`stage4-proposal-v2`, 2026-10-14): the version submitted for approval.

**Why.** The owner's clarification request of 2026-10-14 covered seven points: timestamps and trading sessions,
the reaction prices of each timing class, the entry rule, intraday announcements, the timestamp audit, and the
exact test.

**Status.** Neither version has been run. No price was downloaded and no outcome was computed. The only data read
are SEC filing lists and index pages for the feasibility counts.

## Unchanged (by request or by design)

- The research question, H1 and H0.
- The 40-session primary horizon.
- The four verdicts (SUPPORTED, NOT SUPPORTED, CONTRARY, INVALID / INSUFFICIENT DATA).
- The universe, the period (2016–2025), the event definition and the benchmark.
- The exploratory family E1–E5 under Holm, the costs of E3, the validity minima and the power assumptions.
- Gate G2 (Cboe cross-check) and the 5% / 20% study-level thresholds.
- For PRE and NON-SESSION events, EAR and DRIFT40 are computed exactly as in v1.

## Changed

| # | Owner's point | v1 | v2 | Section |
|---|---|---|---|---|
| 1 | Earliest verifiable public time; release vs SEC acceptance | Only the SEC acceptance t_A; the dateline was used only by gate G1 | Four quantities: t_A (acceptance, to the second), D_R (release dateline, to the day), t_PR (actual release time from a wire-service or IR page, audit sample only, because these pages cannot be collected at scale) and t_E = min(t_PR, t_A). Without t_PR, the release lies in [L, t_A] under the stated assumption A1. A dateline earlier than t_A's date makes the event UNALIGNED (excluded). | 4 |
| 2 | Before the open, during trading hours, after the close, weekends, holidays | Three classes by t_A on a 09:30 / 16:00 clock; early-close days treated as intraday; sessions from SPY bars | Five classes (PRE, POST, NON-SESSION, INTRADAY, UNALIGNED) on the exact XNYS schedule (`exchange_calendars`, pinned), with holidays, special closures and 13:00 early closes. SPY bar dates are cross-checked after the prices are downloaded. | 3, 5, 13 |
| 3 | Exact start and end prices per class | One formula for all: close(d_pre) → close(d0+1), with d_pre the session before t_A's calendar day | Start = the last regular-session close before the earliest possible release time (s_b); end = close(s*+1). Per class: PRE close(d−1) → close(d+1); POST close(d) → close(d+2); NON-SESSION close(last session) → close(n+1). **POST events no longer include session d, which traded before the release.** | 5, 6 |
| 4 | Entry after the reaction, no overlap, no unavailable information | Open of d0+2 | Open of s*+2, one session boundary after the last EAR price. The information used at entry is listed, and all of it is known by close(s*+1). | 6 |
| 5 | Intraday releases with daily data | Kept: window from the previous day's close, which includes the pre-announcement part of the session | **Excluded from the primary analysis** under a pre-registered rule: daily bars cannot separate the pre-release part of the session, and no reliable 2016–2025 intraday data is available. About 3% of events in feasibility. | 5, 13 |
| 6 | 100-announcement audit: time accuracy and session alignment | Dateline vs acceptance date only; INVALID if more than 10% of releases were a day or more early | Audit of the verified release time t_PR. It reports time accuracy (t_A − t_PR) and **session alignment** (rule vs true (s_b, s*)). Seed `20261014`; 100 verified events, at most 150 attempts. **G1a** (the v1 rule) is kept. New rules: **G1b**, INVALID if PRE / NON-SESSION misalignment exceeds 10%; **G1b-POST**, POST excluded before any price if POST misalignment exceeds 10%; **G1c**, INVALID if fewer than 100 releases can be verified. The justification is in section 13. | 13 |
| 7 | Exact test, dependence, confidence interval | Mean quarterly Spearman, Newey–West lag 1, t with 39 df (stated briefly) | Full formulas: ρ_q, ρ̄, γ̂_0 and γ̂_1, with lag-1 cross-products only between consecutive calendar quarters; Var̂ = (γ̂_0 + γ̂_1)/M; T against t(M−1); two-sided p; CI ρ̄ ± t_{0.975,M−1}·SE. Why lag 1 suffices (40-session windows never reach quarter q+2). Within-quarter dependence handled by aggregating each quarter to one number (Fama–MacBeth). Lag 1–4 autocorrelations reported, never used to change the test. | 11 |

## Consequences of v2

- **Fewer events.** The intraday exclusion costs about 3%. If G1b-POST triggers, POST events (about a third)
  are dropped, which brings the sample to about 10,000, the validity minimum. INSUFFICIENT DATA is then possible.
  This is stated in section 10.
- **New risk 10.** Selection by timing class. Results by class are reported.
- **The audit needs hosts this cloud environment refuses** (wire services, company investor-relations sites).
  After approval it runs on the owner's PC or once those domains are allowed. It reads release pages only, never
  prices.
- **One new dependency** at implementation: `exchange_calendars`, version pinned in the pre-registration
  (4.11.1 proposed).
- **Order of execution.** The timestamp audit is its own step (3), before any price download.
