"""
Stage 3 - prospective weekly record (src/prospective.py) and its place in the weekly report (Q11).

Synthetic prices only check the protocol: record timing, immutability and the hash chain, validity rules,
realised returns from the next session, the once-only pre-registered test, and point-in-time reading.
"""

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
import yfinance

from tests.conftest import make_price_frame

TICKERS = [f'T{i:02d}' for i in range(12)]
END = '2026-10-01T12:00:00+00:00'            # after the last synthetic session (2026-09-30)


@pytest.fixture
def market(monkeypatch):
    frames = {'SPY': make_price_frame(400, seed=99, ticker='SPY')}
    for n, t in enumerate(TICKERS):
        frames[t] = make_price_frame(400, seed=n, ticker=t)
    monkeypatch.setattr(yfinance, 'download', lambda t, *a, **k: frames.get(t, pd.DataFrame()))
    return frames


def sessions(frame):
    return [d.date().isoformat() for d in frame.index]


def fridays(frame):
    return [d.date().isoformat() for d in frame.index if d.weekday() == 4]


def at(day, offset_days, clock):
    return f'{(date.fromisoformat(day) + timedelta(days=offset_days)).isoformat()}T{clock}+00:00'


def fake_signal(score):
    def ticker_signal(self, ticker, s0):
        v = score(ticker, s0)
        return {'status': 'OK', 'technical': v, 'fundamentals': v, 'insider': None, 'combined': v,
                'signal': 'NEUTRAL', 'features': {}}
    return ticker_signal


def forward(frames, ticker, s0, h):
    close = frames[ticker].iloc[:, 0].to_numpy()
    i = sessions(frames[ticker]).index(s0)
    return close[i + 1 + h] / close[i + 1] - 1


def craft(p, s0, generated_at, scores):
    """A record written outside Recorder.run (to test the validity rules), with its ledger entry."""
    base = p.prospective_dir()
    record = {'protocol': p.PROTOCOL, 's0': s0, 'generated_at': generated_at, 'n_scored': len(scores),
              'tickers': {t: {'status': 'OK', 'combined': v, 'technical': v, 'fundamentals': None, 'insider': None,
                              'signal': 'NEUTRAL'} for t, v in scores.items()}}
    path = base / 'records' / f'record_{s0}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding='utf-8')
    p._append_ledger(base, record, f'records/record_{s0}.json')
    return path


# ---------------------------------------------------------------- calendar rules

def test_signal_session_and_week_bounds():
    from src.prospective import entry_open_bound, signal_session, week_bounds
    days = ['2026-10-07', '2026-10-08', '2026-10-09']
    assert signal_session(days, '2026-10-10T04:59:59+00:00') == '2026-10-08'
    assert signal_session(days, '2026-10-10T05:00:00+00:00') == '2026-10-09'
    assert week_bounds('2026-10-09') == ('2026-10-10T05:00:00+00:00', '2026-10-12T13:30:00+00:00')
    assert week_bounds('2026-10-08') == week_bounds('2026-10-09')            # Thursday (Friday holiday)
    assert entry_open_bound('2026-10-13') == '2026-10-13T13:30:00+00:00'


def test_universe_is_frozen_copy_of_the_validation_universe():
    from src.common import validation_universe
    from src.prospective import UNIVERSE
    assert len(UNIVERSE) == 40 and tuple(validation_universe()) == UNIVERSE


# ---------------------------------------------------------------- record

def test_record_is_made_once_per_week_and_chained(market, monkeypatch):
    from src import prospective as p
    monkeypatch.setattr(p.Recorder, 'ticker_signal', fake_signal(lambda t, s0: 50.0 + int(t[1:])))
    s0 = fridays(market['SPY'])[-3]
    rec = p.Recorder()
    out = rec.run(now=at(s0, 1, '20:00:00'), universe=TICKERS)
    assert out['status'] == 'CREATED' and out['s0'] == s0 and out['record']['n_scored'] == 12
    record = json.loads(out['path'].read_text())
    assert record['signal_instant'] == f'{s0}T21:00:00+00:00' and record['protocol'] == p.PROTOCOL
    assert record['signal']['components'] == ['technical', 'fundamentals', 'insider']
    assert record['calendar']['last_sessions'][-1] == s0
    ledger = p.verify_ledger()
    assert ledger['chain_ok'] and list(ledger['verified']) == [s0]
    assert ledger['verified'][s0]['record_sha256'] == p.sha256(record)
    again = rec.run(now=at(s0, 2, '20:00:00'), universe=TICKERS)                      # Sunday catch-up run
    assert again['status'] == 'EXISTS' and p.verify_ledger()['n_entries'] == 1
    # Friday 22:00 UTC: s0 is still Thursday (EOD rule) and its week is not over
    assert rec.run(now=at(s0, 0, '22:00:00'), universe=TICKERS)['status'] == 'NOT DUE'
    # an earlier week, attempted on its Monday after the earliest open: too late, nothing written
    earlier = fridays(market['SPY'])[-5]
    late = rec.run(now=at(earlier, 3, '14:00:00'), universe=TICKERS)
    assert late['status'] == 'NOT DUE' and 'too late' in late['message']
    assert not (p.prospective_dir() / 'records' / f'record_{earlier}.json').exists()


def test_ticker_signal_uses_walk_forward_scores_up_to_s0_only(market):
    from src import prospective as p
    from src.price_technical import PriceTechnical
    s0 = fridays(market['SPY'])[-10]
    out = p.Recorder().ticker_signal('T01', s0)
    close = market['T01'].iloc[:, 0].to_numpy()
    i = sessions(market['T01']).index(s0)
    assert out['status'] == 'OK'
    assert out['technical'] == PriceTechnical().score_closes(close[:i + 1])['technical_score']
    assert out['fundamentals'] is None and out['insider'] is None                    # no SEC offline
    assert out['combined'] is None and out['signal'] == 'INSUFFICIENT DATA'          # 1 component < 2
    frame = market['T01']
    frame.iloc[i + 1:, 0] = frame.iloc[i + 1:, 0] * 3                                 # rewrite the "future"
    assert p.Recorder().ticker_signal('T01', s0)['technical'] == out['technical']
    missing = p.Recorder().ticker_signal('T01', '2020-01-03')
    assert missing['status'] == 'DATA UNAVAILABLE' and 'no close on 2020-01-03' in missing['reason']


def test_ticker_failure_is_recorded_not_raised(market, monkeypatch):
    from src import prospective as p

    def signal(self, ticker, s0):
        if ticker == 'T00':
            raise RuntimeError('boom')
        return fake_signal(lambda t, d: 60.0)(self, ticker, s0)
    monkeypatch.setattr(p.Recorder, 'ticker_signal', signal)
    s0 = fridays(market['SPY'])[-3]
    out = p.Recorder().run(now=at(s0, 1, '20:00:00'), universe=TICKERS)
    assert out['record']['tickers']['T00'] == {'status': 'DATA UNAVAILABLE', 'reason': 'RuntimeError: boom'}
    assert out['record']['n_scored'] == 11


# ---------------------------------------------------------------- ledger

def test_ledger_detects_changed_records_and_broken_chain(market, monkeypatch):
    from src import prospective as p
    monkeypatch.setattr(p.Recorder, 'ticker_signal', fake_signal(lambda t, s0: 50.0 + int(t[1:])))
    first, second = fridays(market['SPY'])[-4:-2]
    rec = p.Recorder()
    for s0 in (first, second):
        assert rec.run(now=at(s0, 1, '20:00:00'), universe=TICKERS)['status'] == 'CREATED'
    path = p.prospective_dir() / 'records' / f'record_{second}.json'
    record = json.loads(path.read_text())
    record['tickers']['T00']['combined'] = 99.0                                       # edited after the fact
    path.write_text(json.dumps(record))
    ledger = p.verify_ledger()
    assert list(ledger['verified']) == [first]
    assert ledger['problems'] == [f'record {second}: content differs from its ledger entry']
    ev = p.evaluate(now=END, write=False)
    bad = next(r for r in ev['records'] if r['s0'] == second)
    assert bad['status'] == 'invalid' and bad['problems'][0].startswith('integrity')
    assert all(r['date'] == first for r in ev['samples'])
    lines = (p.prospective_dir() / 'ledger.jsonl').read_text().splitlines()
    entry = json.loads(lines[0])
    entry['generated_at'] = '2000-01-01T00:00:00+00:00'                               # rewritten history
    (p.prospective_dir() / 'ledger.jsonl').write_text('\n'.join([json.dumps(entry)] + lines[1:]) + '\n')
    broken = p.verify_ledger()
    assert not broken['chain_ok'] and broken['verified'] == {}
    third = fridays(market['SPY'])[-2]
    refused = rec.run(now=at(third, 1, '20:00:00'), universe=TICKERS)
    assert refused['status'] == 'LEDGER BROKEN'
    assert not (p.prospective_dir() / 'records' / f'record_{third}.json').exists()


# ---------------------------------------------------------------- evaluate

def test_evaluate_applies_validity_rules_and_measures_from_next_close(market, monkeypatch):
    from src import prospective as p
    from src.walk_forward import spearman
    monkeypatch.setattr(p.Recorder, 'ticker_signal', fake_signal(lambda t, s0: 50.0 + int(t[1:])))
    spy_fridays = fridays(market['SPY'])
    a, b, c = spy_fridays[-12], spy_fridays[-11], spy_fridays[-10]
    rec = p.Recorder()
    for s0 in (a, b):
        rec.run(now=at(s0, 1, '20:00:00'), universe=TICKERS)
    scores = {t: 50.0 + int(t[1:]) for t in TICKERS}
    thursday = (date.fromisoformat(c) - timedelta(days=1)).isoformat()
    craft(p, thursday, at(thursday, 2, '12:00:00'), scores)                       # Friday followed it
    late = spy_fridays[-9]
    craft(p, late, at(late, 3, '13:30:00'), scores)                               # at the entry open: too late
    pending = spy_fridays[-1]
    craft(p, pending, at(pending, 1, '12:00:00'), scores)
    ev = p.evaluate(now=END)
    status = {r['s0']: r for r in ev['records']}
    assert status[a]['status'] == status[b]['status'] == 'valid'
    assert 'weekly spacing' in status[thursday]['problems'][0]
    assert status[late]['problems'][0].startswith('timing')
    assert status[pending]['status'] == 'pending' or status[pending]['horizons']['20d']['status'] == 'pending'
    assert ev['record_counts']['valid'] >= 2 and ev['record_counts']['invalid'] == 2
    s1 = sessions(market['SPY'])[sessions(market['SPY']).index(a) + 1]
    assert status[a]['entry_date'] == s1
    row = next(r for r in ev['samples'] if r['date'] == a and r['ticker'] == 'T03')
    assert abs(row['fwd_5d'] - forward(market, 'T03', a, 5)) < 1e-12
    assert abs(row['fwd_20d'] - forward(market, 'T03', a, 20)) < 1e-12
    ic = spearman(list(scores.values()), [forward(market, t, a, 20) for t in scores])
    assert status[a]['horizons']['20d'] == {'status': 'evaluated', 'exit_date': status[a]['horizons']['20d']['exit_date'],
                                             'n_pairs': 12, 'ic': round(ic, 4)}
    assert {r['date'] for r in ev['samples']} <= {a, b, pending}                 # invalid records never used
    h20 = ev['horizons']['20d']
    assert h20['hypothesis'] == 'P1' and h20['n_evaluated'] == 2 and h20['confirmatory'] is None
    assert set(h20['interim']) == {'n_weeks', 'mean_ic', 'positive_weeks_pct'}     # no t, no p before 52
    assert ev['status'] == 'IN PROGRESS'
    assert (p.prospective_dir() / 'evaluation.json').exists()


def test_too_few_tickers_do_not_count(market, monkeypatch):
    from src import prospective as p
    monkeypatch.setattr(p.Recorder, 'ticker_signal',
                        fake_signal(lambda t, s0: 50.0 + int(t[1:]) if int(t[1:]) < 9 else None))
    s0 = fridays(market['SPY'])[-12]
    p.Recorder().run(now=at(s0, 1, '20:00:00'), universe=TICKERS)
    ev = p.evaluate(now=END, write=False)
    assert ev['records'][0]['horizons']['20d']['status'] == 'too few tickers (< 10)'
    assert ev['horizons']['20d']['n_evaluated'] == 0


def test_preregistered_test_runs_once_on_the_first_records(market, monkeypatch):
    from src import prospective as p
    monkeypatch.setattr(p, 'MIN_RECORDS', 4)

    def score(t, s0):
        noise = np.random.default_rng(int(s0.replace('-', '')) + int(t[1:])).normal(0, 0.02)
        return round(50 + 100 * (forward(market, t, s0, 20) + noise), 4)
    monkeypatch.setattr(p.Recorder, 'ticker_signal', fake_signal(score))
    weeks = fridays(market['SPY'])[-12:-6]
    rec = p.Recorder()
    for s0 in weeks:
        assert rec.run(now=at(s0, 1, '20:00:00'), universe=TICKERS)['status'] == 'CREATED'
    ev = p.evaluate(now=END)
    conf = ev['horizons']['20d']['confirmatory']
    assert conf['records'] == weeks[:4] and conf['n_weeks'] == 4
    assert conf['mean_ic'] > 0.5 and conf['p_value'] < conf['required_p'] == 0.025 and conf['confirmed'] is True
    assert ev['status'] == 'CONCLUDED'
    frozen = json.loads((p.prospective_dir() / 'confirmatory_20d.json').read_text())
    assert frozen == conf
    # a later evaluation (more records, other prices) reads the frozen result: the test is never re-run
    market['T00'].iloc[:, 0] = market['T00'].iloc[:, 0][::-1].to_numpy()
    later = p.evaluate(now='2026-10-02T12:00:00+00:00')
    assert later['horizons']['20d']['confirmatory'] == frozen


def test_confirmatory_test_reports_adverse_and_not_confirmed():
    from src import prospective as p
    rows = []
    for w, day in enumerate(['2026-01-02', '2026-01-09', '2026-01-16', '2026-01-23']):
        for t in range(10):
            rows.append({'date': day, 'ticker': t, 'combined': t, 'fwd_5d': -t + (w % 2) * 1.5 * (t % 3)})
    out = p.confirmatory_test(rows, ['2026-01-02', '2026-01-09', '2026-01-16', '2026-01-23'], 5, 'P2', END)
    assert out['mean_ic'] < 0 and out['confirmed'] is False and out['adverse'] is True


def test_latest_evaluation_is_point_in_time(market, monkeypatch):
    from src import prospective as p
    monkeypatch.setattr(p.Recorder, 'ticker_signal', fake_signal(lambda t, s0: 50.0 + int(t[1:])))
    s0 = fridays(market['SPY'])[-12]
    p.Recorder().run(now=at(s0, 1, '20:00:00'), universe=TICKERS)
    p.evaluate(now=END)
    p.evaluate(now='2026-10-03T12:00:00+00:00')
    assert p.latest_evaluation('2026-10-02T00:00:00+00:00')['computed_at'] == END
    assert p.latest_evaluation('2026-10-04T00:00:00+00:00')['computed_at'] == '2026-10-03T12:00:00+00:00'
    assert p.latest_evaluation('2026-09-30T00:00:00+00:00') is None


def test_no_records_and_no_calendar(market, monkeypatch):
    from src import prospective as p
    assert p.evaluate(now=END)['status'] == 'NO RECORDS'
    monkeypatch.setattr(yfinance, 'download', lambda *a, **k: pd.DataFrame())
    out = p.Recorder().run(now=END, universe=TICKERS)
    assert out['status'] == 'DATA UNAVAILABLE' and 'SPY' in out['message']


# ---------------------------------------------------------------- weekly report Q11

def _quant(tmp_path, base):
    from src.weekly.sections import quant
    from tests.test_weekly_catalysts_quant import quant_ctx, wf_payload, write_json
    wf = write_json(tmp_path, 'wf.json', wf_payload('2026-10-06T09:00:00+00:00'))
    research = {1: tmp_path / 'none1.json', 2: tmp_path / 'none2.json'}
    return quant.build(quant_ctx(), analysis_path=tmp_path / 'none.json', walk_forward_path=wf,
                       research_paths=research, prospective_path=base).as_dict()


def _evaluation(computed_at, confirmatory=None):
    def horizon(hyp, n):
        return {'hypothesis': hyp, 'n_evaluated': n, 'required': 52,
                'interim': {'n_weeks': n, 'mean_ic': 0.0312 if n else None, 'positive_weeks_pct': 100.0 if n else None},
                'confirmatory': confirmatory}
    return {'protocol': 'stage3-v1', 'computed_at': computed_at, 'status': 'IN PROGRESS',
            'record_counts': {'valid': 1, 'invalid': 0, 'pending': 0},
            'records': [{'s0': '2026-09-04', 'problems': []}],
            'horizons': {'20d': horizon('P1', 0), '5d': horizon('P2', 1)}}


def _write_eval(base, payload):
    from src.common import stamp
    (base / 'history').mkdir(parents=True, exist_ok=True)
    (base / 'history' / f"evaluation_{stamp(payload['computed_at'])}.json").write_text(json.dumps(payload))


def test_q11_without_records_is_unavailable(tmp_path):
    out = _quant(tmp_path, tmp_path / 'prospective')
    item = next(u for u in out['unavailable'] if u['item'].startswith('prospective record'))
    assert 'no stage 3 record generated at or before the cutoff' in item['reason']
    assert '52 valid weekly records' in item['reason']
    assert not (tmp_path / 'prospective').exists()                         # the section never writes


def test_q11_reads_records_and_evaluation_at_the_cutoff(tmp_path, monkeypatch):
    from src import prospective as p
    base = tmp_path / 'prospective'
    monkeypatch.setenv('TRADING_AGENT_REPORTS_DIR', str(tmp_path))
    scores = {t: 50.0 + int(t[1:]) for t in TICKERS}
    craft(p, '2026-09-04', '2026-09-05T20:00:00+00:00', scores)
    craft(p, '2026-10-09', '2026-10-10T20:00:00+00:00', scores)            # after T_c (2026-10-07T05:00Z)
    _write_eval(base, _evaluation('2026-10-04T12:00:00+00:00'))
    late = _evaluation('2026-10-08T12:00:00+00:00')
    late['horizons']['5d']['interim']['mean_ic'] = 0.9                       # computed after the cutoff
    _write_eval(base, late)
    out = _quant(tmp_path, base)
    c = next(x for x in out['conclusions'] if x['statement'].startswith('Stage 3 prospective record'))
    assert '1 stage 3 weekly record(s) generated at or before the cutoff (s0 2026-09-04 to 2026-09-04)' in c['statement']
    assert 'evaluation computed 2026-10-04T12:00:00+00:00' in c['statement']
    assert 'P1 (20d): 0 of 52 valid weekly records evaluated (no test' in c['statement']
    assert 'P2 (5d): 1 of 52 valid weekly records evaluated, interim mean IC +0.0312' in c['statement']
    assert '0.9' not in c['statement'] and c['level'] == 'STRONGLY SUPPORTED'
    t = next(x for x in out['tables'] if x['title'] == 'Prospective record (stage 3, pre-registered)')
    assert [r[0] for r in t['rows']] == ['P1', 'P2'] and t['rows'][0][6] == 'not yet (sample incomplete)'
    pending = next(u for u in out['unavailable'] if u['item'] == 'pre-registered prospective test (stage 3)')
    assert '20d 0/52, 5d 1/52' in pending['reason']
    assert not any(u['item'].startswith('prospective record') for u in out['unavailable'])


def test_q11_states_the_preregistered_result_and_integrity_problems(tmp_path, monkeypatch):
    from src import prospective as p
    base = tmp_path / 'prospective'
    monkeypatch.setenv('TRADING_AGENT_REPORTS_DIR', str(tmp_path))
    scores = {t: 50.0 + int(t[1:]) for t in TICKERS}
    craft(p, '2026-09-04', '2026-09-05T20:00:00+00:00', scores)
    path = craft(p, '2026-09-11', '2026-09-12T20:00:00+00:00', scores)
    path.write_text(path.read_text().replace('50.0', '51.0'))                 # changed after the fact
    conf = {'records': ['2025-09-05', '2026-08-28'], 'mean_ic': 0.021, 't_stat': 1.1, 'p_value': 0.2713,
            'required_p': 0.025, 'confirmed': False, 'adverse': False}
    _write_eval(base, _evaluation('2026-10-04T12:00:00+00:00', confirmatory=conf))
    out = _quant(tmp_path, base)
    c = next(x for x in out['conclusions'] if x['statement'].startswith('Stage 3 prospective record'))
    assert 'P1 (20d): pre-registered test on the first 2 valid records (2025-09-05 to 2026-08-28): mean IC ' \
           '+0.0210, t 1.1, p 0.2713 (required < 0.025): NOT CONFIRMED' in c['statement']
    assert '1 stage 3 weekly record(s)' in c['statement']                      # the changed one is not counted
    integrity = next(u for u in out['unavailable'] if u['item'] == 'stage 3 record integrity')
    assert 'record 2026-09-11: content differs from its ledger entry' in integrity['reason']
    assert not any(u['item'] == 'pre-registered prospective test (stage 3)' for u in out['unavailable'])
