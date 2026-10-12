# Stage 3 pre-registration — prospective weekly record (paper only)

Written on 2026-10-12, after stage 2 (`docs/research/STAGE2_RESULTS.md`: 0 of 4 hypotheses confirmed) and
**before any stage 3 record exists**. The git commit that adds this file is the timestamp of the
pre-registration; the next commit fixes the same protocol in code (`src/prospective.py`: `PROTOCOL`,
`UNIVERSE`, `HORIZONS`, `MIN_RECORDS`, `MIN_TICKERS`, `ALPHA`) before the first record is made.

Why a stage 3: stages 1 and 2 used the same years (2017-2026). Only signals recorded **before** their
outcomes exist can test the system out of time, without any possibility of fitting or selecting on the
outcomes. Nothing is traded: the record is on paper and is not a trade recommendation.

## What is recorded

- **Signal**: the ex-news combined heuristic score of `ScoringSignalFixed` (technical, fundamentals and
  insider components, weights 0.25 / 0.40 / 0.15 renormalised over the available components, at least 2
  components; labels POSITIVE >= 65, NEGATIVE <= 40), computed exactly as the walk-forward computes it
  (`WalkForward.score_at`, shared code):
  - technical: `PriceTechnical.score_closes` on the adjusted closes up to and including s0;
  - fundamentals: `ScoringFundamentals.score_inputs(SECParser.fundamentals(t, known_at=T))`;
  - insider: Form 4 transactions filed in (T − 90 days, T], unavailable when that window is not fully
    covered by the downloaded filings or contains a Form 4 that could not be read.
  News is excluded (as in the walk-forward): the daily news score covers the configured universe only.
- **Universe**: frozen at this commit, the 40 tickers of `validation_universe` in `scheduler_config.json`
  (copied into `src/prospective.py`; a later config change does not change the stage 3 universe).
- **Signal session s0**: the last session of the SPY daily bars (yfinance) with 05:00 UTC the next day at or
  before the generation time (the weekly report's rule). **Signal instant T** = 21:00 UTC on s0 (the
  walk-forward convention).
- **When**: `python main.py prospective record`, run by `scripts/daily_run.py` every Saturday evening.
- **Storage**: one file per s0, `reports/prospective/records/record_<s0>.json`, created once and never
  overwritten; its SHA-256 (canonical JSON) is appended to the hash-chained ledger
  `reports/prospective/ledger.jsonl`. Each record keeps the scores themselves: a later code change never
  rewrites a past signal.

## Outcome

- **Entry**: close of s1, the first SPY session after s0. **Exit**: close of the H-th session after s1 in
  the ticker's own daily bars. Return = adjusted close(exit) / adjusted close(entry) − 1 (prices read at
  evaluation time).
- **Horizons**: H = 20 and H = 5 sessions.

## Validity of a weekly record (checked at evaluation, all required)

1. **Integrity**: its SHA-256 equals its ledger entry and the ledger chain verifies up to that entry.
2. **Timing**: generated before 13:30 UTC on s1 (the earliest US open in UTC), i.e. before any price of the
   entry session existed.
3. **Weekly spacing**: s0 is the last session of its ISO week in the SPY bars seen at evaluation.
4. **Cross-section**: at least 10 tickers with a combined score and a realised return at H.

An invalid record is listed with its reason and never used. A missing week is never filled in.

## Confirmatory hypotheses (family of 2, Bonferroni, α = 0.05)

| ID | Statistic | Expected sign | Horizon |
|---|---|---|---|
| P1 | mean weekly cross-sectional Spearman IC of the ex-news combined score | + | 20 sessions |
| P2 | idem | + | 5 sessions |

- Weekly IC = Spearman correlation across tickers between the combined score and the realised return.
- Test = `walk_forward.cross_sectional_ic` (mean over weeks, t = mean / sd × √n_eff, n_eff = n × min(1,
  5 / H) for overlapping windows), two-sided p = `two_sided_p(t)` rounded to 4 decimals: the production
  criterion of `validation_status`.
- A hypothesis is **confirmed** only if its mean IC is > 0 and p < 0.025 (= 0.05 / 2).
- **Confirmatory sample**: the first 52 valid records, in s0 order, whose outcome is evaluable at that
  horizon (about one year). The test is run **once** per horizon, when that sample is complete. Records after
  the 52nd are reported descriptively and never re-test P1 or P2.
- Before the sample is complete, the weekly report shows the progress (n / 52) and interim figures
  (mean IC, share of positive weeks) **without t-statistic, p-value or conclusion**.
- Power: at 20 sessions n_eff = 13 for 52 weekly records, so only a large and stable IC can be confirmed;
  a non-confirmation is not evidence of no effect.

## Exploratory (reported, cannot confirm anything)

Cross-sectional IC of each component (technical, fundamentals, insider); mean return and hit rate per
signal class versus the equal-weight universe; the feature vector stored in each record.

## Decision rule

- P1 or P2 confirmed → the weekly report's Q11 states it, with the effect size and its interval, as a
  prospective, out-of-time result for the ex-news heuristic over this universe. It remains a ranking
  statement, not a trade recommendation; using it to change how the report labels model outputs requires a
  separate, documented code change.
- Neither confirmed → the quantitative section keeps the "not demonstrated" label; the record continues
  descriptively.
- Not changed after the first record: universe, signal definition, horizons, entry and exit rules, validity
  rules, sample size and test. A change to the scoring code that would change the scores starts a new
  series under a new protocol version (a dated amendment below); records of different versions are never
  pooled.

## Known limitations

- Adjusted prices are the vintage read at evaluation (Yahoo revises them after dividends and splits).
- Session close instant 21:00 UTC is an estimate (20:00 UTC in US summer time); the timing rule uses the
  open of s1, which is conservative.
- The universe was chosen in 2026 (current large caps): selection bias in what is studied, but no look-ahead
  in the outcomes, which are all after the records.
- No transaction costs, positions or risk: ranking skill only.
- The ledger is local (the owner's PC): it detects a changed or removed record, not a ledger rebuilt from
  scratch. An external timestamp is obtained by committing `reports/prospective/` to the repository
  (`docs/LOCAL_RUN.md`).
