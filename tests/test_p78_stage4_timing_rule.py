"""
Stage 4 proposal v3: timing rule (docs/research/stage4_proposal/timing_rule.py). The timestamps below are
HYPOTHETICAL (not observations); the first test uses a synthetic session calendar, the second the XNYS calendar.
"""

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'docs' / 'research' / 'stage4_proposal'))
from timing_rule import NEW_YORK, Schedule, classify  # noqa: E402


def synthetic():
    """Weekdays from 2024-01-01 for 120 days, 09:30-16:00; 2024-01-15 closed; 2024-01-19 closes at 13:00."""
    out, d = [], date(2024, 1, 1)
    while len(out) < 90:
        if d.weekday() < 5 and d != date(2024, 1, 15):
            close = time(13) if d == date(2024, 1, 19) else time(16)
            out.append((d, datetime.combine(d, time(9, 30), NEW_YORK), datetime.combine(d, close, NEW_YORK)))
        d += timedelta(days=1)
    return Schedule(out)


def at(day, hh, mm=0):
    return datetime.combine(date.fromisoformat(day), time(hh, mm), NEW_YORK)


def test_classes_and_windows_on_a_synthetic_calendar():
    s = synthetic()
    pre = classify(at('2024-01-09', 7), date(2024, 1, 9), s)
    assert pre['class'] == 'V-PRE' and pre['primary']
    assert (pre['start_close'], pre['end_close'], pre['entry_open']) == (date(2024, 1, 8), date(2024, 1, 10),
                                                                         date(2024, 1, 11))
    post = classify(at('2024-01-09', 16, 5), date(2024, 1, 9), s)
    assert post['class'] == 'POST' and not post['primary'] and post['start_close'] == date(2024, 1, 9)
    assert classify(at('2024-01-09', 9, 30), date(2024, 1, 9), s)['class'] == 'INTRADAY'
    assert classify(at('2024-01-09', 16), date(2024, 1, 9), s)['class'] == 'POST'
    holiday = classify(at('2024-01-15', 8), date(2024, 1, 15), s)         # closed Monday
    assert holiday['class'] == 'V-NONSESSION' and holiday['start_close'] == date(2024, 1, 12)
    assert holiday['reaction_sessions'] == [date(2024, 1, 16), date(2024, 1, 17)]
    assert classify(at('2024-01-19', 14), date(2024, 1, 19), s)['class'] == 'POST'     # after a 13:00 close
    weekend_release = classify(at('2024-01-22', 6, 30), date(2024, 1, 21), s)          # Sunday release
    assert weekend_release['class'] == 'V-PRE' and weekend_release['start_close'] == date(2024, 1, 19)
    assert classify(at('2024-01-10', 7), date(2024, 1, 9), s)['class'] == 'SPANNING'   # a trading day between
    assert classify(at('2024-01-13', 10), date(2024, 1, 12), s)['class'] == 'SPANNING'
    assert classify(at('2024-01-09', 7), None, s)['class'] == 'INCONSISTENT'
    assert classify(at('2024-01-09', 7), date(2024, 1, 10), s)['class'] == 'INCONSISTENT'


def test_entry_follows_the_reaction_and_the_holding_period_is_40_sessions():
    s = synthetic()
    r = classify(at('2024-01-09', 7), date(2024, 1, 9), s)
    i = s.index
    assert i[r['entry_open']] == i[r['end_close']] + 1                  # next session after the last EAR close
    assert i[r['exit_close']] - i[r['entry_open']] + 1 == 40


def test_xnys_holidays_special_closures_and_early_closes():
    pytest.importorskip('exchange_calendars')
    s = Schedule.xnys()
    good_friday = classify(at('2024-03-29', 10), date(2024, 3, 29), s)
    assert good_friday['class'] == 'V-NONSESSION' and good_friday['start_close'] == date(2024, 3, 28)
    carter = classify(at('2025-01-09', 7), date(2025, 1, 9), s)          # market closed (national day of mourning)
    assert carter['class'] == 'V-NONSESSION' and carter['reaction_sessions'][0] == date(2025, 1, 10)
    assert classify(at('2024-11-29', 14, 30), date(2024, 11, 29), s)['class'] == 'POST'   # 13:00 early close
    assert classify(at('2024-11-29', 12, 30), date(2024, 11, 29), s)['class'] == 'INTRADAY'
