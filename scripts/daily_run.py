#!/usr/bin/env python3
"""
Daily local run (Windows Task Scheduler or cron): `python scripts/daily_run.py [--weekly | --no-weekly]`

Runs, with this Python interpreter, in the project folder:
  1. python main.py collect   external sources and agency APIs (each value stored with its retrieval time)
  2. python main.py analyze   prices, SEC filings, Form 4 and the daily signal run
  3. python main.py weekly    on Saturdays (local date) unless --no-weekly; --weekly forces it
One failing step does not stop the next ones. Each step writes data/logs/<YYYY-MM-DD>_<step>.log and the run
writes data/logs/last_run.json; the exit code is 1 when a step failed (Task Scheduler "Last Run Result").

Schedule it after the US close, e.g. 23:00 Paris (16:00 New York = 22:00 Paris): values without a publication
time (BLS, EIA, option and earnings-calendar snapshots, release calendars) are admitted by the weekly report only
when retrieved before its cutoff (Saturday 05:00 UTC), so Friday's releases (08:30 New York) and the end-of-session
option snapshot must be collected on Friday evening. See docs/LOCAL_RUN.md.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TIMEOUT_SECONDS = 3 * 3600
SATURDAY = 5


def plan(today, weekly=None):
    """Steps to run on `today` (a date); weekly None = on Saturdays only."""
    steps = ['collect', 'analyze']
    if weekly or (weekly is None and today.weekday() == SATURDAY):
        steps.append('weekly')
    return steps


def interpreter():
    """python.exe rather than pythonw.exe for the steps (their output is written to the log files)."""
    exe = Path(sys.executable)
    if exe.name.lower() == 'pythonw.exe' and (exe.parent / 'python.exe').exists():
        return str(exe.parent / 'python.exe')
    return str(exe)


def run_step(step, log_path, runner=subprocess.run):
    """Run `python main.py <step>`, output to log_path; returns {'step', 'exit_code', 'seconds', 'log'}."""
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)          # no console window on Windows
    start = time.monotonic()
    with open(log_path, 'a', encoding='utf-8') as log:
        log.write(f'=== {datetime.now().isoformat(timespec="seconds")} python main.py {step}\n')
        log.flush()
        try:
            done = runner([interpreter(), 'main.py', step], cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT,
                          env=env, timeout=TIMEOUT_SECONDS, creationflags=flags)
            code = done.returncode
        except subprocess.TimeoutExpired:
            log.write(f'\n=== timeout after {TIMEOUT_SECONDS} s\n')
            code = 'timeout'
        except OSError as e:
            log.write(f'\n=== could not start: {type(e).__name__}: {e}\n')
            code = 'not started'
    return {'step': step, 'exit_code': code, 'seconds': round(time.monotonic() - start), 'log': str(log_path)}


def main(argv=None, runner=subprocess.run, now=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--weekly', action='store_true', help='also run the weekly report today')
    group.add_argument('--no-weekly', action='store_true', help='never run the weekly report today')
    args = parser.parse_args(argv)
    now = now or datetime.now()
    weekly = True if args.weekly else False if args.no_weekly else None
    logs = PROJECT_ROOT / 'data' / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    results = [run_step(step, logs / f'{now.date().isoformat()}_{step}.log', runner)
               for step in plan(now.date(), weekly)]
    ok = all(r['exit_code'] == 0 for r in results)
    summary = {'started_at': now.isoformat(timespec='seconds'), 'ok': ok, 'steps': results}
    (logs / 'last_run.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
    for r in results:
        print(f"{r['step']:8} exit {r['exit_code']}  {r['seconds']:5d} s  {r['log']}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
