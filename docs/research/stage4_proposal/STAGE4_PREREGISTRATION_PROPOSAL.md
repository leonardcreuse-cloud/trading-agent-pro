# Stage 4 — pre-registration PROPOSAL: drift after the market's reaction to earnings announcements

**Status: PROPOSAL, awaiting the owner's review and approval. NOT RUN.**

- No price, return or outcome of this study has been downloaded or computed.
- The only data read so far are SEC filing lists and index pages, for the feasibility counts in
  `feasibility.json` (script `feasibility.py`).
- On approval, the approved text is copied to `docs/research/STAGE4_PREREGISTRATION.md` and committed with its
  SHA-256, before any price is downloaded. Results go to a write-once `reports/research_stage4.json`.
- This study changes nothing in the production signal, stage 3 or the paper strategy PT1, and its result is never
  used by them.

Proposal version: `stage4-proposal-v1` (2026-10-12).

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
  positively rank-correlated with the market-adjusted return over the next 40 trading sessions, entered at the
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

**Feasibility (filings only, seeded sample of 60 companies, `feasibility.json`).**
- 1,911 events, extrapolated to about 15,900 for the full list, or about 400 per calendar quarter.
- Events per year grow with index additions.
- Earnings seasons concentrate events: about 2% of events fall in each of March, June, September and December.

## 3. Variables: source and definition

| Variable | Source | Definition |
|---|---|---|
| Announcement | SEC EDGAR submissions feed (rank 1) | Form `8-K` (not `8-K/A`) whose items include `2.02`, and no other 8-K item 2.02 of the same company accepted in the preceding 45 calendar days. Later ones are excluded and counted. At most one event per company per calendar quarter (the first). |
| t_A | EDGAR filing index page, "Accepted" field (New York time) | The acceptance instant. The feed's `acceptanceDateTime` label is not used. |
| Sessions | SPY daily bars (yfinance) | The trading-session calendar. |
| Prices | yfinance daily bars (rank 2), auto-adjusted for splits and dividends: open and close | Ratios of adjusted prices are total returns within a window. |
| Price cross-check | Cboe delayed daily history (rank 2) | yfinance unadjusted close vs Cboe close on every session used, tolerance 0.5% (see 13). |
| Benchmark | SPY, same source and adjustment | See 8. |
| Sector (exploratory only) | GICS sector in the frozen list (today's classification) | Mapped to the SPDR sector ETF. |

**Session definitions.**
- **d_pre**: the last session strictly before the calendar date of t_A.
- **d0**: the session of t_A if t_A falls on a session before 16:00 New York; otherwise the first session after
  t_A.

**Return definitions.**
- **EAR** = P(close d0+1) / P(close d_pre) − SPY(close d0+1) / SPY(close d_pre).
- **DRIFT40** = P(close d0+41) / P(open d0+2) − SPY(close d0+41) / SPY(open d0+2). This is a holding period of
  40 sessions, d0+2 to d0+41.

## 4. Timestamp and information-availability rules

- **Announcement time.** An announcement is public no earlier than its press release and, by this rule, no later
  than its SEC acceptance. The acceptance time t_A is the authoritative, verifiable timestamp.
- **Reaction window.** It starts at the close of the session before t_A's calendar day. It therefore includes a
  release made earlier on the same day (e.g. a newswire release before the 8-K).
- **Timestamp audit (gate G1).**
  - Before any price is downloaded: for a seeded random sample of 100 events, the release date is read from the
    exhibit 99 dateline. The rule is in `feasibility.py`; undetected datelines are read by hand and recorded in
    `docs/research/stage4/dateline_audit.csv`.
  - The study is INVALID as designed if more than 10% of the sample has a release dated at least one calendar day
    before t_A's date.
  - Feasibility: 30 of 30 detected datelines were on the acceptance date; 30 of 60 had a format the rule did not
    detect.
- **EAR availability.** EAR uses closes up to d0+1, available after that session's close.
- **Point-in-time inputs.**
  - Adjusted prices are back-adjusted with later dividends, but a ratio inside a window depends only on dividends
    inside that window, so no later information enters the window.
  - No parameter is estimated from data (no beta, no fitted threshold), so there is no training set to leak.

## 5. Announcements during and outside market hours

Acceptance-time classes in New York time; feasibility sample of 60: 39 pre-open, 19 after close, 2 intraday.

| t_A | d0 | Reaction window (closes) |
|---|---|---|
| Before 09:30 on a session | the same session | d_pre → d0+1: two sessions |
| 09:30–16:00 on a session | the same session | d_pre → d0+1: two sessions, including the pre-release part of d0 |
| 16:00 or later, or on a non-session day | the next session | d_pre → d0+1: three sessions, so a same-day earlier release is still inside |

**Early-close days.** The exchange calendar is unknown, so an acceptance between an early close and 16:00 is
classed as intraday. Its reaction still falls on d0 or d0+1, inside the window.

**Diagnostic.** The primary statistic is also reported by timing class. This is descriptive, not a test.

## 6. Entry timestamp and executable reference price

- **Decision time.** After the close of d0+1, when EAR is known from end-of-day data.
- **Entry.** The open of d0+2: a market-on-open order sent before that open.
- **Reference price.** The adjusted open of d0+2 (yfinance). The Cboe open of d0+2 is reported beside it as a
  check.
- **Not used.** No price at or before the signal's close is used for entry.

## 7. Primary horizon and outcome metric

- **Horizon.** H = 40 sessions, chosen before any data.
  - The usual 60-day window would often reach the company's next quarterly announcement (about 63 sessions
    later) and mix in its news.
  - 40 sessions keeps almost all windows before it.
  - The share of windows that still contain the company's next 8-K item 2.02 is reported.
- **Outcome.** DRIFT40 (market-adjusted, open-to-close, total return).
- **Primary statistic.** The mean over calendar quarters of the Spearman correlation between EAR and DRIFT40.
  - Events are assigned to the quarter of their entry date d0+2.
  - Ties are averaged.

## 8. Benchmark

- **Primary.** SPY total return over the same window (market adjustment, no estimated beta).
- **Exploratory.** The SPDR ETF of the company's GICS sector (E4).

## 9. Transaction costs and execution assumptions

- **Primary statistic.** It is cost-free: it measures information in EAR, not profitability. No profitability is
  claimed from it.
- **Exploratory E3 (tradable form).**
  - Each quarter, the long leg is the events in the top quintile of EAR and the short leg the bottom quintile.
  - The quintile breakpoints come from the previous quarter's EAR distribution, known at entry: no look-ahead.
  - Equal weight; entry at the open of d0+2, exit at the close of d0+41.
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

## 11. Statistical test and confidence interval

- **Statistic.** For each quarter q with at least 100 eligible events, ρ_q = Spearman(EAR, DRIFT40). The
  statistic is the mean of ρ_q over those quarters.
- **Standard error.** Newey–West HAC with Bartlett weights and lag 1, because windows of late-quarter events
  extend into the next quarter.
- **Test.** t = mean / SE with M − 1 degrees of freedom; two-sided p-value.
- **Confidence interval.** 95% CI = mean ± t(0.975, M−1) × SE.
- **Why this design.**
  - Quarterly cross-sections absorb the clustering of announcements in calendar time.
  - Ranks limit the influence of extreme returns.
  - Each company appears at most once per quarter.
- **Also reported, not tested:** the number of events per quarter, the sign of ρ in each of the three
  sub-periods 2016–2018, 2019–2021 and 2022–2025, and results by timing class.

## 12. Multiple-testing controls

**Confirmatory family:** one test (the primary), α = 0.05. Nothing else can change the conclusion.

**Exploratory family:** Holm correction at 0.05 within the family, labelled exploratory in every output.

| ID | Exploratory outcome |
|---|---|
| E1 | Same statistic, horizon 20 sessions |
| E2 | Same statistic, horizon 60 sessions (overlap with next announcements reported) |
| E3 | Quintile long-short, net of costs (section 9): mean quarterly return, HAC t-test |
| E4 | Same statistic with the sector-ETF-adjusted outcome |
| E5 | Same statistic excluding windows that contain the company's next 8-K item 2.02 |

No other horizon, benchmark, subgroup or rule may be added after the data are seen. Any later idea needs a new
pre-registration.

## 13. Exclusions and missing data

All exclusions are decided before outcomes are computed, never on DRIFT, and every count is reported.

**Event-level exclusions.**
- 8-K/A filings; 8-K item 2.02 filings within 45 days after another (the first is kept); a second event of the
  same company in a quarter.
- An index page without an "Accepted" time: excluded, not estimated.
- Any missing yfinance price on a session used (d_pre, d0+1, d0+2, d0+41) or a missing SPY price: excluded.
  Nothing is filled or interpolated.
- yfinance unadjusted close and Cboe close disagreeing by more than 0.5% on a session used (gate G2): excluded.
- Price at d_pre below 5 USD (very rare in this index): excluded.
- Windows ending after the last available session: excluded (censoring, counted).

**Gates.** The study is INVALID as designed if gate G1 fails, if more than 5% of events fail gate G2, or if more
than 20% of candidate events are excluded for missing data.

## 14. Acceptance and rejection criteria

| Outcome | Rule |
|---|---|
| SUPPORTED | The validity minima (section 10) and gates (sections 4 and 13) pass, the mean ρ is > 0, and two-sided p < 0.05 (equivalently, the 95% CI lies above 0). |
| NOT SUPPORTED | Validity passes and p ≥ 0.05. The CI is reported; "no effect" is never claimed. |
| CONTRARY | Validity passes, the mean ρ is < 0 and p < 0.05: evidence of reversal, reported as such, not used. |
| INVALID / INSUFFICIENT DATA | A gate or minimum fails: no hypothesis result is stated. |

**What SUPPORTED means.** It is a historical association in current S&P 500 members, net of none of the
real-world frictions of section 9.

**What it does not allow.** It does not justify a trading rule, a production change or any profitability claim.
Any use would need a separate pre-registered prospective test of at least 52 weeks, like stage 3. That optional
phase B (events after the approval date, frozen universe) would be proposed separately.

## Order of execution after approval

1. Commit `STAGE4_PREREGISTRATION.md` and `universe.csv`, with their SHA-256 values.
2. Build the event table from SEC data only: filings, index pages, t_A. Run gate G1, then freeze the table with
   its hash.
3. Download prices, run gate G2 and the coverage checks, compute EAR and DRIFT, and freeze the table.
4. Compute the primary statistic once, then the exploratory family.
5. Write `reports/research_stage4.json` once, recording the code version and the pre-registration hash.

A recalculation after a data fix uses `--recalc` and keeps the original, as in stages 1 and 2.

## Principal statistical risks (summary for the reviewer)

1. **Survivorship.** Only current members are included; removed or delisted companies are absent. Survivors may
   have had better post-announcement returns after bad reactions, which biases toward reversal or attenuation.
   The direction on the rank correlation is not known. Mitigations: events only after the date added, the
   sub-period signs, and an optional prospective phase B. No free source of historical constituents or delisted
   prices is available here.
2. **Low power for small effects.** The detectable correlation is about 0.03. The literature suggests a weak
   effect among large caps, so NOT SUPPORTED is likely even if a tiny effect exists.
3. **Timestamp error.** The SEC acceptance can lag the press release. Gate G1 measures this, and the window
   design absorbs same-day lags. Lags of a day or more would mismeasure EAR and entry.
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
