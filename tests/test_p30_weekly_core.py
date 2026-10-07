"""Phase P3.0 - weekly report core contract (offline)."""

import json

import pandas as pd
import pytest

from src.weekly.core import (STRONG, UNCERTAIN, LookAheadError, SectionResult, TimeModel, conclude,
                             evidence, unavailable, write_archive)

SESSIONS = [d.date().isoformat() for d in pd.bdate_range('2026-09-01', '2026-10-09')]


def test_time_model_cutoffs_and_windows():
    tm = TimeModel(SESSIONS, requested_cutoff='2026-10-07T12:00:00+00:00', generated_at='2026-10-07T12:00:00+00:00')
    assert tm.s0 == '2026-10-06'                        # 10-07 not finished before the cutoff
    assert tm.cutoff == '2026-10-07T05:00:00+00:00'     # EOD(10-06)
    assert tm.week == ['2026-09-30', '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06']
    assert tm.previous_cutoff == '2026-09-30T05:00:00+00:00'   # EOD(09-29)
    assert tm.in_window('2026-10-01T14:00:00+00:00') and not tm.in_window('2026-09-30T05:00:00+00:00')
    assert not tm.news_complete()                        # generated < cutoff + 26 h
    assert TimeModel(SESSIONS, '2026-10-07T12:00:00+00:00', '2026-10-09T00:00:00+00:00').news_complete()


def test_evidence_after_cutoff_is_a_look_ahead_error():
    tm = TimeModel(SESSIONS, '2026-10-07T12:00:00+00:00', '2026-10-07T12:00:00+00:00')
    with pytest.raises(LookAheadError):
        evidence(tm, 'SEC EDGAR', 1, '8-K', published_at='2026-10-07T13:00:00+00:00')
    ok = evidence(tm, 'SEC EDGAR', 1, '8-K', published_at='2026-10-06T13:00:00+00:00', fresh=True)
    assert ok['published_at'] == '2026-10-06T13:00:00+00:00'


def test_levels_are_decided_by_rules_not_by_sections():
    tm = TimeModel(SESSIONS, '2026-10-07T12:00:00+00:00', '2026-10-07T12:00:00+00:00')
    sec = evidence(tm, 'SEC EDGAR', 1, '10-Q', published_at='2026-10-01T12:00:00+00:00', fresh=True)
    yf = evidence(tm, 'yfinance', 2, 'close', published_at='2026-10-06T21:00:00+00:00', fresh=True)
    news = evidence(tm, 'NewsAPI', 3, 'article', published_at='2026-10-05T10:00:00+00:00', fresh=True)
    assert conclude('MP', 2, 'a 10-Q was accepted', [sec], 'official_fact')['level'] == STRONG
    stale = evidence(tm, 'SEC EDGAR', 1, '10-Q', published_at='2026-01-01T00:00:00+00:00', fresh=False)
    assert 'STALE_AT_CUTOFF' in conclude('MP', 2, 'x', [stale], 'official_fact')['reason_codes']
    price = conclude('MP', 1, 'MP fell 5%', [yf], 'market_fact')
    assert price['level'] == UNCERTAIN and price['reason_codes'] == ['SINGLE_RANK2_SOURCE']
    assert conclude('MP', 1, 'MP fell 5%', [yf, yf], 'market_fact', cross_checked=True)['level'] == STRONG
    assert conclude('MP', 2, 'rank-2 as official', [yf], 'official_fact')['level'] == UNCERTAIN
    assert conclude('overall', 4, 'story', [news], 'aggregator')['level'] == UNCERTAIN
    model = conclude('MP', 10, 'signal NEUTRAL', [], 'system_output')
    assert model['level'] == STRONG                     # a statement about the system's output
    assert conclude('MP', 10, 'signal means up', [yf], 'model_output')['reason_codes'] == ['MODEL_NOT_VALIDATED']
    partial = conclude('MP', 2, 'x', [sec], 'official_fact', reason_codes=['PARTIAL_COVERAGE'])
    assert partial['level'] == UNCERTAIN and partial['what_would_resolve_it']
    with pytest.raises(ValueError):
        conclude('MP', 2, 'x', [], 'official_fact')      # no evidence -> must be unavailable()
    with pytest.raises(ValueError):
        conclude('MP', 2, 'x', [sec], 'official_fact', reason_codes=['MADE_UP'])


def test_unavailable_requires_reason_and_section_routing():
    r = SectionResult('x', [3])
    r.add(unavailable('overall', 3, 'GPR index', 'host blocked by proxy'))
    with pytest.raises(ValueError):
        unavailable('overall', 3, 'GPR index', '')
    assert r.as_dict()['unavailable'][0]['level'] == 'DATA UNAVAILABLE' and not r.as_dict()['conclusions']


def test_archive_is_never_overwritten(tmp_path):
    tm = TimeModel(SESSIONS, '2026-10-07T12:00:00+00:00', '2026-10-07T12:00:00+00:00')
    payload = {'sections': [], 'code_version': 'abc'}
    first = write_archive(tm, payload, '<html></html>')
    second = write_archive(tm, payload, '<html></html>')
    assert first[1].name == 'weekly_v1.json' and second[1].name == 'weekly_v2.json'
    manifest = json.loads((first[1].parent / 'manifest_v1.json').read_text())
    assert manifest['cutoff'] == tm.cutoff and manifest['sha256_json']
