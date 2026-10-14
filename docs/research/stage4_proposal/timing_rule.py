"""
Stage 4 proposal v3: reference implementation of the timing rule (section 5). It uses no network and reads no price.

classify(t_a, d_r, schedule) -> dict
  t_a       SEC acceptance instant (EDGAR index page "Accepted"), a timezone-aware datetime
  d_r       announcement day: the earliest of the 8-K cover-page "Date of earliest event reported" (feed field
            reportDate) and the exhibit 99 dateline when one is detected; a date, or None when neither exists
  schedule  Schedule: XNYS sessions with their open and close instants (early closes included)

The release lies in I = [00:00 New York of d_r, t_a]: it cannot be on an earlier day than d_r, and the
8-K is public from its acceptance. When no regular-session trading falls inside I, every possible release instant
has the same last close before it (s_b) and the same first open after it (s*): the alignment is VERIFIED from SEC
data alone. Otherwise it depends on an assumption and the event is not in the primary analysis.

Classes: V-PRE and V-NONSESSION (verified, primary); POST (depends on A1: release after the close of d); INTRADAY
(anchor in trading hours); SPANNING (announcement day earlier than t_a's day with trading in between);
INCONSISTENT (no announcement day, or one after t_a's day).
"""

from bisect import bisect_left, bisect_right
from datetime import datetime, time
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo('America/New_York')
PRIMARY = ('V-PRE', 'V-NONSESSION')


class Schedule:
    """Sessions in order: (day, open, close), instants timezone-aware."""

    def __init__(self, sessions):
        self.days = [s[0] for s in sessions]
        self.opens = [s[1] for s in sessions]
        self.closes = [s[2] for s in sessions]
        self.index = {d: i for i, d in enumerate(self.days)}

    @classmethod
    def xnys(cls, start='2015-01-01'):
        """From exchange_calendars XNYS (version pinned in the pre-registration), read from its schedule table."""
        import exchange_calendars as xc
        sched = xc.get_calendar('XNYS', start=start).schedule
        return cls([(d.date(), o.tz_convert(NEW_YORK).to_pydatetime(), c.tz_convert(NEW_YORK).to_pydatetime())
                    for d, o, c in zip(sched.index, sched['open'], sched['close'])])

    def last_close_at_or_before(self, t):
        i = bisect_right(self.closes, t) - 1
        return i if i >= 0 else None

    def first_open_after(self, t):
        i = bisect_right(self.opens, t)
        return i if i < len(self.days) else None

    def trading_inside(self, start, end):
        """True when some session [open, close) intersects [start, end]."""
        i = bisect_left(self.closes, start)          # first session whose close is >= start
        while i < len(self.days) and self.opens[i] <= end:
            if self.closes[i] > start:
                return True
            i += 1
        return False


def classify(t_a, d_r, schedule):
    t_a = t_a.astimezone(NEW_YORK)
    day = t_a.date()
    out = {'t_a': t_a.isoformat(), 'd_r': d_r.isoformat() if d_r else None}
    if d_r is None or d_r > day:
        return {**out, 'class': 'INCONSISTENT', 'primary': False}
    start = datetime.combine(d_r, time(0), NEW_YORK)
    i = schedule.index.get(day)
    if i is not None and schedule.opens[i] <= t_a < schedule.closes[i]:
        return {**out, 'class': 'INTRADAY', 'primary': False}
    b = schedule.last_close_at_or_before(start) if not schedule.trading_inside(start, t_a) else None
    s = schedule.first_open_after(t_a)
    if b is None:
        cls = 'POST' if (d_r == day and i is not None and t_a >= schedule.closes[i]) else 'SPANNING'
        if cls == 'POST':          # windows under A1 (descriptive diagnostic only): start at close(d)
            b = i
        else:
            return {**out, 'class': cls, 'primary': False}
    else:
        cls = 'V-PRE' if (i is not None and t_a < schedule.opens[i]) else 'V-NONSESSION'
    if s is None or s + 41 >= len(schedule.days):
        return {**out, 'class': cls, 'primary': False, 'reason': 'calendar ends before the window'}
    d = schedule.days
    return {**out, 'class': cls, 'primary': cls in PRIMARY,
            'start_close': d[b], 'reaction_sessions': [d[s], d[s + 1]], 'end_close': d[s + 1],
            'entry_open': d[s + 2], 'exit_close': d[s + 41]}
