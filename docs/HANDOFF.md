# Handoff — state on 2026-10-12

## Done and pushed
- Data layer with provenance (SEC XBRL / Form 4, FRED vintages, yfinance, NewsAPI), point-in-time rules,
  `python main.py audit`.
- Signals relabelled (quantitative signal, never a trade recommendation); validation status shown.
- Research: walk-forward (40 tickers), stage 1 (148 stocks), stage 2 holdout (242 stocks):
  **no statistically reliable predictive edge** (0 of 4 pre-registered hypotheses confirmed;
  `docs/research/STAGE1_RESULTS.md`, `docs/research/STAGE2_RESULTS.md`).
- Weekly analyst report `python main.py weekly` (first report: `reports/weekly/2026-10-09/`).
- P4.0 phase 1: `python main.py collect` (src/external_sources.py): CFTC COT, FINRA short interest,
  Cboe put/call, Fed FOMC calendar, BLS release schedules, Federal Register (BIS, OFAC, USTR,
  presidential documents), GPR index, GDELT daily events, yfinance option snapshots.
- P4.0 live run (2026-10-11, project database `data/`, ~93 MB): all 12 collectors OK. First run 7,553 values
  (CFTC 1,653 - 57 weekly reports x 8 contracts; FINRA 1,827 - history since 2019-20; Cboe 384 - 64 sessions;
  FOMC 57 meetings 2021-2027; BLS schedules 62; BLS API 293; BEA 112; EIA 1,317; Federal Register 122; GPR
  1,185; GDELT 525 - 15 days; options 16). Fixed from the live responses: binary raw payloads (GDELT zip, GPR
  xls) were stored corrupted (UTF-8 decoding) -> now byte for byte; BLS per-release schedule pages omit the
  current month's releases (CPI 10-14, PPI 10-15) -> monthly calendars added; GPR (two Last-Modified values for
  the same file) and Federal Register (future-dated documents clamped to each retrieval) re-stored unchanged
  values at every run -> an unchanged value keeps its stored publication date; one transient connection reset
  (EIA) -> one retry, never after a proxy refusal. Third run: 0 new rows; storage audit PASS. The second run
  left 1,185 GPR and 4 Federal Register duplicate versions (same values, real header / retrieval dates): kept,
  harmless (history is never deleted).
- P4.1: keyed agency APIs `src/agency_apis.py` (BLS v2: 15 series - CPI, PPI, jobs, earnings, JOLTS; BEA:
  NIPA tables 1.1.1 / 2.8.4 / 2.6 - GDP, PCE, PCE prices, income, saving rate; EIA: 12 series - oil and gas spot
  prices, weekly stocks, production, refinery utilisation, retail fuel prices, gas storage), run by
  `python main.py collect`. Tested offline on real payload excerpts and live (see the live run above).

- P4.0 phase 2: the new data are wired into the weekly report (sections `catalysts`, new `positioning`,
  `geopolitics`, `agencies`; SP500 cross-check fixed; stale "blocked" items removed). Live report for the week
  ending 2026-10-09: `reports/weekly/2026-10-09/weekly_v3.*` (v2 was the same run before a cosmetic fix).

- P5.0 (stage 3, "voie 2"): prospective weekly record, paper only. Pre-registration committed first
  (`docs/research/STAGE3_PREREGISTRATION.md`, commit 4ddae81), code next (318ef56: `src/prospective.py`,
  `python main.py prospective [record|evaluate]`, weekly Q11 progress), then the first record: week of
  2026-10-09, generated 2026-10-12T06:45:13Z in the cloud and pushed at 06:45:53Z, before the 13:30 UTC open
  (40/40 tickers scored: 13 POSITIVE, 27 NEUTRAL). Its `code_version` reads `318ef56-dirty`: the only uncommitted
  changes were two docs files.

- Master mission P0-P6 (2026-10-12): the analyst platform is complete and validated. Per-phase files, tests,
  live results and limitations: `docs/MISSION_STATUS.md`; summary: `docs/CHANGELOG.md`.
  - The weekly report has 22 parts and a COMPLETE / INCOMPLETE status.
  - Fundamentals, valuation and DCF; technical analysis; risk engine.
  - Hash-chained journals; paper strategy PT1 (started 2026-10-12, 8 market-on-open orders).
  - Tests: 562 passed.
  - Final audit: 0 FAIL, 19 explained WARNs.
  - No predictive ability is demonstrated anywhere; stage 3 and PT1 are the only open tests.

- Gap round G0–G6 (2026-10-12): the second pass over every requirement of the mission.
  - The requirement-by-requirement state is in `docs/REQUIREMENTS_TRACEABILITY.md`.
  - New commands: `sources`, `dashboard`, `verify-report`, `weekly --verify`, `paper report`.
  - New data: the Cboe second price source and company guidance quoted from 8-K earnings releases.
  - Tests: 598 passed.
  - Audit: 0 FAIL.
  - Weekly v16: replay IDENTICAL, source verification 84 / 84.
  - To widen the cloud environment's network (World Bank, ECB, Treasury, Census, NY Fed, OFR, IMF,
    U. Michigan, USGS, Stooq are refused today): environment settings, Network access, Allowed domains
    (https://code.claude.com/docs/en/cloud-environments#network-access). Then run `python main.py sources`
    again.

- 2026-10-12, owner's brief (preserve validation, propose stage 4, review blocked sources):
  - Stage 3 and PT1 continue unchanged. With the current code, the 40 scores of the 2026-10-09 record
    recompute identically, and the journals and ledger chains verify.
  - Stage 4 pre-registration PROPOSAL (post-earnings drift after the market's reaction):
    `docs/research/stage4_proposal/STAGE4_PREREGISTRATION_PROPOSAL.md`, with a filings-only feasibility count.
    NOT RUN: it waits for the owner's approval.
  - Blocked sources review: `docs/SOURCE_ACCESS_REVIEW.md`. It recommends USGS minerals data (priority 1) and,
    optionally, Treasury FiscalData; nothing else.

## Saved result files (force-added although reports/*.json is ignored)
`reports/walk_forward.json`, `reports/research_stage1.json`, `reports/research_stage2.json` feed the
validation status of the signal; `reports/weekly/2026-10-09/` is the first weekly report.
`reports/prospective/records/` and `reports/prospective/ledger.jsonl` (stage 3) are tracked normally: commit
them every week from the PC (external timestamp); `evaluation.json` and `history/` are derived and ignored.
The SQLite database (`data/`, ~550 MB) is NOT in git: a new session rebuilds it on the first runs
(`python main.py analyze`, then `python main.py weekly`; SEC requests are throttled). In this session `data/`
holds only the `collect` sources (~93 MB; GDELT raw zips ~6 MB per day): `analyze` / `weekly` not yet re-run.

## Local daily run (decided 2026-10-11)
The database lives on the owner's Windows PC; a scheduled task runs `scripts\daily_run.py` every day at 23:00
Paris (collect, analyze, paper; stage 3 record on weekends; weekly report on Sundays). Setup and reasons: `docs/LOCAL_RUN.md`. Cloud sessions
start with an empty database: use them for development, the local run for the real reports.

## Environment checklist (owner)
- Environment variables, one per line `NAME=value`: `FRED_API_KEY`, `NEWSAPI_KEY`, `SEC_USER_AGENT`,
  and the new `BLS_API_KEY`, `BEA_API_KEY`, `EIA_API_KEY` (read in a session started after saving).
- Allowed domains: www.cftc.gov, publicreporting.cftc.gov, www.cboe.com, cdn.cboe.com, cdn-api.cboe.com,
  www.theocc.com, www.finra.org, cdn.finra.org, api.finra.org, api.bls.gov, www.bls.gov,
  www.federalreserve.gov, api.gdeltproject.org, data.gdeltproject.org, finance.yahoo.com, fc.yahoo.com,
  query1.finance.yahoo.com, query2.finance.yahoo.com, www.federalregister.gov,
  sanctionslist.ofac.treas.gov, www.bis.gov, ustr.gov, apps.bea.gov, api.eia.gov,
  www.matteoiacoviello.com (Nasdaq's internal API and OCC are deliberately not used), plus the
  pre-existing api.stlouisfed.org, newsapi.org, data.sec.gov, www.sec.gov (keep them when editing the list).
- `SEC_USER_AGENT` must be `Name email` (a space, then a real address): www.sec.gov answers 403 otherwise,
  while data.sec.gov still accepts it.

### Key check on 2026-10-11 (live)
FRED, NewsAPI, BLS v2, BEA, EIA: OK. All allowed domains reachable through the proxy.
SEC: data.sec.gov OK; www.sec.gov 403 with the old User-Agent (no email), 200 with the `Name email`
format -> owner fixed the variable.
Re-checked in the next session (2026-10-11, live): `SEC_USER_AGENT` has the `Name email` format; www.sec.gov
(company_tickers.json, browse-edgar, Archives Form 4 XML) and data.sec.gov (submissions, companyfacts) all
answer 200; without a User-Agent www.sec.gov answers 403. BLS v2, BEA and EIA keys verified by real data calls.

## Next (agreed: "voie 1" — a real weekly financial-analysis assistant, no prediction claims)
1. Done (P4.1): keys verified live; BLS v2 / BEA / EIA clients in `src/agency_apis.py`.
2. Done: `python main.py collect` run live, parsers and storage fixed (see above). Run `collect` daily: BLS and
   EIA values carry no publication date (retrieval time), so the weekly report only sees a release after a
   collect run that followed it.
3. Done (P4.0 phase 2): positioning, geopolitics and agencies sections; FOMC / BLS calendars and earnings
   snapshots in catalysts; SP500 cross-check; stale items removed. Open points: the daily run on the owner's
   PC (`docs/LOCAL_RUN.md`) is what makes BLS, EIA, option and earnings snapshots, BLS calendars and FRED
   release calendars admissible (retrieved before a cutoff); most new DATA UNAVAILABLE items of the 2026-10-09
   report come from their absence; GDP and
   commodities are read from BEA / EIA (agencies section), not added to the FRED macro tables; BLS October 2025
   does not exist (2025 shutdown), so a 12-month change that needs it is DATA UNAVAILABLE.
4. Done (P4.2): SEC label conventions verified on EDGAR index pages and converted to true acceptance times;
   `python main.py dedupe` for redundant versions (audit: 0 FAIL, 441 PASS on the cloud database); Form 4
   document markers; FRED release calendars collected daily; margins / cash flow / dilution / derived
   valuation in Q2. On the owner's PC, once after pulling: `python main.py analyze`, then
   `python main.py dedupe` (it backs the whole database up first: free disk space about twice its size),
   then `python main.py audit`.
5. Done (P5.0): stage 3 prospective record (see above). From now on it runs by itself on the PC every weekend
   (`scripts/daily_run.py`); the pre-registered test happens once, after 52 valid weekly records (about
   October 2027 at 5 sessions, a month later at 20). Until then the weekly report shows the progress and
   interim figures only. Nothing in the protocol may change; a scoring change that alters scores means a new
   series (amendment in the pre-registration).

## Owner actions on the PC (in this order)
1. `git fetch origin`, `git checkout claude/nifty-ramanujan-u1p317`, `git pull`. This brings the code, the
   first stage 3 record and ledger, and the PT1 journals. Pull BEFORE the next daily run on the PC
   (23:00 Paris, from 2026-10-12): its `paper` step must continue the pushed journals, whose 8 orders fill at
   the 2026-10-12 open. If a run already created `reports\paper\*.jsonl` locally, move those files to a
   backup folder before pulling. Never merge two journals.
2. `venv\Scripts\pip install -r requirements.txt`; add `BLS_API_KEY`, `BEA_API_KEY`, `EIA_API_KEY` to `.env`;
   `venv\Scripts\python main.py status`.
3. `venv\Scripts\python scripts\daily_run.py --no-weekly` once, then
   `powershell -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1` (untested on Windows: report any
   error message).
4. Once: `venv\Scripts\python main.py dedupe`, then `venv\Scripts\python main.py audit` (expected 0 FAIL).
5. Every week (e.g. Sunday): `git add reports/prospective reports/paper`,
   `git commit -m "Stage 3 record and PT1 journals <date>"`, `git push`.
6. If `python main.py weekly` exits with 3, a critical section failed. The report is still written, with
   status INCOMPLETE and the reason; read its "Report status" line.
