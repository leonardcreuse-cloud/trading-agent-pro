# Stage 4 — pre-registration PROPOSAL v2: drift after the market's reaction to earnings announcements

**Status: PROPOSAL v2, awaiting the owner's review and approval. NOT RUN.**

- No price, return or outcome of this study has been downloaded or computed.
- The only data read so far are SEC filing lists and index pages, for the feasibility counts in
  `feasibility.json` (script `feasibility.py`).
- On approval, the approved text is copied to `docs/research/STAGE4_PREREGISTRATION.md` and committed with its
  SHA-256, before any price is downloaded. Results go to a write-once `reports/research_stage4.json`.
- This study changes nothing in the production signal, stage 3 or the paper strategy PT1, and its result is never
  used by them.

**Version.** Proposal version `stage4-proposal-v2` (2026-10-14).
- It supersedes `stage4-proposal-v1` (2026-10-12), kept unchanged in `STAGE4_PREREGISTRATION_PROPOSAL_v1.md`
  (SHA-256 `d4c42d9918a5df9cc62210436af81a5a4691b4ede33980275abd73dfca43372f`).
- `CHANGES_v1_to_v2.md` lists every difference.
- The owner's clarification request of 2026-10-14 asked for: the timestamp-to-session mapping, the reaction
  prices of each timing class, the entry rule, intraday announcements, the timestamp audit, and the exact test.
- Unchanged by request: the research question, the 40-session primary horizon and the four verdicts.

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

## 1. Primary hypothesis

- **H1.** Across announcements of the eligible companies, the announcement-window market-adjusted return (EAR) is
  positively rank-correlated with the market-adjusted return over the next 40 trading sessions (DRIFT40), entered
  at the first open after the reaction window.
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

**Feasibility (filings only, seeded sample of 60 companies, `feasibility.json`).**
- 1,911 events, extrapolated to about 15,900 for the full list, or about 400 per calendar quarter.
- Events per year grow with index additions.
- Earnings seasons concentrate events: about 2% of events fall in each of March, June, September and December.
- Of 60 timed events: 39 accepted before the open, 19 after the close, 2 during trading hours. The last group is
  excluded under section 5, so about 3% fewer events.

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

## 4. Timestamps: release versus SEC acceptance

**Four quantities.** All times are New York time; no timestamp is estimated or filled.

| Symbol | What it is | Source | Precision | Available for |
|---|---|---|---|---|
| **t_A** | SEC acceptance of the 8-K | EDGAR filing index page, "Accepted" field. The feed's `acceptanceDateTime` label is not used. | Second | Every event |
| **D_R** | Calendar date of the press release (exhibit 99 dateline) | The exhibit 99 filed with the 8-K, read by the pre-registered rule of `feasibility.py`: a dateline at most 7 days before t_A | Day, no time | Events whose dateline the rule detects (about half in feasibility) |
| **t_PR** | The company's actual press-release time | A timestamp with time of day shown on the wire-service page of the release (Business Wire, PR Newswire, GlobeNewswire, Accesswire or similar) or on the company's investor-relations news page. An archived copy of that page counts; the time shown on the page is used, not the archive time. Each record keeps its URL, retrieval time, the SHA-256 of the raw page and the quoted text. | Minute | Only the events of the timestamp audit (gate G1). These pages are not reachable from the cloud environment (network policy, 2026-10-14) and cannot be collected for about 16,000 events. |
| **t_E** | The earliest verifiable public time | min(t_PR, t_A) when t_PR is verified; otherwise the release interval below | — | — |

**Why t_A bounds the release.** EDGAR disseminates an 8-K at its acceptance, so the announcement is public no
later than t_A. The release itself can be earlier: wire first, 8-K minutes later.

**Release interval when t_PR is not known (every event outside the audit).** The release lies in
I = [L, t_A], where:
- L = the later of (a) 00:00 of t_A's calendar day and (b) the last session close (XNYS schedule, early closes
  included) at or before t_A.
- Assumption A1: the release was made on t_A's calendar day and after the last regular-session close before t_A.
  This is what makes the alignment of section 5 possible with daily data. Gate G1 measures how often it fails.
- Exchange rules reinforce A1. NYSE and Nasdaq require listed companies to notify the exchange before releasing
  material news during trading hours, so earnings releases are normally made before the open or after the close.
- If a detected dateline D_R is earlier than t_A's calendar date, A1 is contradicted. The release time on that
  earlier day is unknown, so the event cannot be aligned and is excluded (section 13).

**What A1 cannot cause.** If A1 is wrong for an event, the true release was earlier than assumed. The reaction
window then starts too late, after part of the reaction. EAR is mismeasured, which biases the statistic toward
zero. The entry is not affected: it is after the window in every case, so A1 cannot introduce look-ahead.

## 5. Mapping announcements to trading sessions

**The anchor τ.**
- τ = t_E for an audited event with a verified t_PR.
- τ = t_A for every other event, with the release interval I of section 4.
- The class is decided from τ and the XNYS schedule of τ's calendar date.

**Notation.**
- open(s) and close(s) are the schedule instants of session s. A close is 16:00, or 13:00 on an early-close day.
- s_b: the last session whose close is at or before the start of the release interval. This is the last
  regular-session price before the announcement.
- s*: the first session whose open is after τ, the first session that can react.
- s*+k: the k-th session after s*.

**The five timing classes.**

| Class | Condition on τ | Start price (s_b close) | Reaction sessions | End price | Primary analysis |
|---|---|---|---|---|---|
| **PRE** (before the open) | τ's date is a session d and τ < open(d) (09:30) | close of the session before d | d and d+1 | close(d+1) | included |
| **POST** (after the close) | τ's date is a session d and τ ≥ close(d) (16:00, or 13:00 on an early-close day) | close(d) | d+1 and d+2 | close(d+2) | included |
| **NON-SESSION** (weekend, holiday, special closure) | τ's date is not a session | close of the last session before τ's date | n and n+1, where n is the first session after τ's date | close(n+1) | included |
| **INTRADAY** (during trading hours) | τ's date is a session d and open(d) ≤ τ < close(d) | — | — | — | **excluded** (see below) |
| **UNALIGNED** | a detected D_R earlier than t_A's calendar date (outside the audit) | — | — | — | **excluded** |

- In every included class, the reaction window is exactly two sessions, s* and s*+1, as in v1.
- The start is the last regular-session close before the earliest possible release time.
- **No regular-session trading occurs between the start close and the release.** Extended-hours trading in that
  gap (16:00–20:00 and 04:00–09:30) cannot be seen in daily data and falls inside the window. It is usually thin
  before a release.
- **Holidays and early closes** come from the XNYS schedule. A release at 14:00 on an early-close day is POST
  (after the 13:00 close). A release on Good Friday is NON-SESSION.

**Why intraday announcements are excluded.**
- With daily bars, the only price before an intraday release is the previous close, and the only one after it
  is the same day's close. A daily window cannot separate the movement of session d before the release from the
  reaction after it.
- Reliable intraday history for 2016–2025 is not available here:
  - yfinance keeps 5-minute bars for about 60 days and hourly bars for about 730 days;
  - no licensed intraday source is available.
- Pre-registered rule: every event whose anchor falls inside trading hours is excluded from the primary
  analysis, and the number is reported.
- This also excludes some releases made before the open but filed during the session. That costs events, not
  validity; feasibility shows 2 of 60.

## 6. Reaction return, entry and outcome

**EAR** = P(close(s*+1)) / P(close(s_b)) − SPY(close(s*+1)) / SPY(close(s_b)). Adjusted prices; the same sessions
for the stock and SPY.

**Decision time.** After close(s*+1), when EAR is known from end-of-day data.

**Entry.**
- When: at open(s*+2), with a market-on-open order sent before that open.
- Reference price: the adjusted yfinance open of s*+2. The Cboe open of s*+2 is reported beside it as a check.
- Constraint: the entry is one full session boundary after the last price used by EAR. No price at or before
  close(s*+1) is used for entry, and the reaction window and the holding period do not overlap.

**Information used at entry.** Only items known by close(s*+1):
- t_A and the 8-K, public at t_A, before s*;
- D_R, from the exhibit filed with the 8-K;
- the timing class;
- EAR;
- the frozen list's index membership and "Date added". This is a survivorship limitation (risk 1), not
  information from after entry.

**DRIFT40** = P(close(s*+41)) / P(open(s*+2)) − SPY(close(s*+41)) / SPY(open(s*+2)). This is the 40 sessions
s*+2 to s*+41, unchanged from v1.

**Equivalence with v1.** For PRE and NON-SESSION events, s* is v1's d0, so EAR and DRIFT40 are identical to v1.
For POST events, v1 started EAR at the close of the session before d. v2 starts it at close(d), the last close
before the release. v2 therefore no longer includes session d, which traded before the announcement.

**Quarter of an event.** The calendar quarter of its entry date, s*+2.

**No estimated parameter.**
- Adjusted prices are back-adjusted with later dividends, but a ratio inside a window depends only on dividends
  inside that window.
- No beta and no fitted threshold is estimated, so there is no training set to leak.

**Diagnostic.** The primary statistic is also reported by timing class (PRE, POST, NON-SESSION). This is
descriptive, not a test.

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

**Validity minima.**
- At least 32 of the 40 quarters with at least 100 eligible events each.
- At least 10,000 eligible events in total.
- Otherwise the result is INSUFFICIENT DATA.

**Power.** These are assumptions, not estimates from this sample.
- The sampling SD of one quarter's Spearman correlation with n ≈ 400 is about 1/√(n−1) = 0.050.
- With between-quarter variation of the true effect σ_b ∈ {0, 0.03, 0.05} and a HAC inflation of 1.0–1.2, the
  standard error of the mean over 40 quarters is 0.008–0.013.
- **Minimum detectable effect** (80% power, 5% two-sided, t with 39 df): a mean rank correlation of **0.023 to
  0.039**.
- **Middle scenario** (σ_b 0.03, inflation 1.2): power is 0.42 at a true correlation of 0.02, 0.75 at 0.03 and
  0.94 at 0.04.
- **Consequence.** A real but small effect (around 0.01–0.02) would probably be missed, and the conclusion would
  then read "not supported", never "no effect exists".
- **Effect of v2.** The intraday exclusion removes about 3% of events, and the POST fallback (section 13), if
  triggered, about a third. With the fallback, about 10,000 events would remain: at the validity minimum, so
  INSUFFICIENT DATA becomes possible.

## 11. Statistical test, dependence and confidence interval (exact specification)

**Per-quarter statistic.**
- For each calendar quarter q (assigned by entry date) with n_q ≥ 100 eligible events:
  ρ_q = the Pearson correlation of the ranks of EAR and the ranks of DRIFT40 among those events (Spearman).
- Ties get average ranks.
- Each company appears at most once per quarter.
- Quarters with n_q < 100 are dropped and listed.

**Primary statistic.** The eligible quarters, in calendar order, are q_1 … q_M. The statistic is
ρ̄ = (1/M) Σ_{t=1..M} ρ_{q_t}.

**Dependence between events.**
- **Within a quarter**, announcements cluster by season and industry, and their windows overlap. Each quarter
  contributes one number, ρ_q. The test uses only the time-series variation of ρ_q across quarters (Fama–MacBeth
  aggregation), so within-quarter dependence enters through that variation, not through an event-level standard
  error.
- **Between quarters**, a holding window lasts 40 sessions, shorter than one quarter (about 63 sessions). The
  window of an event entered in quarter q therefore ends in q or q+1 and never in q+2. Only adjacent quarters
  share calendar days, so serial dependence is expected at lag 1 only.

**Standard error: Newey–West HAC, Bartlett kernel, lag L = 1, fixed in advance.**
- With e_t = ρ_{q_t} − ρ̄:
  - γ̂_0 = (1/M) Σ_{t=1..M} e_t²
  - γ̂_1 = (1/M) Σ_{t=2..M} a_t · e_t · e_{t−1}
  - Here a_t = 1 when q_{t−1} is the calendar quarter immediately before q_t, and 0 when a quarter is missing
    between them (dropped quarters are not bridged).
- Var̂(ρ̄) = (γ̂_0 + 2 · (1 − 1/(L+1)) · γ̂_1) / M = (γ̂_0 + γ̂_1) / M, and SE = √Var̂(ρ̄).
- This is never negative, because |γ̂_1| ≤ γ̂_0.
- The lag is not chosen from the data. No other kernel, lag or small-sample correction is used.

**Test and confidence interval.**
- **Test statistic.** T = ρ̄ / SE, compared with Student's t with M − 1 degrees of freedom.
- **p-value.** Two-sided: p = 2 · (1 − F_{t, M−1}(|T|)).
- **95% confidence interval.** ρ̄ ± t_{0.975, M−1} · SE. With M = 40, t_{0.975, 39} = 2.023.
- **Decision.** It uses only ρ̄, T, p and the CI, by the rules of section 14.

**Reported with it, never tested:**
- n_q for every quarter, and the list of dropped quarters;
- the sample autocorrelations of ρ_q at lags 1 to 4, to show whether lag 1 was adequate (a large autocorrelation
  at lag 2 or more is reported as a limitation, not used to change the test);
- the sign of ρ̄ in 2016–2018, 2019–2021 and 2022–2025;
- results by timing class.

## 12. Multiple-testing controls

**Confirmatory family:** one test (the primary), α = 0.05. Nothing else can change the conclusion.

**Exploratory family:** Holm correction at 0.05 within the family, labelled exploratory in every output. Each uses
the same events, timing classes and test as the primary (section 11).

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

### Gate G1: timestamp audit (before any price is downloaded)

**Sample.**
- After the event table is built from SEC data and frozen, its candidate events are shuffled with the seed
  `20261014`. This is before the timing exclusions, so the sample represents every candidate event, excluded
  ones included.
- Events are audited in that order until 100 have a verified t_PR, or 150 have been attempted.

**Recorded for each audited event** in `docs/research/stage4/timestamp_audit.csv`:
- t_A and D_R, with D_R read by hand when the rule does not detect it;
- t_PR, with its source URL, retrieval time, the SHA-256 of the raw page and the quoted timestamp text;
- the timing class and (s_b, s*) given by the section 5 rule;
- the class and (s_b, s*) given by the true anchor t_E = min(t_PR, t_A).

**Publication-time accuracy (reported):**
- the share with t_PR ≤ t_A;
- the distribution of t_A − t_PR (median, 90th percentile, share above 1 hour, share above 1 calendar day);
- the agreement of the detected D_R with t_PR's date.

**Session alignment.** An audited event that the rule keeps is **misaligned** in either case:
- its rule (s_b, s*) differs from its true (s_b, s*);
- its true t_E falls inside trading hours, so it should have been excluded.

A difference in class alone is not a misalignment when (s_b, s*) is the same. An example is a release after
Monday's close filed before Tuesday's open: POST and PRE give the same start, close(Monday), and the same
reaction session, Tuesday.

**Decision rules.**

| Rule | Condition | Consequence |
|---|---|---|
| **G1a** (v1 rule, kept) | More than 10% of the audited events have t_PR on a calendar day before t_A's date | INVALID |
| **G1b** (new) | Among audited events the rule keeps, the misalignment rate of the PRE and NON-SESSION classes together exceeds 10% | INVALID |
| **G1b-POST** (new) | The misalignment rate of POST events exceeds 10% while PRE / NON-SESSION pass | POST events are excluded from the primary analysis, before any price is downloaded. The validity minima of section 10 then decide between continuing and INSUFFICIENT DATA. |
| **G1c** (new) | Fewer than 100 events have a verified t_PR after 150 attempts | INVALID: the timestamps cannot be verified |

**Why G1 changed.**
- **G1a is unchanged.** It is now measured with the verified release time instead of the dateline alone.
- **G1b** extends the same 10% threshold from "release a day early" to "release on the wrong side of a session
  boundary", which is what actually matters with daily prices.
  - A misalignment can only make EAR start late, which biases the statistic toward zero (section 4). It cannot
    create look-ahead.
  - So 10% bounds a loss of accuracy, not of validity, and keeping v1's threshold is consistent.
- **G1b-POST** exists because A1 is weakest for POST events. An 8-K accepted after the close can follow a release
  made earlier the same day. That class is tested on its own.
  - The fallback is decided on timestamps only, before any price, so it cannot be tuned on outcomes.
  - The cost: the remaining events are only pre-open and non-session announcers.
- **G1c** follows from the audit's purpose: an audit that cannot verify release times cannot pass.
  - At most 50 extra events are drawn, so the audited set cannot drift far from a random sample. The share of
    unverifiable events is reported.

**Where the audit runs.**
- The wire-service and investor-relations pages are refused by the cloud environment's network policy.
- So, after approval, the audit runs either on the owner's PC or in the cloud once the owner allows those
  domains.
- It reads only release pages, never prices.

### Event-level exclusions

- 8-K/A filings; an 8-K item 2.02 filed within 45 days after another (the first is kept); a second event of the
  same company in a quarter.
- An index page without an "Accepted" time: excluded, not estimated.
- INTRADAY and UNALIGNED events (section 5), and POST events if G1b-POST is triggered.
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
- more than 20% of candidate events are excluded for missing data. Timing exclusions are reported separately and
  are not counted in this 20%.

## 14. Acceptance and rejection criteria

| Outcome | Rule |
|---|---|
| SUPPORTED | The validity minima (section 10) and gates (section 13) pass, ρ̄ > 0, and two-sided p < 0.05 (equivalently, the 95% CI lies above 0). |
| NOT SUPPORTED | Validity passes and p ≥ 0.05. The CI is reported; "no effect" is never claimed. |
| CONTRARY | Validity passes, ρ̄ < 0 and p < 0.05: evidence of reversal, reported as such, not used. |
| INVALID / INSUFFICIENT DATA | A gate or minimum fails: no hypothesis result is stated. |

**What SUPPORTED means.** It is a historical association in current S&P 500 members, net of none of the
real-world frictions of section 9.

**What it does not allow.** It does not justify a trading rule, a production change or any profitability claim.
Any use would need a separate pre-registered prospective test of at least 52 weeks, like stage 3. That optional
phase B (events after the approval date, frozen universe) would be proposed separately.

## Order of execution after approval

1. Commit `STAGE4_PREREGISTRATION.md` and `universe.csv`, with their SHA-256 values. Pin `exchange_calendars` in
   the requirements.
2. Build the event table from SEC data only: filings, index pages, t_A, D_R, timing class, (s_b, s*) by the
   section 5 rule. Freeze it with its hash.
3. Gate G1: run the timestamp audit, freeze `timestamp_audit.csv` with its hash, and apply G1a, G1b, G1b-POST and
   G1c. Stop here if the study is INVALID.
4. Download prices, run the calendar cross-check, gate G2 and the coverage checks, compute EAR and DRIFT, and
   freeze the table.
5. Compute the primary statistic once, then the exploratory family.
6. Write `reports/research_stage4.json` once, recording the code version and the pre-registration hash.

A recalculation after a data fix uses `--recalc` and keeps the original, as in stages 1 and 2.

## Principal statistical risks (summary for the reviewer)

1. **Survivorship.** Only current members are included; removed or delisted companies are absent. Survivors may
   have had better post-announcement returns after bad reactions, which biases toward reversal or attenuation.
   The direction on the rank correlation is not known. Mitigations: events only after the date added, the
   sub-period signs, and an optional prospective phase B. No free source of historical constituents or delisted
   prices is available here.
2. **Low power for small effects.** The detectable correlation is about 0.03. The literature suggests a weak
   effect among large caps, so NOT SUPPORTED is likely even if a tiny effect exists.
3. **Timestamp and session alignment.**
   - The release time is verified only for the audit sample. Every other event relies on assumption A1, whose
     failure rate gate G1 measures and bounds at 10% per class.
   - A misalignment can only attenuate the result (section 4).
   - Intraday announcements are excluded because daily data cannot measure them.
   - Extended-hours trading before a release is inside the window and cannot be removed with daily data.
4. **EAR is not a pure earnings surprise.** Guidance, conference-call content and other news are mixed in.
   Interpretation is limited to "the reaction to the announcement day(s)".
5. **Cross-sectional dependence.** Announcements cluster by season and industry. Quarterly cross-sections plus
   HAC address calendar clustering; industry-wide news within a quarter can still make the ranks dependent and
   standard errors too small.
6. **Overlap with the next announcement** at 40 sessions is reported, and E5 tests sensitivity.
7. **Prior use of the data.** The same price histories were used in stages 1 and 2, for different hypotheses. No
   parameter is fitted, so there is no train/test leakage, but the period is not "fresh". Only phase B would be.
8. **Exploratory outcomes** are many by nature. Holm correction applies, and they can never change the
   conclusion.
9. **Single-vendor prices.** yfinance is cross-checked against Cboe on every session used. Both redistribute the
   same exchange closes, so the check catches pipeline errors, not exchange errors.
10. **Selection by timing class.** Excluding INTRADAY events (and POST events if G1b-POST triggers) leaves
    companies whose announcement habits may differ by industry or size. Results by class are reported. A result
    obtained without POST events applies only to pre-open and non-session announcers.
