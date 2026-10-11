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
| Saturday, 23:00 | the same, then `python main.py weekly` (week ending the day before) |

Logs: `data\logs\<date>_<step>.log`; summary of the latest run: `data\logs\last_run.json` (`"ok": true`).
Exit codes: `collect` returns 2 when at least one source was unavailable (the log line gives the reason); the
task's "Last Run Result" is 1 when any step did not return 0. A failed source is never filled in: the report
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

## Good to know

- The PC must be on (session open) at 23:00. A missed run starts at the next opportunity, but values it
  retrieves after a cutoff do not count for that week's report (they are shown as DATA UNAVAILABLE, with the
  reason). Friday evening is the run that matters most.
- Back up `data\` from time to time: it is the only copy of the history (raw payloads included).
- `scheduler.py` is the older always-on loop that runs `analyze` only, at 08:00; the scheduled task replaces it.
- Remove the task: `Unregister-ScheduledTask -TaskName "TradingAgentPro daily" -Confirm:$false`.
