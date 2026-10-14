# Stage 4 — pre-registration PROPOSAL v3: drift after the market's reaction to earnings announcements

**Status: PROPOSAL v3, awaiting the owner's review and approval. NOT RUN.**

- No price, return or outcome of this study has been downloaded or computed.
- The only data read so far are SEC filing lists and EDGAR index pages, for the feasibility counts in
  `feasibility.json` (v1) and `feasibility_v3.json` (scripts `feasibility.py` and `feasibility_v3.py`).
- On approval, the approved text is copied to `docs/research/STAGE4_PREREGISTRATION.md` and committed with its
  SHA-256, before any price is downloaded. Results go to a write-once `reports/research_stage4.json`.
- This study changes nothing in the production signal, stage 3 or the paper strategy PT1, and its result is never
  used by them.

**Version.** Proposal version `stage4-proposal-v3` (2026-10-14).
- Earlier versions, kept unchanged:
  - v1 (2026-10-12): `STAGE4_PREREGISTRATION_PROPOSAL_v1.md`, SHA-256 `d4c42d99…3372f`.
  - v2 (2026-10-14): `STAGE4_PREREGISTRATION_PROPOSAL_v2.md`, SHA-256 `65b95d4c…c644b`.
- `CHANGES_v2_to_v3.md` lists every difference.
- v3 answers the owner's second clarification request (2026-10-14) on timestamp assumptions and their statistical
  consequences.
- Unchanged by request: the research question, the 40-session primary horizon, the universe, the period, the
  primary statistic and the four verdicts.

**Decision required before freezing.** Section 15: with the available timestamps, the verified primary set is
expected to fall below the 10,000-event validity minimum.

## Why this question, and what it cannot answer

The question is whether the market-adjusted return around an earnings announcement predicts the market-adjusted
return over the following weeks. This is post-earnings-announcement drift measured with the market's own reaction,
as in Chan, Jegadeesh & Lakonishok (1996) and Brandt, Kishore, Santa-Clara & Venkatachalam (2008).

**No analyst consensus.**
- Consensus estimates are not in SEC filings and no licensed source is available, so the classic standardized
  surprise against consensus cannot be built.
- The surprise derived from XBRL EPS (seasonal random walk) is not used: XBRL EPS arrives with the 10-Q / 10-K,
  usually days or weeks after the 8-K release, so it would describe a different, later event.
- The reaction (EAR) used instead mixes the earnings news with guidance and any other news of the same days. It
  is not an earnings surprise.

**Prior evidence.** Published work reports that the classic drift weakened markedly in recent decades, especially
for large companies (e.g. Martineau, 2022, "Rest in peace post-earnings announcement drift", *Critical Finance
Review*). This study is therefore set up so that a null result is an expected, fully reportable outcome.

**Scope (v3).** The question is tested on the announcements whose alignment with trading sessions can be verified
from SEC records (section 5): mostly releases before the open, plus those on weekends and holidays. Any result
applies to that population (risk 10).

## 1. Primary hypothesis

- **H1.** Across eligible announcements, the announcement-window market-adjusted return (EAR) is positively
  rank-correlated with the market-adjusted return over the next 40 trading sessions (DRIFT40), entered at the
  first open after the reaction window.
- **H0.** The mean quarterly Spearman correlation between EAR and DRIFT40 is 0.
- **Test.** Two-sided. H1 is supported only with a positive sign (see 14).
- **Nature.** The statistic measures association, not a tradable rule (see 9 and 11).

## 2. Eligible companies and period

**Companies.**
- The S&P 500 constituents list (`datasets/s-and-p-500-companies`; a rank-3 third-party compilation, as in stages
  1 and 2), downloaded on the approval day and frozen as `docs/research/stage4/universe.csv` with its SHA-256.
- All GICS sectors are included: the hypothesis uses no accounting ratio.
- One company per SEC CIK: for several listed share classes, the alphabetically first ticker.

**Events.**
- Announcements whose SEC acceptance date (New York) falls between 2016-01-01 and 2025-12-31.
- Only events dated on or after the company's "Date added" to the index, when the list gives it. An unknown date
  counts as a member, and the number of such events is reported.

**Period.** Ten years, chosen before any price data. Every outcome window ends by about March 2026, so all data
exist at approval.

**Feasibility (filings only).**
- v1 (`feasibility.json`): from a seeded sample of 60 companies, 1,911 candidate events, extrapolated to about
  15,900 for the full list.
- v3 (`feasibility_v3.json`, a seeded subset of 300 of those events, timed on their index pages):

| Class | Events | Share |
|---|---|---|
| V-PRE | 172 | 57.3% |
| POST | 97 | 32.3% |
| INTRADAY | 21 | 7.0% |
| SPANNING | 10 | 3.3% |

- No V-NONSESSION event and no index page without a time was found.
- The cover-page reportDate equals the acceptance day for 287 of 300 events.
- The primary set (section 5) is therefore about 57% of candidates (95% interval 52–63%), or about 9,100 events
  (8,200–10,000) before any price-based exclusion.

## 3. Variables: source and definition

| Variable | Source | Definition |
|---|---|---|
| Announcement | SEC EDGAR submissions feed (rank 1) | Form `8-K` (not `8-K/A`) whose items include `2.02`, and no other 8-K item 2.02 of the same company accepted in the preceding 45 calendar days. Later ones are excluded and counted. At most one event per company per calendar quarter (the first). |
| Timestamps | see section 4 | t_A, D_R, t_PR, t_E |
| Exchange calendar | `exchange_calendars` XNYS, version pinned at approval (4.11.1 proposed), read from its `schedule` table | Sessions, holidays (including special closures such as 2018-12-05 and 2025-01-09) and early closes (13:00), each with its open and close instants. After prices are downloaded, it is cross-checked against the SPY bars (section 13). |
| Prices | yfinance daily bars (rank 2), auto-adjusted for splits and dividends: open and close | Ratios of adjusted prices are total returns within a window. |
| Price cross-check | Cboe delayed daily history (rank 2) | yfinance unadjusted close vs Cboe close on every session used, tolerance 0.5% (see 13). |
| Benchmark | SPY, same source and adjustment | See 8. |
| Sector (exploratory only) | GICS sector in the frozen list (today's classification) | Mapped to the SPDR sector ETF. |

## 4. Timestamps: release, SEC acceptance and the announcement day

**Four quantities.** All times are New York time; no timestamp is estimated or filled.

| Symbol | What it is | Source | Precision | Available for |
|---|---|---|---|---|
| **t_A** | SEC acceptance of the 8-K | EDGAR filing index page, "Accepted" field. The feed's `acceptanceDateTime` label is not used. | Second | Every event |
| **D_R** | Announcement day | The earlier of two dates: (a) the 8-K cover page's "Date of Report (Date of earliest event reported)", the feed field `reportDate`, which the filer must state and which for item 2.02 is the date of the public announcement; (b) the exhibit 99 dateline, when the rule of `feasibility.py` detects it | Day, no time | Every event with a reportDate (all 300 in feasibility) |
| **t_PR** | The company's actual press-release time | A timestamp with time of day shown on the wire-service page of the release (Business Wire, PR Newswire, GlobeNewswire, Accesswire or similar) or on the company's investor-relations news page. An archived copy counts; the time on the page is used, not the archive time. Each record keeps its URL, retrieval time, the SHA-256 of the raw page and the quoted text. | Minute | Only the audit sample (gate G1). These pages are refused by the cloud environment's network policy and cannot be collected for about 16,000 events. |
| **t_E** | The earliest public time: the instant the announcement became public | min(t_PR, t_A) | — | Known only where t_PR is |

**How they interact.**
- **Upper bound.** EDGAR disseminates an 8-K at its acceptance, so the announcement is public no later than
  t_A: t_E ≤ t_A always.
- **Lower bound.** The release cannot be on an earlier day than D_R, the earliest announcement date the company's
  own documents give. So t_E ≥ 00:00 of D_R. This is assumption **A2**; section 13 checks it.
- **The release interval** is I = [00:00 of D_R, t_A], and t_E ∈ I.
- **The rule never needs t_PR.** It needs only to know that every instant of I gives the same alignment. When t_PR
  is known (audit sample), it serves to check the rule, not to replace it, so every event is classified the same
  way.

**Assumption A1 (v2), now outside the primary analysis.**
- Statement: the release came after the last regular-session close before t_A.
- Only one class needs it: **POST**, an 8-K accepted after the close of a session day d whose announcement day is
  d. Its interval [00:00 d, t_A] contains d's trading hours, so the release could have been before the open,
  during the session or after the close.
- A1 is plausible:
  - NYSE and Nasdaq require listed companies to notify the exchange before releasing material news during
    trading hours, and companies usually release earnings outside them;
  - the 8-K usually follows the wire release within minutes.
- It cannot be verified for about 16,000 events without release times, which are unavailable at scale. v3
  therefore excludes POST events from the primary analysis. They are reported only as a descriptive diagnostic
  (section 6), labelled "timing unverified (A1)", and they cannot change the verdict.

**Assumption A2, which the primary analysis relies on.**
- Statement: the announcement was not made on a day earlier than D_R. This is the only timing assumption of the
  primary set.
- It is a factual claim about the company's own SEC cover page and press-release dateline, not a claim about
  behaviour.
- Feasibility: reportDate equals t_A's day for 96% of events. The other 4% are mostly SPANNING and excluded.
- Gate G1 measures how often A2 fails in the primary set.

## 5. Mapping announcements to trading sessions (rule for every event, release time unknown)

**Reference implementation.** `docs/research/stage4_proposal/timing_rule.py` (`classify`), tested in
`tests/test_p78_stage4_timing_rule.py` on a synthetic calendar and on XNYS. It is the code that will be run on
approval.

**Notation.**
- open(s) and close(s) are the XNYS schedule instants of session s. A close is 16:00, or 13:00 on an early-close
  day.
- I = [00:00 of D_R, t_A], the release interval.
- s_b: the last session whose close is at or before the start of I.
- s*: the first session whose open is after t_A.

**Rule.**

| Step | Condition | Class | Primary? |
|---|---|---|---|
| 1 | D_R missing or after t_A's day | INCONSISTENT | no |
| 2 | t_A inside a session: open(d) ≤ t_A < close(d) | INTRADAY | no |
| 3 | No session's trading hours [open, close) intersect I, and t_A is before the open of its own (session) day | **V-PRE** | **yes** |
| 3' | Same, and t_A's day is not a session (weekend, holiday, special closure) | **V-NONSESSION** | **yes** |
| 4 | Trading hours inside I, D_R = t_A's day and t_A ≥ close(d) | POST (relies on A1) | no; descriptive only |
| 5 | Trading hours inside I otherwise: an announcement day earlier than t_A's day with a session in between | SPANNING | no |

For V-PRE and V-NONSESSION events, every possible release instant in I has the same s_b and the same s*. The
session alignment is therefore **determined by SEC records alone**, whatever the true t_PR is inside I.

**Prices for the primary classes.** The reaction window is exactly two sessions, s* and s*+1, as in v1 and v2.

| Class | Start price | Reaction sessions | End price | Entry | Exit |
|---|---|---|---|---|---|
| V-PRE (t_A before the open of session d) | close(s_b) = the previous session's close, or Friday's close when D_R is a weekend day | d, d+1 | close(d+1) | open(d+2) | close(d+41) |
| V-NONSESSION (t_A on a non-session day) | close of the last session before D_R | n, n+1 (n = first session after t_A) | close(n+1) | open(n+2) | close(n+41) |

**Worked examples.** These are **hypothetical timestamps on real 2024 calendar dates, not observations**. They
were computed with `timing_rule.classify` on the XNYS calendar.

| # | t_A (accepted) | D_R | Class | Start close | Reaction sessions | End close | Entry open | Exit close |
|---|---|---|---|---|---|---|---|---|
| 1 | Tue 2024-10-22 07:05 | 2024-10-22 | V-PRE | Mon 10-21 | 10-22, 10-23 | 10-23 | 10-24 | 2024-12-19 |
| 2 | Tue 2024-10-22 16:10 | 2024-10-22 | POST (A1) | (Tue 10-22 under A1) | (10-23, 10-24) | (10-24) | (10-25) | (12-20): descriptive only |
| 3 | Tue 2024-10-22 11:15 | 2024-10-22 | INTRADAY | — | — | — | — | excluded |
| 4 | Sat 2024-10-26 09:00 | 2024-10-26 | V-NONSESSION | Fri 10-25 | Mon 10-28, 10-29 | 10-29 | 10-30 | 2024-12-26 |
| 5 | Thu 2024-11-28 08:00 (Thanksgiving) | 2024-11-28 | V-NONSESSION | Wed 11-27 | Fri 11-29 (13:00 close), Mon 12-02 | 12-02 | 12-03 | 2025-01-31 |
| 6 | Fri 2024-11-29 14:30 (after the 13:00 early close) | 2024-11-29 | POST (A1) | — | — | — | — | descriptive only |
| 7 | Mon 2024-10-28 06:30 | Sun 2024-10-27 | V-PRE (no trading between Sunday 00:00 and t_A) | Fri 10-25 | 10-28, 10-29 | 10-29 | 10-30 | 2024-12-26 |
| 8 | Tue 2024-10-22 07:00 | Mon 2024-10-21 | SPANNING (Monday's session lies inside I) | — | — | — | — | excluded |
| 9 | Mon 2024-10-21 16:00:00 exactly | 2024-10-21 | POST (at the close counts as after) | — | — | — | — | descriptive only |
| 10 | Mon 2024-10-21 09:30:00 exactly | 2024-10-21 | INTRADAY (at the open counts as during) | — | — | — | — | excluded |
| 11 | Fri 2024-03-29 10:00 (Good Friday, closed) | 2024-03-29 | V-NONSESSION | Thu 03-28 | Mon 04-01, 04-02 | 04-02 | 04-03 | 2024-05-29 |
| 12 | Sat 2024-10-26 10:00 | Fri 2024-10-25 | SPANNING (Friday's session lies inside I) | — | — | — | — | excluded |
| 13 | Tue 2024-10-22 07:00 | none | INCONSISTENT | — | — | — | — | excluded |

**Intraday announcements.**
- With daily bars, the only price before an intraday release is the previous close, and the only one after it
  is the same day's close. A daily window cannot separate the pre-release movement of the session from the
  reaction.
- Reliable intraday history for 2016–2025 is not available here (yfinance keeps 5-minute bars for about 60 days
  and hourly bars for about 730 days; no licensed source).
- So INTRADAY events are excluded (7% in feasibility).

**Extended-hours trading.** Trading between the start close and the release (16:00–20:00 and 04:00–09:30) cannot
be seen in daily data. It falls inside the reaction window and is usually thin before a release.

## 6. Reaction return, entry and outcome

**EAR** = P(close(s*+1)) / P(close(s_b)) − SPY(close(s*+1)) / SPY(close(s_b)). Adjusted prices; the same sessions
for the stock and SPY.

**Decision time.** After close(s*+1), when EAR is known from end-of-day data.

**Entry.**
- When: at open(s*+2), with a market-on-open order sent before that open.
- Reference price: the adjusted yfinance open of s*+2. The Cboe open of s*+2 is reported beside it as a check.
- Constraint: the entry is one full session boundary after the last price used by EAR, so the windows do not
  overlap.

**Information used at entry.** Only items known by close(s*+1):
- t_A and the 8-K, public at t_A, before s*;
- D_R, from that 8-K's cover page and exhibit;
- the timing class;
- EAR;
- the frozen list's index membership and "Date added". This is a survivorship limitation (risk 1), not
  information from after entry.

**DRIFT40** = P(close(s*+41)) / P(open(s*+2)) − SPY(close(s*+41)) / SPY(open(s*+2)). This is the 40 sessions
s*+2 to s*+41.

**Quarter of an event.** The calendar quarter of its entry date, s*+2.

**No estimated parameter.**
- Adjusted prices are back-adjusted with later dividends, but a ratio inside a window depends only on dividends
  inside that window.
- No beta and no fitted threshold is estimated, so there is no training set to leak.

**Descriptive diagnostics (never tested, never part of the verdict).**
- The primary statistic for V-PRE and V-NONSESSION separately.
- The same statistic for POST events, with windows computed under A1 (start close(d)), labelled "timing
  unverified (A1)".

## 7. Primary horizon and outcome metric

- **Horizon.** H = 40 sessions, chosen before any data.
  - The usual 60-day window would often reach the company's next quarterly announcement (about 63 sessions
    later) and mix in its news.
  - 40 sessions keeps almost all windows before it.
  - The share of windows that still contain the company's next 8-K item 2.02 is reported.
- **Outcome.** DRIFT40 (market-adjusted, open-to-close, total return; section 6).
- **Primary statistic.** The mean over calendar quarters of the Spearman correlation between EAR and DRIFT40
  (section 11).

## 8. Benchmark

- **Primary.** SPY total return over the same window (market adjustment, no estimated beta).
- **Exploratory.** The SPDR ETF of the company's GICS sector (E4).

## 9. Transaction costs and execution assumptions

- **Primary statistic.** It is cost-free: it measures information in EAR, not profitability. No profitability is
  claimed from it.
- **Exploratory E3 (tradable form).**
  - Each quarter, the long leg is the events in the top quintile of EAR and the short leg the bottom quintile.
  - The quintile breakpoints come from the previous quarter's EAR distribution, known at entry: no look-ahead.
  - Equal weight; entry at open(s*+2), exit at close(s*+41).
  - Costs are the PT1 assumptions: 1 bp commission + 5 bp slippage + 2 bp half-spread per side, i.e. 16 bp round
    trip per leg and 32 bp for the long-short pair.
  - Reported gross and net, with the long-only top quintile minus SPY (net 16 bp).
  - Not modelled: borrow fees, short constraints and market impact. The short leg is optimistic.

## 10. Minimum sample size and power

**Validity minima (unchanged).**
- At least 32 of the 40 quarters with at least 100 eligible events each.
- At least 10,000 eligible events in total.
- Otherwise the result is INSUFFICIENT DATA.

**Power.** These are assumptions, not estimates from this sample.

| | v1 / v2 (n_q ≈ 400) | v3 primary set (n_q ≈ 228, feasibility) |
|---|---|---|
| SD of one quarter's ρ_q | 0.050 | 0.066 |
| Minimum detectable mean ρ (80% power, 5% two-sided, t with 39 df; σ_b ∈ {0, 0.03, 0.05}, HAC inflation 1.0–1.2) | 0.023 – 0.039 | **0.030 – 0.045** |
| Power, middle scenario (σ_b 0.03, inflation 1.2), at a true correlation of 0.02 / 0.03 / 0.04 | 0.42 / 0.75 / 0.94 | **0.29 / 0.56 / 0.81** |

A real but small effect (around 0.01–0.02) would very probably be missed. The conclusion would then read "not
supported", never "no effect exists".

## 11. Statistical test, dependence and confidence interval (unchanged from v2)

**Per-quarter statistic.**
- For each calendar quarter q (assigned by entry date) with n_q ≥ 100 eligible events:
  ρ_q = the Pearson correlation of the ranks of EAR and the ranks of DRIFT40 among those events (Spearman).
- Ties get average ranks.
- Each company appears at most once per quarter.
- Quarters with n_q < 100 are dropped and listed.

**Primary statistic.** The eligible quarters, in calendar order, are q_1 … q_M. The statistic is
ρ̄ = (1/M) Σ_{t=1..M} ρ_{q_t}.

**Dependence between events.**
- **Within a quarter**, each quarter contributes one number, ρ_q. The test uses only the time-series variation of
  ρ_q across quarters (Fama–MacBeth aggregation).
- **Between quarters**, a 40-session window (shorter than a quarter of about 63 sessions) of an event entered in
  quarter q ends in q or q+1, never in q+2. So serial dependence is expected at lag 1 only.

**Standard error: Newey–West HAC, Bartlett kernel, lag L = 1, fixed in advance.**
- With e_t = ρ_{q_t} − ρ̄:
  - γ̂_0 = (1/M) Σ_{t=1..M} e_t²
  - γ̂_1 = (1/M) Σ_{t=2..M} a_t · e_t · e_{t−1}
  - Here a_t = 1 when q_{t−1} is the calendar quarter immediately before q_t, and 0 otherwise (dropped quarters
    are not bridged).
- Var̂(ρ̄) = (γ̂_0 + γ̂_1) / M (the Bartlett weight at lag 1 is 1/2, which doubles back to γ̂_1), and
  SE = √Var̂(ρ̄).
- This is never negative, because |γ̂_1| ≤ γ̂_0.
- No other kernel, lag or small-sample correction is used.

**Test and confidence interval.**
- **Test statistic.** T = ρ̄ / SE, compared with Student's t with M − 1 degrees of freedom.
- **p-value.** Two-sided: p = 2 · (1 − F_{t, M−1}(|T|)).
- **95% confidence interval.** ρ̄ ± t_{0.975, M−1} · SE (2.023 for M = 40).

**Reported, never tested:**
- n_q for every quarter, and the list of dropped quarters;
- the sample autocorrelations of ρ_q at lags 1 to 4 (reported as a limitation if large at lag 2 or more, never
  used to change the test);
- the sign of ρ̄ in 2016–2018, 2019–2021 and 2022–2025;
- the diagnostics of section 6.

## 12. Multiple-testing controls (unchanged)

**Confirmatory family:** one test (the primary), α = 0.05. Nothing else can change the conclusion.

**Exploratory family:** Holm correction at 0.05 within the family, labelled exploratory in every output. Each uses
the primary events (V-PRE and V-NONSESSION) and the test of section 11.

| ID | Exploratory outcome |
|---|---|
| E1 | Same statistic, horizon 20 sessions |
| E2 | Same statistic, horizon 60 sessions (overlap with next announcements reported) |
| E3 | Quintile long-short, net of costs (section 9): mean quarterly return, HAC t-test |
| E4 | Same statistic with the sector-ETF-adjusted outcome |
| E5 | Same statistic excluding windows that contain the company's next 8-K item 2.02 |

No other horizon, benchmark, subgroup or rule may be added after the data are seen. Any later idea needs a new
pre-registration.

## 13. Gates, exclusions and missing data

All exclusions are decided before outcomes are computed, never on DRIFT, and every count is reported.

### What timestamp errors can do to the estimate

1. **Look-ahead is impossible, whatever the timestamp error.** The windows are computed from t_A, D_R and the
   calendar, all known before s*. The entry is after the last EAR price. A timestamp error cannot place an outcome
   price before the decision.
2. **The timing error is one-sided.** Because t_E ≤ t_A, a misaligned event is always one whose announcement was
   public **earlier** than its window assumes. Its window starts one or more sessions too late, and the event is
   misaligned only when a session lies in between.
3. **The effect on the correlation is not one-sided.**
   - For a misaligned event, the measured EAR omits the first day or days of the true reaction. It also includes
     one or more days that, in true time, belong to the post-reaction period. The measured DRIFT is the true drift
     shifted by the same number of sessions.
   - Approximately (exactly for Pearson correlations when the aligned and misaligned groups have equal means and
     variances), the pooled estimate is ρ̂ ≈ (1 − π)·ρ_A + π·ρ_M. Here π is the share of misaligned events, ρ_A
     the correlation among aligned events (the target) and ρ_M the correlation among misaligned events. The bias
     is about π·(ρ_M − ρ_A).
   - **Attenuation holds only under a classical errors-in-variables assumption.** The error added to EAR would
     have to be independent of both the true EAR and the true DRIFT. Then |ρ_M| < |ρ_A| and the bias is toward
     zero.
   - **That assumption is not justified here.** The error consists of returns on days next to the reaction and
     to the drift window. Abnormal returns around announcements can be serially correlated: a reaction that
     continues over several days, a partial reversal, bid-ask bounce. The error can therefore be correlated with
     the measured DRIFT.
   - ρ_M can then have either sign, and can differ from zero even when ρ_A = 0. For example, if the days after a
     reaction keep moving in the same direction, a misaligned EAR that captures them is positively correlated
     with the following weeks, even with no drift relative to the true reaction. A reversal gives the opposite
     sign.
   - **So misalignment can bias the estimate in either direction, including away from zero, and could in
     principle create a false SUPPORTED or CONTRARY.** v2's sentence that it "can only attenuate" is withdrawn.
4. **How the protocol limits the bias.**
   - (a) Only events whose alignment is determined by SEC records alone enter the primary test, so misalignment
     requires A2 to fail.
   - (b) The audit bounds the misaligned share π in that set: gate G1b below requires a 95% upper bound of at
     most 5%.
   - (c) Explicit assumption: |ρ_M − ρ_A| ≤ 0.20. A correlation between a two-day return and the following
     40-session return beyond 0.20 in absolute value would be implausibly large. This is an assumption, not a
     measured fact.
   - Under (b) and (c), |bias| ≤ 0.05 × 0.20 = 0.010 with 95% confidence. That is less than half the smallest
     detectable effect (0.030 for this set).
   - If (c) were false, the bound would not hold. This is stated as a limitation (risk 3).

### Gate G1: timestamp audit (before any price is downloaded)

**Sample.**
- After the event table is built from SEC data, classified and frozen, the **primary-set events** (V-PRE and
  V-NONSESSION) are shuffled with the seed `20261014`.
- They are audited in that order until 100 have a verified t_PR, or 150 have been attempted.

**Recorded for each audited event** in `docs/research/stage4/timestamp_audit.csv`:
- t_A, the reportDate, the detected dateline and D_R;
- t_PR, with its URL, retrieval time, the SHA-256 of the raw page and the quoted timestamp text;
- the class and (s_b, s*) given by the rule;
- (s_b, s*) given by t_E = min(t_PR, t_A).

**Publication-time accuracy (reported):**
- the share with t_PR ≤ t_A;
- the distribution of t_A − t_PR (median, 90th percentile, share above 1 hour, share above 1 calendar day);
- the share with t_PR's date before D_R (an A2 failure).

**Session alignment.**
- An audited event is **misaligned** when its true (s_b, s*) differs from the rule's, or when its true t_E falls
  inside trading hours.
- In the primary set this can only happen through an A2 failure across a session.

**Decision rules.**

| Rule | Condition | Consequence |
|---|---|---|
| **G1a** (v1 rule, unchanged) | More than 10% of the audited events have t_PR on a calendar day before t_A's date | INVALID |
| **G1b** (revised) | 2 or more of the 100 audited events are misaligned. That is, the one-sided 95% Clopper–Pearson upper bound of π exceeds 5%: 0 misaligned gives 2.95%, 1 gives 4.66%, 2 gives 6.16%. | INVALID |
| **G1c** (unchanged from v2) | Fewer than 100 events have a verified t_PR after 150 attempts | INVALID: the timestamps cannot be verified |

- **G1b-POST of v2 is removed.** POST events are now excluded before any audit.
- **Why G1b is stricter than v2's 10%.** By point 3 above, the bias is not guaranteed to be toward zero. The
  threshold must therefore bound π tightly enough that π·|ρ_M − ρ_A| stays well below the detectable effect.
  10% did not (10% × 0.20 = 0.020, about two thirds of the detectable effect).
- **Note on G1a.** In the primary set, a release on an earlier calendar day than t_A can still be correctly
  aligned (example 7: a Sunday release filed Monday before the open). G1a is kept unchanged anyway, as a
  conservative check.

**Where the audit runs.** The wire-service and investor-relations pages are refused by the cloud environment's
network policy. After approval, the audit runs either on the owner's PC or in the cloud once those domains are
allowed. It reads release pages only, never prices.

### Event-level exclusions

- 8-K/A filings; an 8-K item 2.02 filed within 45 days after another (the first is kept); a second event of the
  same company in a quarter.
- An index page without an "Accepted" time: excluded, not estimated.
- Every class other than V-PRE and V-NONSESSION: INTRADAY, POST, SPANNING, INCONSISTENT. Counted by class.
- Any missing yfinance price on a session used (s_b, s*+1, s*+2, s*+41) or a missing SPY price: excluded.
  Nothing is filled or interpolated.
- yfinance unadjusted close and Cboe close disagreeing by more than 0.5% on a session used (gate G2): excluded.
- Price at s_b below 5 USD (very rare in this index): excluded.
- Windows ending after the last available session: excluded (censoring, counted).

### Calendar cross-check (after prices are downloaded)

- The XNYS sessions from 2015-12-01 to the last session used are compared with the SPY bar dates.
- Any date present in one and not the other is listed.
- Every event whose s_b, s* or window session depends on such a date is excluded and counted.

### Study-level gates

The study is INVALID as designed if:
- gate G1 fails (G1a, G1b or G1c);
- more than 5% of events fail gate G2;
- more than 20% of the primary-set events are excluded for missing data. Timing exclusions are reported
  separately and are not counted in this 20%.

## 14. Acceptance and rejection criteria

| Outcome | Rule |
|---|---|
| SUPPORTED | The validity minima (section 10) and gates (section 13) pass, ρ̄ > 0, and two-sided p < 0.05 (equivalently, the 95% CI lies above 0). |
| NOT SUPPORTED | Validity passes and p ≥ 0.05. The CI is reported; "no effect" is never claimed. |
| CONTRARY | Validity passes, ρ̄ < 0 and p < 0.05: evidence of reversal, reported as such, not used. |
| INVALID / INSUFFICIENT DATA | A gate or minimum fails: no hypothesis result is stated. |

**What SUPPORTED means.** It is a historical association in current S&P 500 members, for announcements with
verifiable session alignment, net of none of the real-world frictions of section 9.

**What it does not allow.** It does not justify a trading rule, a production change or any profitability claim.
Any use would need a separate pre-registered prospective test of at least 52 weeks, like stage 3. That optional
phase B (events after the approval date, frozen universe) would be proposed separately.

## 15. Can the question be tested validly with the available timestamp data?

**Session alignment: yes, for a subset.**
- About 57% of announcements (feasibility) have an alignment determined by SEC records: the 8-K acceptance time
  and the cover-page announcement date. No assumption about release behaviour is needed, only A2, which the audit
  checks.
- For those events, the reaction and drift windows are exact at the daily level, and look-ahead is impossible.

**The rest: not with daily data and free timestamps.**
- After-close filings (32%) need A1, which cannot be verified at scale without press-release times.
- Intraday filings (7%) cannot be measured with daily prices.
- Both are excluded from the primary test.

**Sample size: probably not, under the unchanged minimum.**
- The verified set is expected to hold about 9,100 candidate events (95% interval 8,200–10,000) before
  price-based exclusions. The pre-registered minimum is 10,000.
- Unless the owner decides otherwise, the protocol therefore most likely ends **INSUFFICIENT DATA**.
- The per-quarter minimum (32 quarters with at least 100 events) is expected to be met: about 228 events per
  quarter on average.

**Owner decision before freezing.** None of the options changes the hypothesis, the horizon, the universe, the
period, the statistic or the verdicts.

| Option | What it means | Consequence |
|---|---|---|
| **A** (protocol as written, v3) | Freeze v3 with the 10,000 minimum | A valid design; the expected outcome is INSUFFICIENT DATA, which would be reported as such |
| **B** (a v4, only if requested) | Replace the total-event minimum with the precision criterion it stood for, decided now from counts only (no outcome): the per-quarter rule, plus a ceiling on the ex-ante detectable effect computed from the realized n_q | The test can run on about 9,000 events. Lower power: detectable effect 0.030–0.045; power 0.56 at 0.03. NOT SUPPORTED becomes the most likely outcome even if a small effect exists. |
| **C** | Obtain verified release times for after-close announcements (licensed wire-service timestamps for 2016–2025) | POST events (about a third) could rejoin the primary set with verified alignment. No such source is available now. |

The 10,000 figure of v1 was a round judgement, not a power calculation. Changing it is legitimate only as a
decision made now, before any price is seen, and recorded as a new version.

## Order of execution after approval

1. Commit `STAGE4_PREREGISTRATION.md` and `universe.csv`, with their SHA-256 values. Pin `exchange_calendars` in
   the requirements.
2. Build the event table from SEC data only: filings, index pages, t_A, reportDate, dateline, D_R, class,
   (s_b, s*) by `timing_rule.classify`. Freeze it with its hash.
3. Gate G1: audit the primary-set sample, freeze `timestamp_audit.csv` with its hash, and apply G1a, G1b and G1c.
   Stop here if the study is INVALID.
4. Download prices, run the calendar cross-check, gate G2 and the coverage checks, compute EAR and DRIFT, and
   freeze the table.
5. Compute the primary statistic once, then the exploratory family and the descriptive diagnostics.
6. Write `reports/research_stage4.json` once, recording the code version and the pre-registration hash.

A recalculation after a data fix uses `--recalc` and keeps the original, as in stages 1 and 2.

## Principal statistical risks (summary for the reviewer)

1. **Survivorship.** Only current members are included; removed or delisted companies are absent. The direction
   of the bias on the rank correlation is not known. Mitigations: events only after the date added, the
   sub-period signs, and an optional prospective phase B.
2. **Low power for small effects.** The detectable correlation is about 0.03–0.045 for the verified set.
   NOT SUPPORTED is likely even if a small effect exists.
3. **Timestamp errors (section 13).**
   - They cannot create look-ahead, but they can bias the estimate in either direction.
   - The bias is bounded by restricting the test to SEC-verified alignment, by the audit (π ≤ 5% at 95%) and by the
     stated assumption |ρ_M − ρ_A| ≤ 0.20.
   - Extended-hours trading before a release is inside the window and cannot be removed with daily data.
4. **EAR is not a pure earnings surprise.** Guidance, conference-call content and other news are mixed in.
5. **Cross-sectional dependence.** Industry-wide news within a quarter can make the ranks dependent and the
   standard errors too small.
6. **Overlap with the next announcement** at 40 sessions is reported, and E5 tests sensitivity.
7. **Prior use of the data.** The same price histories were used in stages 1 and 2, for different hypotheses. No
   parameter is fitted, but the period is not "fresh". Only phase B would be.
8. **Exploratory outcomes** are many by nature. Holm correction applies, and they can never change the
   conclusion.
9. **Single-vendor prices.** yfinance is cross-checked against Cboe on every session used. The check catches
   pipeline errors, not exchange errors.
10. **Population restricted by timing class.** The primary set holds about 57% of announcements, mostly releases
    before the open. Companies that announce after the close or during the session may differ by industry or
    size. A result applies to the verified population only; POST results are descriptive and unverified.
