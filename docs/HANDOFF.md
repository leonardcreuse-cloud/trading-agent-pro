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
  presidential documents), GPR index, GDELT daily events, yfinance option snapshots. Tested offline on
  real payload excerpts; NOT yet run live (the hosts were refused by the network policy at the time).

## Saved result files (force-added although reports/*.json is ignored)
`reports/walk_forward.json`, `reports/research_stage1.json`, `reports/research_stage2.json` feed the
validation status of the signal; `reports/weekly/2026-10-09/` is the first weekly report.
The SQLite database (`data/`, ~550 MB) is NOT in git: a new session rebuilds it on the first runs
(`python main.py analyze`, then `python main.py weekly`; SEC requests are throttled).

## Environment checklist (owner)
- Environment variables, one per line `NAME=value`: `FRED_API_KEY`, `NEWSAPI_KEY`, `SEC_USER_AGENT`,
  and the new `BLS_API_KEY`, `BEA_API_KEY`, `EIA_API_KEY` (read in a session started after saving).
- Allowed domains: www.cftc.gov, publicreporting.cftc.gov, www.cboe.com, cdn.cboe.com, cdn-api.cboe.com,
  www.theocc.com, www.finra.org, cdn.finra.org, api.finra.org, api.bls.gov, www.bls.gov,
  www.federalreserve.gov, api.gdeltproject.org, data.gdeltproject.org, finance.yahoo.com, fc.yahoo.com,
  query1.finance.yahoo.com, query2.finance.yahoo.com, www.federalregister.gov,
  sanctionslist.ofac.treas.gov, www.bis.gov, ustr.gov, apps.bea.gov, api.eia.gov,
  www.matteoiacoviello.com (Nasdaq's internal API and OCC are deliberately not used).

## Next (agreed: "voie 1" — a real weekly financial-analysis assistant, no prediction claims)
1. Verify the three new keys live; add BLS v2 / BEA / EIA clients that read them (DATA UNAVAILABLE when
   a key is missing).
2. Run `python main.py collect` live; fix any parser against the real responses.
3. P4.0 phase 2 — wire into the weekly report: a `positioning` section (COT, Cboe put/call, FINRA short
   interest, option IV), FOMC + BLS calendars and earnings dates in `catalysts`, GDP + commodities (FRED)
   and Federal Register / GPR / GDELT in `macro` Q4; fix the FRED SP500 cross-check (series not in
   ALFRED: request without realtime parameters); remove the now-resolved DATA UNAVAILABLE items.
4. Audit corrections: SEC acceptanceDateTime labels changed on 2026-10-10 (+4/5 h for ~16 % of
   filings) -> single rule, de-duplicate stored facts, audit back to 0 FAIL; refresh calendars daily;
   Form 4 matching; valuation / cash flow / margins in the report.
5. Later ("voie 2"): prospective weekly record of pre-declared signals vs realised returns (paper only).
