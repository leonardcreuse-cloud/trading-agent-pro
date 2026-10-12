"""scripts/daily_run.py: steps per day, logs, exit code. The runner is faked: no command is executed."""

import importlib.util
import json
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('daily_run', Path(__file__).resolve().parent.parent / 'scripts' /
                                              'daily_run.py')
daily_run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(daily_run)


class Runner:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        kw['stdout'].write(f'fake output of {cmd[-1]}\n')
        return subprocess.CompletedProcess(cmd, 1 if cmd[-1] in self.fail else 0)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_run, 'PROJECT_ROOT', tmp_path)
    return tmp_path


def test_plan_runs_the_weekly_report_on_saturdays_and_the_record_on_weekends():
    assert daily_run.plan(date(2026, 10, 9)) == ['collect', 'analyze', 'paper']                        # Friday
    assert daily_run.plan(date(2026, 10, 10)) == ['collect', 'analyze', 'prospective', 'paper']        # Saturday
    assert daily_run.plan(date(2026, 10, 11)) == ['collect', 'analyze', 'prospective', 'paper', 'weekly']  # Sunday
    assert daily_run.plan(date(2026, 10, 11), weekly=False) == ['collect', 'analyze', 'prospective', 'paper']
    assert daily_run.plan(date(2026, 10, 12), weekly=True) == ['collect', 'analyze', 'paper', 'weekly']


def test_steps_logs_summary_and_exit_code(project):
    runner = Runner(fail={'analyze'})
    code = daily_run.main([], runner=runner, now=datetime(2026, 10, 11, 23, 0))
    assert code == 1                                         # analyze failed; weekly still ran
    assert [c[0][-1] for c in runner.calls] == ['collect', 'analyze', 'prospective', 'paper', 'weekly']
    assert all(c[0][1] == 'main.py' and c[1]['cwd'] == project for c in runner.calls)
    assert all(c[1]['env']['PYTHONIOENCODING'] == 'utf-8' for c in runner.calls)
    summary = json.loads((project / 'data' / 'logs' / 'last_run.json').read_text())
    assert summary['ok'] is False and [s['exit_code'] for s in summary['steps']] == [0, 1, 0, 0, 0]
    log = (project / 'data' / 'logs' / '2026-10-11_collect.log').read_text()
    assert 'python main.py collect' in log and 'fake output of collect' in log
    assert daily_run.main(['--no-weekly'], runner=Runner(), now=datetime(2026, 10, 10, 23, 0)) == 0


def test_timeout_is_reported_not_raised(project):
    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    assert daily_run.main(['--no-weekly'], runner=slow, now=datetime(2026, 10, 9, 23, 0)) == 1
    summary = json.loads((project / 'data' / 'logs' / 'last_run.json').read_text())
    assert [s['exit_code'] for s in summary['steps']] == ['timeout', 'timeout', 'timeout']
