#!/usr/bin/env python3
"""
Append-only, hash-chained journals (master mission P4)

Two separate journals, each a JSON-lines file whose entries are never edited or deleted:
  predictions   reports/paper/predictions.jsonl: one 'prediction' entry per ticker and signal (id, ticker,
                timestamp, horizon, data and sources used, available signals, model output, model version,
                assumptions, uncertainties, expected outcome) and, later, one 'outcome' entry that references the
                prediction id (realised return and its dates). A prediction is never rewritten to match an outcome.
  transactions  reports/paper/transactions.jsonl: orders, fills, stops, corporate actions and marks of the paper
                portfolio (signal timestamp, assumed execution price, direction, quantity, stop, exit rule, fees,
                slippage, rationale, realised result, drawdown).
Each entry carries 'seq', 'prev' (hash of the previous entry, GENESIS for the first) and 'hash' = SHA-256 of the
canonical JSON of the entry without 'hash'. verify() walks the chain; an append is refused on a broken chain.
Entries are dictionaries with a 'type'; ids are deterministic (SHA-256 of their defining fields) so that the same
prediction is never recorded twice.
"""

import hashlib
import json
from pathlib import Path

from .common import reports_dir

GENESIS = '0' * 64


def journal_dir(base=None):
    path = Path(base) if base else reports_dir() / 'paper'
    path.mkdir(parents=True, exist_ok=True)
    return path


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def entry_id(*parts):
    return digest([str(p) for p in parts])[:24]


class Journal:
    def __init__(self, name, base=None):
        self.path = journal_dir(base) / f'{name}.jsonl'

    def entries(self):
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding='utf-8').splitlines() if x.strip()]

    def verify(self):
        """{'n', 'ok', 'problem', 'head'}: walks the hash chain."""
        prev = GENESIS
        lines = self.path.read_text(encoding='utf-8').splitlines() if self.path.exists() else []
        for n, line in enumerate([x for x in lines if x.strip()], 1):
            try:
                e = json.loads(line)
                body = {k: v for k, v in e.items() if k != 'hash'}
                ok = e.get('prev') == prev and e.get('hash') == digest(body) and e.get('seq') == n
            except (ValueError, TypeError):
                ok = False
            if not ok:
                return {'n': n, 'ok': False, 'problem': f'entry {n}: hash chain broken', 'head': prev}
            prev = e['hash']
        return {'n': len([x for x in lines if x.strip()]), 'ok': True, 'problem': None, 'head': prev}

    def ids(self):
        return {e.get('id') for e in self.entries() if e.get('id')}

    def append(self, entries):
        """Append entries (dicts with 'type'); returns them with seq / prev / hash. Refused on a broken chain."""
        state = self.verify()
        if not state['ok']:
            raise RuntimeError(f'{self.path.name}: {state["problem"]}; nothing appended')
        prev, seq, out = state['head'], state['n'], []
        with open(self.path, 'a', encoding='utf-8') as f:
            for e in entries:
                seq += 1
                body = {**e, 'seq': seq, 'prev': prev}
                full = {**body, 'hash': digest(body)}
                f.write(json.dumps(full, sort_keys=True, allow_nan=False) + '\n')
                prev = full['hash']
                out.append(full)
        return out
