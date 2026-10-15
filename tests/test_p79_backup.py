"""
Nightly journal backup (src/backup.py). git is faked: no command is executed and nothing is pushed.
"""

import subprocess
from datetime import datetime

import pytest


class Git:
    """Records git calls; `reject` = pushes refused for these refs; `changed` = journals differ from HEAD."""

    def __init__(self, changed=True, reject=(), branch='claude/work'):
        self.calls, self.changed, self.reject, self.branch = [], changed, set(reject), branch

    def __call__(self, cmd, **kw):
        assert cmd[0] == 'git' and kw['env']['GIT_TERMINAL_PROMPT'] == '0'
        args = cmd[1:]
        self.calls.append(args)
        code, out = 0, ''
        if args[:2] == ['rev-parse', '--abbrev-ref']:
            out = self.branch
        elif args[:2] == ['diff', '--cached']:
            out = 'reports/paper/transactions.jsonl\nreports/prospective/ledger.jsonl' if self.changed else ''
        elif args[0] == 'push' and args[2].split('refs/heads/')[1] in self.reject:
            code, out = 1, '! [rejected] (fetch first)'
        return subprocess.CompletedProcess(cmd, code, out, '')


@pytest.fixture
def root(tmp_path):
    (tmp_path / 'reports' / 'paper').mkdir(parents=True)
    (tmp_path / 'reports' / 'prospective').mkdir(parents=True)
    return tmp_path


def test_commits_only_the_journals_and_never_forces(root):
    from src.backup import BACKUP_BRANCH, run
    git = Git()
    out = run(runner=git, root=root, now=datetime(2026, 10, 15, 23, 5))
    assert out['status'] == 'OK' and out['committed']
    add = next(a for a in git.calls if a[0] == 'add')
    commit = next(a for a in git.calls if a[0] == 'commit')
    assert add == ['add', '--', 'reports/paper', 'reports/prospective']
    assert commit[-3:] == ['--', 'reports/paper/transactions.jsonl', 'reports/prospective/ledger.jsonl']  # nothing else
    pushes = [a for a in git.calls if a[0] == 'push']
    assert pushes == [['push', 'origin', f'HEAD:refs/heads/{BACKUP_BRANCH}'],
                      ['push', 'origin', 'HEAD:refs/heads/claude/work']]
    flat = ' '.join(' '.join(a) for a in git.calls)
    assert '--force' not in flat and ' -f ' not in flat and 'rebase' not in flat and 'pull' not in flat
    assert '2026-10-15' in ' '.join(commit)


def test_unchanged_journals_are_not_committed_but_still_pushed(root):
    from src.backup import run
    git = Git(changed=False)
    out = run(runner=git, root=root)
    assert not out['committed'] and not any(a[0] == 'commit' for a in git.calls)
    assert out['backup_branch'] and out['status'] == 'OK'


def test_newer_commits_on_github_leave_the_journals_on_the_backup_branch(root):
    from src.backup import run
    out = run(runner=Git(reject={'claude/work'}), root=root)
    assert out['status'] == 'PARTIAL' and out['backup_branch'] and not out['working_branch']
    assert any('git pull' in m for m in out['messages'])


def test_refused_backup_branch_or_detached_head_fails(root):
    from src.backup import BACKUP_BRANCH, run
    assert run(runner=Git(reject={BACKUP_BRANCH, 'claude/work'}), root=root)['status'] == 'FAILED'
    detached = Git(branch='HEAD')
    out = run(runner=detached, root=root)
    assert out['status'] == 'FAILED' and len(detached.calls) == 1        # nothing added, nothing pushed
