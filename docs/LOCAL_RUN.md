# Local daily run (owner's Windows machine)

Decided on 2026-10-11: the database lives on the owner's PC (`data\trading_pro.db`, not in git) and a
Windows scheduled task runs the pipeline every day. Cloud sessions start with an empty database and never
see the local one.

Why daily, and why in the evening: values without a publication time (BLS and EIA API values, option and
earnings-calendar snapshots, BLS and FRED release calendars) count in a weekly report only when they were
retrieved before its cutoff, Saturday 05:00 UTC (06:00 or 07:00 Paris). A run at 23:00 Paris, after the US
close (16:00 New York = 22:00 Paris, 17:00 or 18:00 New York when the clocks change on different dates), also
collects Friday's releases (08:30 New York) and an end-of-session option snapshot before the cutoff.

## What runs

| When (local time) | `scripts\daily_run.py` runs |
|---|---|
| every day, 23:00 | `python main.py collect`, then `python main.py analyze` |
| every day, 23:00 | then `python main.py paper` (paper strategy PT1: orders, fills, stops, marks) |
| Saturday, 23:00 | the same, plus `python main.py prospective` (stage 3 weekly record) |
| Sunday, 23:00 | the same, plus `prospective` (catches a missed Saturday) and `python main.py weekly` (week ending Friday; on Sunday evening the news window is complete) |

Logs: `data\logs\<date>_<step>.log`; summary of the latest run: `data\logs\last_run.json` (`"ok": true`).
Exit codes: `collect` returns 2 when at least one source was unavailable (the log line gives the reason);
`weekly` returns 3 when a critical section failed (report status INCOMPLETE, written in the report and its
manifest; the report is still archived); the task's "Last Run Result" is 1 when any step did not return 0. A failed source is never filled in: the report
shows it as DATA UNAVAILABLE.

## One-time setup (PowerShell, in `C:\Users\leona\trading-agent-pro`)

1. Get the code of the branch (until it is merged): `git fetch origin`, then
   `git checkout claude/nifty-ramanujan-u1p317` and `git pull`.
2. Update the packages: `venv\Scripts\pip install -r requirements.txt`.
3. In `.env` (see `.env.example`), add `BLS_API_KEY`, `BEA_API_KEY` and `EIA_API_KEY` (same values as the
   cloud environment) and check `SEC_USER_AGENT` = `Name email` (a space, then a real address).
   `venv\Scripts\python main.py status` must show every key as `set`.
4. Test once: `venv\Scripts\python scripts\daily_run.py --no-weekly`, then check `data\logs\last_run.json`.
5. Register the task: `powershell -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1`
   (option `-Time 23:30`). It runs for the current user, without administrator rights.
6. Check it: `Start-ScheduledTask -TaskName "TradingAgentPro daily"`, then
   `Get-ScheduledTaskInfo -TaskName "TradingAgentPro daily"` (LastTaskResult 0 = success).
7. Stage 3 record: after the pull, `reports\prospective\ledger.jsonl` must exist (first record, week of
   2026-10-09, made in the cloud before the 2026-10-12 open). Pull **before** the first weekend run: a run
   without that file would start a second, separate ledger.
8. Once, after the first run on the updated code: `venv\Scripts\python main.py dedupe` (removes the old
   SEC versions made redundant by the calibrated acceptance times; it backs the database up first into
   `data\backups\`, so keep free disk space of about twice the database size), then
   `venv\Scripts\python main.py audit` (expected: 0 FAIL).

## Stage 3 record (paper only)

`python main.py prospective` makes the weekly signal record of the 40 validation tickers, then evaluates
all records against realised returns (protocol: `docs/research/STAGE3_PREREGISTRATION.md`).

- One record per week, `reports\prospective\records\record_<Friday>.json`, plus one line in
  `reports\prospective\ledger.jsonl` (hash chain). It is made only between Saturday 05:00 UTC and Monday
  13:30 UTC (before the next session can open); outside that window the command says `NOT DUE` (exit 0).
  A weekend with the PC off leaves the week missing: it is never filled in later.
- Never edit, move or delete a record or the ledger: a changed record is excluded by the evaluation, and a
  broken chain stops new records (`LEDGER BROKEN`, exit 1) until it is repaired from git.
- External timestamp (recommended each week, e.g. Sunday): `git add reports/prospective`,
  `git commit -m "Stage 3 record <date>"`, `git push`. The evaluation files (`evaluation.json`, `history\`)
  are derived and ignored by git.
- The weekly report (Q11) shows the progress: records generated and the latest evaluation computed before
  its cutoff. The Saturday evaluation runs after that week's cutoff, so the report shows the previous one.
- The pre-registered test runs once per horizon, after 52 valid weekly records (about one year); its result
  is frozen in `reports\prospective\confirmatory_<H>d.json` (commit it too).

## Paper strategy PT1 (paper only)

`python main.py paper` runs every day (after `analyze`): it turns a new stage 3 record into market-on-open
orders, then fills them, applies stops, dividends and splits, and marks the portfolio at the close
(`docs/research/PAPER_STRATEGY_PT1.md`). Nothing is ever sent to a broker. The journals
`reports\paper\transactions.jsonl` and `reports\paper\predictions.jsonl` are append-only and hash-chained:
never edit them. Commit them with the stage 3 files each week (`git add reports/paper reports/prospective`).
The first orders (record of 2026-10-09) were placed in the cloud before the 2026-10-12 open; pull before running
`paper` on the PC so that the PC continues the same journals.

## Good to know

- The PC must be on (session open) at 23:00. A missed run starts at the next opportunity, but values it
  retrieves after a cutoff do not count for that week's report (they are shown as DATA UNAVAILABLE, with the
  reason). Friday evening is the run that matters most.
- Back up `data\` from time to time: it is the only copy of the history (raw payloads included).
- `scheduler.py` is the older always-on loop that runs `analyze` only, at 08:00; the scheduled task replaces it.
- Remove the task: `Unregister-ScheduledTask -TaskName "TradingAgentPro daily" -Confirm:$false`.
