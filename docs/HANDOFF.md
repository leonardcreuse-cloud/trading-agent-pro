# Handoff — state on 2026-10-11 (end of session)

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

## Saved result files (force-added although reports/*.json is ignored)
`reports/walk_forward.json`, `reports/research_stage1.json`, `reports/research_stage2.json` feed the
validation status of the signal; `reports/weekly/2026-10-09/` is the first weekly report.
The SQLite database (`data/`, ~550 MB) is NOT in git: a new session rebuilds it on the first runs
(`python main.py analyze`, then `python main.py weekly`; SEC requests are throttled). In this session `data/`
holds only the `collect` sources (~93 MB; GDELT raw zips ~6 MB per day): `analyze` / `weekly` not yet re-run.

## Local daily run (decided 2026-10-11)
The database lives on the owner's Windows PC; a scheduled task runs `scripts\daily_run.py` every day at 23:00
Paris (collect + analyze; weekly report on Saturdays). Setup and reasons: `docs/LOCAL_RUN.md`. Cloud sessions
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
4. Audit corrections: SEC acceptanceDateTime labels changed on 2026-10-10 (+4/5 h for ~16 % of
   filings) -> single rule, de-duplicate stored facts, audit back to 0 FAIL; refresh calendars daily;
   Form 4 matching; valuation / cash flow / margins in the report.
5. Later ("voie 2"): prospective weekly record of pre-declared signals vs realised returns (paper only).
