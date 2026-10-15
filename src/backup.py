"""
Nightly backup of the append-only journals to GitHub (consigne of 2026-10-14, phase 0.3; rule R8).

`python main.py backup`, the last step of scripts/daily_run.py:
1. `git add` and `git commit` of the journal folders only (reports/paper, reports/prospective). Other files are
   never added, and anything else already staged stays out of the commit (pathspec commit).
2. `git push` of the current commit to the backup branch `sauvegarde/journaux-pc`. Only the owner's PC pushes there,
   so every push is a fast-forward.
3. `git push` of the same commit to the working branch, which succeeds only when GitHub has nothing newer. When
   GitHub has newer commits (e.g. code not yet pulled), the push is refused and reported: the journals are safe on
   the backup branch, and the owner merges with `git pull`.

Never `--force`, never a rebase, never a pull: the backup does not change the code that runs on the PC.
GIT_TERMINAL_PROMPT=0: a missing credential fails at once instead of waiting for input in a scheduled task.
Exit code 0 when the journals are on GitHub (backup branch), 1 otherwise.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOURNAL_PATHS = ('reports/paper', 'reports/prospective')
BACKUP_BRANCH = 'sauvegarde/journaux-pc'
REMOTE = 'origin'
TIMEOUT = 180


def _git(args, runner, root):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    try:
        done = runner(['git', *args], cwd=root, capture_output=True, text=True, timeout=TIMEOUT, env=env)
        return done.returncode, ((done.stdout or '') + (done.stderr or '')).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 'error', f'{type(e).__name__}: {e}'


def run(runner=subprocess.run, root=PROJECT_ROOT, now=None):
    """{'status': OK | PARTIAL | FAILED, 'committed', 'backup_branch', 'working_branch', 'messages'}."""
    now = now or datetime.now()
    out = {'status': 'FAILED', 'committed': False, 'backup_branch': False, 'working_branch': False, 'messages': []}
    code, branch = _git(['rev-parse', '--abbrev-ref', 'HEAD'], runner, root)
    if code != 0 or branch in ('', 'HEAD'):
        out['messages'].append(f'not on a git branch ({branch or code}): nothing backed up')
        return out
    paths = [p for p in JOURNAL_PATHS if (Path(root) / p).exists()]
    if not paths:
        out['messages'].append('no journal folder found: nothing backed up')
        return out
    code, text = _git(['add', '--', *paths], runner, root)
    if code != 0:
        out['messages'].append(f'git add failed: {text}')
        return out
    code, names = _git(['diff', '--cached', '--name-only', '--', *paths], runner, root)
    if code != 0:
        out['messages'].append(f'git diff failed: {names}')
        return out
    changed = [n for n in names.splitlines() if n.strip()]
    if changed:
        message = f'Journals: automatic nightly backup ({now.date().isoformat()})'
        # the exact changed journal files: nothing else, even when other files are staged
        code, text = _git(['commit', '-m', message, '--', *changed], runner, root)
        if code != 0:
            out['messages'].append(f'git commit failed: {text}')
            return out
        out['committed'] = True
        out['messages'].append(f'committed: {message}')
    else:
        out['messages'].append('journals unchanged since the last commit')
    code, text = _git(['push', REMOTE, f'HEAD:refs/heads/{BACKUP_BRANCH}'], runner, root)
    out['backup_branch'] = code == 0
    out['messages'].append(f'backup branch {BACKUP_BRANCH}: ' + ('pushed' if code == 0 else f'REFUSED: {text}'))
    code, text = _git(['push', REMOTE, f'HEAD:refs/heads/{branch}'], runner, root)
    out['working_branch'] = code == 0
    out['messages'].append(f'working branch {branch}: ' + (
        'pushed' if code == 0 else
        'not updated (GitHub has newer commits: the journals are on the backup branch; run git pull, then '
        f'git push): {text[:300]}'))
    out['status'] = 'OK' if out['backup_branch'] and out['working_branch'] else (
        'PARTIAL' if out['backup_branch'] else 'FAILED')
    return out
