#!/usr/bin/env python3
"""
Weekly report section 'macro' - Q3 macro, Q4 geopolitical indices, Q5 socio-economic (phase P3.0)

Data: FRED only (rank 1 distributor), every vintage stored by ctx.fred(series). Nothing here reads
the wall clock: all instants come from ctx.tm (T_c = cutoff, T_p = previous cutoff).

Vintage rules
  as known at T    ctx.value_at(series, T) (latest observation) and ctx.series_at(series, T) (one
                   value per observation date): the version whose publication instant (FRED vintage
                   date, end of day New York) is <= T. Transforms are computed WITHIN ONE vintage:
                   YoY(m) = v(m) / v(m-12) - 1 with both months from series_at(series, T).
  new release      an observation first published inside the window (T_p, T_c] (ctx.first_release).
  revision         an observation known at T_p whose value differs in the T_c vintage.
  revision noise   largest |value as known at T_c - value at its first print| over the periods first
                   printed inside the stored vintages (periods whose first stored version is the start
                   of the stored vintage window are excluded: that version is not a first print). For a
                   change vs the prior period, the same is computed on the change. A difference is
                   "beyond revision noise" only when |difference| > that largest revision; otherwise the
                   statement carries FIRST_PRINT_WITHIN_REVISION_NOISE (also when the noise cannot be
                   measured). For weekly means of daily series the noise is the largest revision of a
                   single daily value (an upper bound for the revision of a mean).
  freshness        ctx.freshness(obs date, cadence) at T_c, once per series on its latest observation known at
                   T_c (the rule: the series must be FRESH at T_c). The 'as known at T_p' item is a historical
                   vintage fact and carries that same flag (its own age at T_c is not a staleness).
  coverage         a negative or "latest" statement needs a fetch retrieved after T_c; otherwise
                   PARTIAL_COVERAGE.
  thresholds       ctx.weekly['thresholds'] has no macro materiality threshold in v1: differences are
                   reported as facts. If an optional mapping 'macro_abs_change' {series: abs threshold}
                   is added, |difference| below it adds BELOW_THRESHOLD.

Q3  DGS10, DGS2, T10Y2Y, DFF, DFEDTARU / DFEDTARL (target range: a change published in the window is
    an official_fact), VIXCLS, DTWEXBGS, BAMLH0A0HYM2, BAA10Y, NFCI, CPIAUCSL / CPILFESL / PCEPI (YoY).
    Daily series: also the mean of observations dated in the week (s_-5, s_0] known at T_c vs the
    previous week (s_-10, s_-5] known at T_p.
Q4  USEPUINDXD (daily, heavily revised: weekly means only) and GEPUCURRENT (monthly, long lag). Both
    measure policy uncertainty from newspaper coverage, NOT geopolitical events. GPR, GDELT, official
    primary documents: DATA UNAVAILABLE (hosts blocked by the proxy).
Q5  UNRATE, PAYEMS, ICSA / CCSA (4-week averages from one vintage), UMCSENT (FRED delays it ~1 month),
    RSAFS, JTSJOL, MORTGAGE30US, HOUST, CES0500000003 (+ derived real earnings with the CPI of the
    same month known at T_c: an ESTIMATE). Directional readings of a block ("labour indicators
    softer") are ALWAYS interpretations and need >= 2 indicators with a new release beyond revision
    noise, all pointing the same way under the pre-declared sign convention.

Levels: FRED values are official_fact (STRONGLY SUPPORTED only when fresh, covered and not within
revision noise); derived values add ESTIMATE; UMCSENT adds TIMESTAMP_AMBIGUOUS (FRED's vintage date
is not the source's publication date); judgements are interpretation. Timing words only.
"""

import math
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta

from ...common import to_utc_iso
from ...macro_fred import VINTAGE_BASIS
from ..core import UNAVAILABLE, SectionResult, conclude, evidence, unavailable

NAME = 'macro'
QUESTIONS = [3, 4, 5]
SOURCE, RANK = 'FRED', 1
NOT_EVALUATED = 'NOT EVALUATED'
EPS = 1e-9
DIRECTION_CONVENTION = 'macro-direction-v1'
MAX_REVISIONS_CITED = 3


def _spec(q, label, unit, short, cadence, diff_unit, transform='level', change='diff', digits=2,
          block=None, sign=0, note=None):
    return {'q': q, 'label': label, 'unit': unit, 'short': short, 'cadence': cadence,
            'diff_unit': diff_unit, 'transform': transform, 'change': change, 'digits': digits,
            'block': block, 'sign': sign, 'note': note}


UMCSENT_NOTE = ('FRED serves this series with a delay of about one month at the request of the source: the '
                'latest FRED value is not the current University of Michigan print, and the FRED vintage date '
                'is not the date the source first published it')

# Pre-declared series (order = table order). sign: +1 when an increase is the "firmer / stronger /
# higher" direction of its block under DIRECTION_CONVENTION, -1 when it is the opposite.
SERIES = {
    'DGS10': _spec(3, '10-year Treasury constant-maturity yield', '%', '%', 'daily', 'pp'),
    'DGS2': _spec(3, '2-year Treasury constant-maturity yield', '%', '%', 'daily', 'pp'),
    'T10Y2Y': _spec(3, '10-year minus 2-year Treasury yield spread', 'percentage points', ' pp', 'daily', 'pp'),
    'DFF': _spec(3, 'Effective federal funds rate (daily)', '%', '%', 'daily', 'pp'),
    'DFEDTARU': _spec(3, 'Federal funds target range, upper limit', '%', '%', 'daily', 'pp'),
    'DFEDTARL': _spec(3, 'Federal funds target range, lower limit', '%', '%', 'daily', 'pp'),
    'VIXCLS': _spec(3, 'CBOE Volatility Index (VIX), close', 'index', '', 'daily', 'points'),
    'DTWEXBGS': _spec(3, 'Nominal broad U.S. dollar index (goods and services)', 'index Jan 2006 = 100', '',
                      'daily', 'points', digits=4),
    'BAMLH0A0HYM2': _spec(3, 'ICE BofA US High Yield index option-adjusted spread', '%', '%', 'daily', 'pp'),
    'BAA10Y': _spec(3, "Moody's seasoned Baa corporate yield minus 10-year Treasury yield", 'percentage points',
                    ' pp', 'daily', 'pp'),
    'NFCI': _spec(3, 'Chicago Fed National Financial Conditions Index', 'index (0 = average conditions)', '',
                  'weekly', 'points', digits=3),
    'CPIAUCSL': _spec(3, 'CPI all items, urban consumers (SA), year-over-year', '% YoY', '% YoY', 'monthly', 'pp',
                      transform='yoy', block='inflation', sign=1),
    'CPILFESL': _spec(3, 'CPI less food and energy (SA), year-over-year', '% YoY', '% YoY', 'monthly', 'pp',
                      transform='yoy', block='inflation', sign=1),
    'PCEPI': _spec(3, 'PCE price index (SA), year-over-year', '% YoY', '% YoY', 'monthly', 'pp',
                   transform='yoy', block='inflation', sign=1),
    'USEPUINDXD': _spec(4, 'US daily Economic Policy Uncertainty index, newspaper-based, Baker-Bloom-Davis',
                        'index', '', 'daily', 'points'),
    'GEPUCURRENT': _spec(4, 'Global Economic Policy Uncertainty index, current-price GDP weights, newspaper-based',
                         'index', '', 'monthly', 'points'),
    'UNRATE': _spec(5, 'Unemployment rate', '%', '%', 'monthly', 'pp', digits=1, block='labour', sign=-1),
    'PAYEMS': _spec(5, 'All employees, total nonfarm (payrolls)', 'thousands of persons', ' thousand', 'monthly',
                    'thousand', digits=0, block='labour', sign=1),
    'ICSA': _spec(5, 'Initial unemployment insurance claims (SA)', 'persons', '', 'weekly', 'persons', digits=0,
                  block='labour', sign=-1),
    'CCSA': _spec(5, 'Continued unemployment insurance claims (SA)', 'persons', '', 'weekly', 'persons', digits=0,
                  block='labour', sign=-1),
    'UMCSENT': _spec(5, 'University of Michigan consumer sentiment', 'index 1966 Q1 = 100', '', 'monthly',
                     'points', digits=1, block='consumer', sign=1, note=UMCSENT_NOTE),
    'RSAFS': _spec(5, 'Advance retail and food services sales', 'USD millions', ' USD m', 'monthly', '%',
                   change='pct', digits=0, block='consumer', sign=1),
    'JTSJOL': _spec(5, 'JOLTS job openings, total nonfarm', 'thousands', ' thousand', 'monthly', 'thousand',
                    digits=0, block='labour', sign=1),
    'MORTGAGE30US': _spec(5, '30-year fixed-rate mortgage average (Freddie Mac PMMS)', '%', '%', 'weekly', 'pp'),
    'HOUST': _spec(5, 'Housing starts, total (SAAR)', 'thousands of units', ' thousand', 'monthly', '%',
                   change='pct', digits=0, block='consumer', sign=1),
    'CES0500000003': _spec(5, 'Average hourly earnings of all employees, total private', 'USD per hour', ' USD/h',
                           'monthly', '%', change='pct', digits=2),
}

BLOCKS = {
    'inflation': {'q': 3, 'name': 'Inflation block', 'up': 'higher', 'down': 'lower'},
    'labour': {'q': 5, 'name': 'Labour block', 'up': 'firmer', 'down': 'softer'},
    'consumer': {'q': 5, 'name': 'Consumer and housing block', 'up': 'stronger', 'down': 'weaker'},
}

TARGET = ('DFEDTARU', 'DFEDTARL')

STATIC_UNAVAILABLE = [
    (3, 'FOMC meeting calendar (full)',
     'www.federalreserve.gov is blocked by the proxy (CONNECT 403; HTTP "Host not in allowlist"), tested '
     '2026-10-07; FRED release 101 lists every calendar day and cannot identify meetings. A partial calendar '
     '(Summary of Economic Projections meetings, FRED release 326) is handled by the catalysts section. A '
     'meeting with an unchanged target range cannot be detected from DFEDTARU / DFEDTARL.'),
    (3, 'consensus forecasts and surprises for macro and socio-economic releases',
     'no source of consensus forecasts is available to this system (no licensed survey data; FRED does not '
     'publish consensus)'),
    (3, 'official release times of day',
     'FRED gives vintage dates only; bls.gov, bea.gov and federalreserve.gov are blocked by the proxy, so the '
     'report uses the conservative end-of-day New York convention for every release'),
    (4, 'Caldara-Iacoviello Geopolitical Risk (GPR) index',
     'www.matteoiacoviello.com is blocked by the proxy (HTTPS CONNECT 403; HTTP "Host not in allowlist"), tested '
     '2026-10-07; FRED has no GPR series'),
    (4, 'GDELT event and news database',
     'api.gdeltproject.org and data.gdeltproject.org are blocked by the proxy (CONNECT 403), tested 2026-10-07; '
     'the BigQuery copy is not usable (no credentials)'),
    (4, 'official primary documents on geopolitical and trade actions (Federal Register, OFAC, BIS export '
        'controls, USTR)',
     'these hosts are blocked by the proxy (CONNECT 403), tested 2026-10-07: no rank-1 document for any '
     'geopolitical event is available, so no geopolitical event can be strongly supported'),
    (5, 'current University of Michigan consumer sentiment print (preliminary / final)',
     'FRED delays UMCSENT by about one month at the request of the source; no other source of the survey is '
     'configured'),
    (5, 'official sampling-error bands for labour and consumer statistics',
     'BLS and BEA technical notes are not reachable (bls.gov and bea.gov blocked by the proxy)'),
]


# ---------------------------------------------------------------- small helpers

def _num(v):
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    if abs(v) >= 1 and abs(v - round(v)) < EPS:
        return int(round(v))
    return round(v, 4)


def _fmt(v, digits=2):
    if v is None:
        return 'N/A'
    if abs(v) >= 1 and abs(v - round(v)) < EPS and digits <= 2:
        return f'{int(round(v)):,}'
    text = f'{v:,.{max(digits, 0)}f}'
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return '0' if text in ('-0', '') else text


def _sfmt(v, digits=2):
    if v is None:
        return 'N/A'
    text = _fmt(v, digits)
    return text if text.startswith('-') or text == '0' else '+' + text


def _ddigits(spec):
    """Display digits for differences / changes."""
    if spec['change'] == 'pct' or spec['transform'] == 'yoy':
        return 2
    return max(spec['digits'], 2) if spec['digits'] else 0


def _val(spec, v):
    return f"{_fmt(v, spec['digits'] if spec['transform'] != 'yoy' else 2)}{spec['short']}"


def _diff(spec, v, unit=None):
    unit = unit or spec['diff_unit']
    return f"{_sfmt(v, _ddigits(spec))}{'' if unit == '%' else ' '}{unit}"


def _period(spec, obs):
    if obs is None:
        return 'N/A'
    return obs[:7] if spec['cadence'] == 'monthly' else obs


def _when(instant):
    """Publication display: the FRED vintage date when the instant is its end-of-day convention."""
    if not instant:
        return 'N/A'
    if instant.endswith('T05:00:00+00:00'):
        vintage = date.fromisoformat(instant[:10]) - timedelta(days=1)
        return f'{vintage.isoformat()} (FRED vintage)'
    return instant[:16] + 'Z'


def _add_months(obs, k):
    d = date.fromisoformat(obs)
    m = d.month - 1 + k
    return date(d.year + m // 12, m % 12 + 1, 1).isoformat()


def _prior(spec, obs):
    if spec['cadence'] == 'monthly':
        return _add_months(obs, -1)
    if spec['cadence'] == 'weekly':
        return (date.fromisoformat(obs) - timedelta(days=7)).isoformat()
    return None


def _qty(spec, get, obs):
    """Displayed quantity of `obs` in one vintage (get: obs -> value): level, or YoY % within the vintage."""
    if obs is None:
        return None
    v = get(obs)
    if v is None:
        return None
    if spec['transform'] == 'yoy':
        base = get(_add_months(obs, -12))
        return None if not base else (v / base - 1) * 100
    return v


def _chg(spec, get, obs):
    """(change of the quantity vs the prior period, prior obs) in one vintage."""
    prior = _prior(spec, obs) if obs else None
    if prior is None:
        return None, prior
    a, b = _qty(spec, get, prior), _qty(spec, get, obs)
    if a is None or b is None:
        return None, prior
    if spec['change'] == 'pct':
        return (None if a == 0 else (b / a - 1) * 100), prior
    return b - a, prior


def _mean(values):
    return sum(values) / len(values) if values else None


def _fresh(ctx, as_of, cadence):
    """True / False from ctx.freshness at the cutoff, None when unknown."""
    if as_of is None:
        return None
    status = (ctx.freshness(str(as_of)[:10], cadence) or {}).get('status')
    return True if status == 'FRESH' else False if status == 'STALE' else None


def _thresholds(ctx):
    weekly = getattr(ctx, 'weekly', None) or {}
    return dict(weekly.get('thresholds') or {}), weekly.get('thresholds_version')


# ---------------------------------------------------------------- vintages

class _Vintages:
    """Every stored version of one series available at T_c: {obs: [(published_at, value)]}."""

    def __init__(self, rows):
        by = defaultdict(list)
        for obs, value, pub in rows:
            by[obs].append((pub, value))
        # stable sort on the publication instant: equal instants keep the storage order
        self.by_obs = {o: sorted(lst, key=lambda t: t[0]) for o, lst in by.items()}
        self.pubs = {o: [p for p, _ in lst] for o, lst in self.by_obs.items()}
        self.min_pub = min((lst[0][0] for lst in self.by_obs.values()), default=None)

    def _index(self, obs, instant):
        pubs = self.pubs.get(obs)
        if not pubs:
            return None
        i = bisect_right(pubs, instant)
        return None if i == 0 else i - 1

    def value(self, obs, instant):
        i = self._index(obs, instant)
        return None if i is None else self.by_obs[obs][i][1]

    def pub(self, obs, instant):
        i = self._index(obs, instant)
        return None if i is None else self.by_obs[obs][i][0]

    def first(self, obs):
        lst = self.by_obs.get(obs)
        return lst[0] if lst else (None, None)


def _versions(ctx, sid):
    """
    [(obs_date, value, available_at)] for every stored FRED version of `sid` available at T_c
    (COALESCE(published_at, retrieved_at) <= T_c, the Database no-look-ahead rule). Uses
    ctx.vintages(series, known_at) when the context offers it, else a read-only query of ctx.db.
    """
    cutoff = ctx.tm.cutoff
    getter = getattr(ctx, 'vintages', None)
    if callable(getter):
        rows = getter(sid, cutoff)
    else:
        extra, args = ctx.db._known_filter(cutoff, False)
        with ctx.db.connect() as conn:
            rows = [(r[0], r[1], r[2]) for r in conn.execute(
                "SELECT as_of_date, value, COALESCE(published_at, retrieved_at) FROM observations "
                "WHERE source='FRED' AND entity=? AND metric='value' AND value IS NOT NULL" + extra
                + ' ORDER BY as_of_date, COALESCE(published_at, retrieved_at), retrieved_at', [sid] + args)]
    out = []
    for obs, value, avail in rows:
        avail = to_utc_iso(avail)
        if value is None or avail is None or avail > cutoff:
            continue
        out.append((str(obs)[:10], float(value), avail))
    return out


def _noise(d, fn):
    """
    Largest |fn(vintage at T_c) - fn(vintage at first print)| over periods first printed inside the
    stored vintages; fn(get, obs) computes a quantity from one vintage (get: obs -> value).
    """
    vers, snap_c = d['vers'], d['snap_c']
    best, n, at, first_obs, last_obs = 0.0, 0, None, None, None
    for obs in sorted(vers.by_obs):
        first_pub = vers.first(obs)[0]
        if first_pub is None or first_pub == vers.min_pub:
            continue                       # start of the stored vintage window, not a first print
        at_first = fn(lambda o, t=first_pub: vers.value(o, t), obs)
        now = fn(snap_c.get, obs)
        if at_first is None or now is None:
            continue
        n += 1
        first_obs = first_obs or obs
        last_obs = obs
        r = abs(now - at_first)
        if r > best:
            best, at = r, obs
    return {'max': best if n else None, 'n': n, 'obs': at, 'from': first_obs, 'to': last_obs}


def _noise_text(spec, noise, what):
    if noise['max'] is None:
        return f'largest revision of {what} not measurable (no first print inside the stored vintages)'
    where = f", {_period(spec, noise['obs'])}" if noise['obs'] and noise['max'] > EPS else ''
    return (f"largest revision of {what} in stored vintages {_fmt(noise['max'], max(_ddigits(spec), 2))}"
            f" over {noise['n']} periods {_period(spec, noise['from'])}..{_period(spec, noise['to'])}{where}")


def _assess(spec, delta, noise, thr):
    """(beyond: bool | None, reason codes, phrase) for a difference against revision noise / threshold."""
    codes, parts = [], []
    if delta is None:
        return None, codes, ''
    if noise['max'] is None:
        beyond = None
        codes.append('FIRST_PRINT_WITHIN_REVISION_NOISE')
        parts.append('revision noise cannot be measured, so the difference is not shown to exceed it')
    else:
        beyond = abs(delta) > noise['max'] + EPS
        if beyond:
            parts.append('beyond revision noise')
        elif abs(delta) <= EPS and noise['max'] <= EPS:
            parts.append('no revision of this quantity was ever observed in the stored vintages')
        else:
            codes.append('FIRST_PRINT_WITHIN_REVISION_NOISE')
            parts.append('within revision noise')
    if thr is not None:
        if abs(delta) < thr:
            codes.append('BELOW_THRESHOLD')
            parts.append(f'below the pre-declared materiality threshold {_fmt(thr, 4)}')
        else:
            parts.append(f'at or above the pre-declared materiality threshold {_fmt(thr, 4)}')
    return beyond, codes, '; '.join(parts)


# ---------------------------------------------------------------- loading

def _load(ctx, sid):
    spec, tm = SERIES[sid], ctx.tm
    d = {'sid': sid, 'spec': spec, 'status': 'OK', 'reason': None, 'fetch': {}, 'covered': False,
         '_cutoff': tm.cutoff, '_previous_cutoff': tm.previous_cutoff}
    st = ctx.fred(sid) or {}
    if st.get('status') != 'OK':
        d.update(status=UNAVAILABLE, reason=f"FRED {sid}: {st.get('reason') or 'fetch failed'}")
        return d
    fetch = st.get('fetch') or {}
    retrieved = to_utc_iso(fetch.get('retrieved_at'))
    d['fetch'] = fetch
    d['covered'] = bool(retrieved) and retrieved > tm.cutoff
    d['latest_c'] = ctx.value_at(sid, tm.cutoff)
    d['latest_p'] = ctx.value_at(sid, tm.previous_cutoff)
    d['snap_c'] = {str(o)[:10]: float(v) for o, v in ctx.series_at(sid, tm.cutoff) if v is not None}
    d['snap_p'] = {str(o)[:10]: float(v) for o, v in ctx.series_at(sid, tm.previous_cutoff) if v is not None}
    first = {str(o)[:10]: to_utc_iso(p) for o, p in (ctx.first_release(sid) or {}).items() if p}
    d['first'] = {o: p for o, p in first.items() if p <= tm.cutoff}     # later first prints are unknown at T_c
    d['new'] = sorted(o for o, p in d['first'].items() if p > tm.previous_cutoff)
    d['vers'] = _Vintages(_versions(ctx, sid))
    if not d['latest_c'] or not d['snap_c']:
        d.update(status=UNAVAILABLE, reason=f'FRED {sid}: no observation known at the cutoff {tm.cutoff} in the '
                                            'stored vintages')
        return d
    d['latest_c'] = (str(d['latest_c'][0])[:10], float(d['latest_c'][1]), to_utc_iso(d['latest_c'][2]))
    if d['latest_p']:
        d['latest_p'] = (str(d['latest_p'][0])[:10], float(d['latest_p'][1]), to_utc_iso(d['latest_p'][2]))
    return d


def _ok(d):
    return d is not None and d['status'] == 'OK'


def _missing_reason(d):
    return 'not requested in this run (series override for a test run)' if d is None else d['reason']


def _pub_at(d, obs, which):
    instant = d['_cutoff'] if which == 'c' else d['_previous_cutoff']
    return d['vers'].pub(obs, instant) if obs else None


def _ev(ctx, d, fact, as_of, published_at, fresh):
    fetch = d.get('fetch') or {}
    return evidence(ctx.tm, SOURCE, RANK, f"{d['sid']}: {fact}", as_of=as_of, published_at=published_at,
                    retrieved_at=fetch.get('retrieved_at'), fetch_id=fetch.get('fetch_id'), fresh=fresh,
                    basis=VINTAGE_BASIS)


def _qty_pub(d, obs, which):
    """Publication instant of the inputs of the displayed quantity (both months for a YoY)."""
    pubs = [_pub_at(d, obs, which)]
    if d['spec']['transform'] == 'yoy' and obs:
        pubs.append(_pub_at(d, _add_months(obs, -12), which))
    pubs = [p for p in pubs if p]
    return max(pubs) if pubs else None


def _coverage(d):
    return [] if d['covered'] else ['PARTIAL_COVERAGE']


def _coverage_text(d):
    if d['covered']:
        return ''
    return (f" FRED fetch retrieved {d['fetch'].get('retrieved_at')}, not after the cutoff: releases between that "
            'fetch and the cutoff may be missing.')


def _new_text(spec, d):
    if not d['new']:
        return 'no'
    last = d['new'][-1]
    return (f"yes: {len(d['new'])} obs (latest {_period(spec, last)}, first published "
            f"{_when(d['first'][last])})")


def _revisions(d):
    """[(obs, value at T_p, value at T_c)] for observations known at T_p and revised by T_c."""
    out = []
    for obs, old in d['snap_p'].items():
        new = d['snap_c'].get(obs)
        if new is not None and abs(new - old) > EPS * max(1.0, abs(old)):
            out.append((obs, old, new))
    return sorted(out)


def _revision_text(spec, revs):
    if not revs:
        return 'no'
    big = max(revs, key=lambda r: abs(r[2] - r[1]))
    return (f'yes: {len(revs)} obs (largest |change| {_fmt(abs(big[2] - big[1]), max(spec["digits"], 2))} '
            f'for {_period(spec, big[0])})')


# ---------------------------------------------------------------- statements

def _asknown(ctx, res, d, q, thr):
    """
    Q3-style statement for one series (also GEPUCURRENT in Q4): displayed quantity as known at T_p and
    at T_c, difference, new release, revisions, revision noise. Returns the table row facts.
    """
    tm, spec, sid = ctx.tm, d['spec'], d['sid']
    dc = d['latest_c'][0]
    dp = d['latest_p'][0] if d['latest_p'] else None
    qc = _qty(spec, d['snap_c'].get, dc)
    qp = _qty(spec, d['snap_p'].get, dp) if dp else None
    revs = _revisions(d)
    noise = _noise(d, lambda get, obs: _qty(spec, get, obs))
    out = {'qc': qc, 'qp': qp, 'dc': dc, 'dp': dp, 'delta': None, 'noise': noise, 'beyond': None,
           'revs': revs, 'record': None, 'items': []}
    what = 'the year-over-year rate' if spec['transform'] == 'yoy' else 'the value'
    if qc is None:
        res.add(unavailable('overall', q, f'{sid} ({spec["label"]})',
                            f'{what} for {_period(spec, dc)} cannot be computed in the vintage known at the cutoff: '
                            f'no observation for {_period(spec, _add_months(dc, -12))} in that vintage'))
        return out
    head = f"{sid} ({spec['label']})"
    fresh = _fresh(ctx, dc, spec['cadence'])          # the series at T_c (also carried by the T_p item)
    item_c = _ev(ctx, d, f'{_val(spec, qc)} for {_period(spec, dc)} as known at T_c {tm.cutoff}', dc,
                 _qty_pub(d, dc, 'c') or d['latest_c'][2], fresh)
    items = [item_c]
    codes = _coverage(d)
    yoy_note = (' (YoY computed within one vintage from the seasonally adjusted index)'
                if spec['transform'] == 'yoy' else '')
    new_note = (f"; new release in the window: {_period(spec, d['new'][-1])} first published "
                f"{_when(d['first'][d['new'][-1]])}" if d['new'] else '; no new observation first published in '
                                                                       'the window')
    if qp is None:
        statement = (f'{head}: {_val(spec, qc)} for {_period(spec, dc)} as known at T_c{yoy_note}; no comparable '
                     f'value as known at T_p in the stored vintages{new_note}.')
    elif dc == dp and abs(qc - qp) <= EPS:
        statement = (f'{head}: no new observation first published in the window; latest as known at T_c: '
                     f'{_val(spec, qc)} for {_period(spec, dc)} (published {_when(_qty_pub(d, dc, "c"))}), unchanged '
                     f'from T_p{yoy_note}.')
    else:
        delta = qc - qp
        out['delta'] = delta
        items.insert(0, _ev(ctx, d, f'{_val(spec, qp)} for {_period(spec, dp)} as known at T_p '
                                    f'{tm.previous_cutoff} (historical vintage)', dp,
                            _qty_pub(d, dp, 'p') or d['latest_p'][2], fresh))
        if dc == dp:
            statement = (f'{head}: the latest observation ({_period(spec, dc)}) was revised from {_val(spec, qp)} '
                         f'(as known at T_p) to {_val(spec, qc)} (as known at T_c){yoy_note}; difference '
                         f'{_diff(spec, delta)}; no new observation first published in the window.')
        else:
            beyond, extra, phrase = _assess(spec, delta, noise, thr)
            out['beyond'] = beyond
            codes += extra
            statement = (f'{head}: {_val(spec, qp)} for {_period(spec, dp)} as known at T_p and {_val(spec, qc)} for '
                         f'{_period(spec, dc)} as known at T_c{yoy_note}; difference {_diff(spec, delta)} '
                         f'({phrase}; {_noise_text(spec, noise, what)}){new_note}.')
    if spec['note']:
        statement = statement[:-1] + f' ({spec["note"]}).'
    statement += _coverage_text(d)
    record = conclude('overall', q, statement, items, 'official_fact', reason_codes=codes)
    res.add(record)
    out.update(record=record, items=items)
    return out


def _release(ctx, res, d, q, thr):
    """Q5-style statement: new release in the window (first print, change vs prior period) or latest."""
    spec, sid = d['spec'], d['sid']
    vers = d['vers']
    noise = _noise(d, lambda get, obs: _chg(spec, get, obs)[0])
    revs = _revisions(d)
    out = {'noise': noise, 'revs': revs, 'm': None, 'first_val': None, 'first_pub': None, 'prior': None,
           'prior_val': None, 'chg': None, 'beyond': None, 'record': None, 'items': []}
    head = f"{sid} ({spec['label']})"
    codes = _coverage(d)
    if sid == 'UMCSENT':
        codes.append('TIMESTAMP_AMBIGUOUS')
    resolve = ('the University of Michigan Surveys of Consumers release with its own publication date'
               if sid == 'UMCSENT' else None)
    chg_what = ('the change vs the prior period' if spec['change'] == 'diff'
                else 'the percent change vs the prior period')
    if d['new']:
        m = d['new'][-1]
        first_pub, first_val = vers.first(m)
        if first_pub is None:                          # accessor without the version: use the release instant
            first_pub, first_val = d['first'][m], d['snap_c'].get(m)
        val_c = d['snap_c'].get(m)
        chg, prior = _chg(spec, d['snap_c'].get, m)
        prior_val = d['snap_c'].get(prior) if prior else None
        out.update(m=m, first_val=first_val, first_pub=first_pub, prior=prior, prior_val=prior_val, chg=chg)
        fresh = _fresh(ctx, m, spec['cadence'])
        items = [_ev(ctx, d, f'first print for {_period(spec, m)} = {_val(spec, first_val)} (first published '
                             f'{_when(first_pub)})', m, first_pub, fresh)]
        parts = [f'{head}: new release in the window: first print for {_period(spec, m)} {_val(spec, first_val)} '
                 f'(first published {_when(first_pub)})']
        if val_c is not None and first_val is not None and abs(val_c - first_val) > EPS:
            parts.append(f'already revised to {_val(spec, val_c)} as known at T_c')
        if len(d['new']) > 1:
            parts.append(f"{len(d['new'])} periods first published in the window "
                         f"({', '.join(_period(spec, o) for o in d['new'])})")
        if chg is not None:
            beyond, extra, phrase = _assess(spec, chg, noise, thr)
            out['beyond'] = beyond
            codes += extra
            pubs = [p for p in (_pub_at(d, m, 'c'), _pub_at(d, prior, 'c')) if p]
            items.append(_ev(ctx, d, f'{_period(spec, prior)} = {_val(spec, prior_val)} -> {_period(spec, m)} = '
                                     f'{_val(spec, val_c)} in the vintage known at T_c ({_diff(spec, chg)})', m,
                             max(pubs) if pubs else first_pub, fresh))
            parts.append(f'change vs {_period(spec, prior)} (both from the T_c vintage) {_diff(spec, chg)} '
                         f'({phrase}; {_noise_text(spec, noise, chg_what)})')
        else:
            parts.append(f'change vs the prior period not computable: no observation for {_period(spec, prior)} '
                         'in the vintage known at T_c')
            res.add(unavailable('overall', q, f'{sid}: change vs the prior period',
                                f'no observation for {_period(spec, prior)} in the FRED vintage known at the cutoff'))
        statement = '; '.join(parts) + '.'
    else:
        dc, vc = d['latest_c'][0], d['latest_c'][1]
        pub = d['first'].get(dc)
        items = [_ev(ctx, d, f'latest as known at T_c: {_val(spec, vc)} for {_period(spec, dc)}', dc,
                     _pub_at(d, dc, 'c') or d['latest_c'][2], _fresh(ctx, dc, spec['cadence']))]
        statement = (f'{head}: no new release in the window (T_p, T_c]; latest as known at T_c: {_val(spec, vc)} '
                     f'for {_period(spec, dc)} (first published {_when(pub)}).')
    if spec['note']:
        statement = statement[:-1] + f' ({spec["note"]}).'
    statement += _coverage_text(d)
    record = conclude('overall', q, statement, items, 'official_fact', reason_codes=codes, resolve=resolve)
    res.add(record)
    out.update(record=record, items=items)
    if revs:
        _revision_record(ctx, res, d, q, revs)
    return out


def _revision_record(ctx, res, d, q, revs):
    spec, sid = d['spec'], d['sid']
    cited = sorted(revs, key=lambda r: -abs(r[2] - r[1]))[:MAX_REVISIONS_CITED]
    items = []
    for obs, old, new in cited:
        pub = _pub_at(d, obs, 'c')
        # a revision is dated by its publication (like a filing), not by the period it revises
        fresh = _fresh(ctx, pub[:10], spec['cadence']) if pub else None
        items.append(_ev(ctx, d, f'{_period(spec, obs)} revised from {_val(spec, old)} (T_p vintage) to '
                                 f'{_val(spec, new)} (T_c vintage), published {_when(pub)}', obs, pub, fresh))
    listed = '; '.join(f'{_period(spec, o)}: {_val(spec, a)} -> {_val(spec, b)}' for o, a, b in cited)
    statement = (f"{sid}: {len(revs)} previously published value(s) were revised between the T_p and T_c vintages "
                 f"(largest: {listed}).") + _coverage_text(d)
    res.add(conclude('overall', q, statement, items, 'official_fact', reason_codes=_coverage(d)))


def _week_ranges(tm):
    s_m5, s_m10 = tm.sessions[-6], tm.sessions[-11]
    return (s_m5, tm.s0), (s_m10, s_m5)


def _weekly_means(ctx, d):
    tm = ctx.tm
    (w_lo, w_hi), (p_lo, p_hi) = _week_ranges(tm)
    cur = sorted((o, v) for o, v in d['snap_c'].items() if w_lo < o <= w_hi)
    prev_p = sorted((o, v) for o, v in d['snap_p'].items() if p_lo < o <= p_hi)
    prev_c = sorted((o, v) for o, v in d['snap_c'].items() if p_lo < o <= p_hi)
    m_c, m_p, m_pc = (_mean([v for _, v in x]) for x in (cur, prev_p, prev_c))
    return {'cur': cur, 'prev_p': prev_p, 'prev_c': prev_c, 'mean_c': m_c, 'mean_p': m_p, 'mean_pc': m_pc,
            'diff': None if m_c is None or m_p is None else m_c - m_p, 'w': (w_lo, w_hi), 'pw': (p_lo, p_hi)}


def _weekly_mean_record(ctx, res, d, q, wm, noise, thr):
    """Statement on the weekly mean of a daily series (USEPUINDXD): T_c week vs T_p previous week."""
    spec, sid = d['spec'], d['sid']
    (w_lo, w_hi), (p_lo, p_hi) = wm['w'], wm['pw']
    if wm['mean_c'] is None or wm['mean_p'] is None:
        missing = 'the week (known at T_c)' if wm['mean_c'] is None else 'the previous week (known at T_p)'
        res.add(unavailable('overall', q, f'{sid} weekly mean', f'no observation dated in {missing} in the '
                                                                'FRED vintages'))
        return None
    last_c, last_p = wm['cur'][-1][0], wm['prev_p'][-1][0]
    pubs_c = [p for p in (_pub_at(d, o, 'c') for o, _ in wm['cur']) if p]
    pubs_p = [p for p in (_pub_at(d, o, 'p') for o, _ in wm['prev_p']) if p]
    fresh = _fresh(ctx, d['latest_c'][0], spec['cadence'])
    items = [_ev(ctx, d, f"mean of {len(wm['prev_p'])} obs dated {p_lo} < d <= {p_hi} as known at T_p = "
                         f"{_fmt(wm['mean_p'], 2)} (historical vintage)", last_p,
                 max(pubs_p) if pubs_p else None, fresh),
             _ev(ctx, d, f"mean of {len(wm['cur'])} obs dated {w_lo} < d <= {w_hi} as known at T_c = "
                         f"{_fmt(wm['mean_c'], 2)}", last_c, max(pubs_c) if pubs_c else None, fresh)]
    beyond, codes, phrase = _assess(spec, wm['diff'], noise, thr)
    statement = (f"{sid} ({spec['label']}): mean of the {len(wm['cur'])} daily values dated in the week "
                 f"({w_lo} < d <= {w_hi}) as known at T_c {_fmt(wm['mean_c'], 2)}, against "
                 f"{_fmt(wm['mean_p'], 2)} for the {len(wm['prev_p'])} values dated in the previous week "
                 f"({p_lo} < d <= {p_hi}) as known at T_p (the same previous week as known at T_c: "
                 f"{_fmt(wm['mean_pc'], 2)}); difference {_diff(spec, wm['diff'])} ({phrase}; "
                 f"{_noise_text(spec, noise, 'a single daily value')}). It measures newspaper coverage of "
                 f"economic-policy uncertainty, not geopolitical events.") + _coverage_text(d)
    record = conclude('overall', q, statement, items, 'official_fact', reason_codes=codes + _coverage(d))
    res.add(record)
    return {'record': record, 'beyond': beyond}


# ---------------------------------------------------------------- Q3

def _target_range(ctx, res, data):
    tm = ctx.tm
    u, l = data.get('DFEDTARU'), data.get('DFEDTARL')
    if not (_ok(u) and _ok(l)):
        reasons = '; '.join(f'{sid}: {_missing_reason(x)}' for sid, x in (('DFEDTARU', u), ('DFEDTARL', l))
                            if not _ok(x))
        res.add(unavailable('overall', 3, 'federal funds target range (DFEDTARU / DFEDTARL)', reasons))
        return None
    if not (u['latest_p'] and l['latest_p']):
        res.add(unavailable('overall', 3, 'federal funds target range change in the window',
                            'no DFEDTARU / DFEDTARL observation known at T_p in the stored vintages'))
        return None
    changes = []
    for x in (u, l):
        keys = sorted(x['snap_c'])
        for prev, cur in zip(keys, keys[1:]):
            pub = x['first'].get(cur)
            if abs(x['snap_c'][cur] - x['snap_c'][prev]) > EPS and pub and pub > tm.previous_cutoff:
                changes.append((x['sid'], cur, x['snap_c'][prev], x['snap_c'][cur], pub))
    up_c, lo_c, up_p, lo_p = u['latest_c'][1], l['latest_c'][1], u['latest_p'][1], l['latest_p'][1]
    d_c, d_p = u['latest_c'][0], u['latest_p'][0]
    items = []
    for x in (u, l):
        fresh = _fresh(ctx, x['latest_c'][0], 'daily')
        items.append(_ev(ctx, x, f"{x['latest_p'][1]:.2f}% for {x['latest_p'][0]} as known at T_p (historical "
                                 'vintage)', x['latest_p'][0], _pub_at(x, x['latest_p'][0], 'p'), fresh))
        items.append(_ev(ctx, x, f"{x['latest_c'][1]:.2f}% for {x['latest_c'][0]} as known at T_c",
                         x['latest_c'][0], _pub_at(x, x['latest_c'][0], 'c'), fresh))
    rng_c, rng_p = f'{lo_c:.2f}-{up_c:.2f}%', f'{lo_p:.2f}-{up_p:.2f}%'
    if changes or abs(up_c - up_p) > EPS or abs(lo_c - lo_p) > EPS:
        detail = ''.join(f'; {sid} {a:.2f} -> {b:.2f} from obs {obs}, first published {_when(pub)}'
                         for sid, obs, a, b, pub in changes)
        statement = (f'The federal funds target range changed: {rng_p} for {d_p} as known at T_p, {rng_c} for {d_c} '
                     f'as known at T_c{detail}. Source: FRED DFEDTARU / DFEDTARL.')
        changed = True
    else:
        statement = (f'No change of the federal funds target range was first published in the window: {rng_p} for '
                     f'{d_p} as known at T_p and {rng_c} for {d_c} as known at T_c. Source: FRED DFEDTARU / '
                     'DFEDTARL. Whether an FOMC meeting took place is not established here (calendar unavailable).')
        changed = False
    statement += _coverage_text(u if not u['covered'] else l)
    codes = _coverage(u) + _coverage(l)
    record = conclude('overall', 3, statement, items, 'official_fact', reason_codes=codes)
    res.add(record)
    return {'record': record, 'changed': changed}


def _q3(ctx, res, data, thr, version):
    rows, mean_rows, moves = [], [], []
    target = _target_range(ctx, res, data)
    for sid, spec in SERIES.items():
        if spec['q'] != 3:
            continue
        d = data.get(sid)
        if not _ok(d):
            reason = _missing_reason(d)
            res.add(unavailable('overall', 3, f'{sid} ({spec["label"]})', reason))
            rows.append([sid, spec['label'], spec['unit'], spec['cadence']] + [None] * 9
                        + [NOT_EVALUATED if d is None else UNAVAILABLE, reason])
            if spec['cadence'] == 'daily':
                mean_rows.append([sid] + [None] * 10)
            if spec['block']:
                moves.append({'sid': sid, 'status': 'not evaluated' if d is None else 'unavailable'})
            continue
        t = thr.get(sid)
        if sid in TARGET:
            a = {'qc': d['latest_c'][1], 'qp': d['latest_p'][1] if d['latest_p'] else None, 'dc': d['latest_c'][0],
                 'dp': d['latest_p'][0] if d['latest_p'] else None, 'revs': _revisions(d),
                 'noise': _noise(d, lambda get, obs, s=spec: _qty(s, get, obs)), 'beyond': None,
                 'record': target['record'] if target else None}
            a['delta'] = None if a['qp'] is None else a['qc'] - a['qp']
        else:
            a = _asknown(ctx, res, d, 3, t)
        level = a['record']['level'] if a.get('record') else UNAVAILABLE
        rows.append([sid, spec['label'], spec['unit'], spec['cadence'], _num(a['qp']), a['dp'] and _period(spec, a['dp']),
                     _num(a['qc']), _period(spec, a['dc']), _num(a['delta']), _new_text(spec, d),
                     _revision_text(spec, a['revs']), _num(a['noise']['max']),
                     None if a['beyond'] is None else ('yes' if a['beyond'] else 'no'), level,
                     ('see the target-range statement' if sid in TARGET else spec['note'])])
        if spec['cadence'] == 'daily':
            wm = _weekly_means(ctx, d)
            b, _, _ = _assess(spec, wm['diff'], a['noise'], t)
            mean_rows.append([sid, _num(wm['mean_c']), len(wm['cur']), _num(wm['mean_p']), len(wm['prev_p']),
                              _num(wm['mean_pc']), len(wm['prev_c']), _num(wm['diff']), _num(a['noise']['max']),
                              None if b is None else ('yes' if b else 'no'),
                              f"{wm['cur'][0][0]}..{wm['cur'][-1][0]}" if wm['cur'] else None])
        if spec['block']:
            moves.append({'sid': sid, 'status': 'ok', 'new': bool(d['new']), 'change': a.get('delta'),
                          'beyond': a.get('beyond'), 'items': a.get('items') or [],
                          'below_threshold': t is not None and a.get('delta') is not None and abs(a['delta']) < t,
                          'unit': spec['diff_unit'], 'spec': spec})
    tm = ctx.tm
    (w_lo, w_hi), (p_lo, p_hi) = _week_ranges(tm)
    res.table('Macro indicators as known at T_p and at T_c (FRED vintages)',
              ['series', 'description', 'unit', 'cadence', 'value as known at T_p', 'obs (T_p)',
               'value as known at T_c', 'obs (T_c)', 'delta (T_c - T_p)', 'new release in window (first publication)',
               'revision of a previously published value', 'largest revision in stored vintages',
               'beyond revision noise', 'level', 'note'],
              rows, question=3,
              note=(f'FRED (rank 1). T_p = {tm.previous_cutoff}, T_c = {tm.cutoff}. Values as known at T are the FRED '
                    'vintage in effect at T (publication instant = end of the vintage date, New York, conservative; '
                    'shown as 05:00 UTC the next day). CPI / PCE rows show YoY % computed within one vintage from the '
                    'seasonally adjusted index (the BLS headline 12-month change uses the unadjusted index and can '
                    'differ slightly). Revision noise is the largest |value at T_c - first print| over periods first '
                    'printed inside the stored vintages. No pre-declared macro materiality threshold in thresholds '
                    f'{version}: differences are facts, not "material changes". Full pre-declared list, moved or not.'))
    res.table('Daily macro series: mean of observations dated in the week vs the previous week',
              ['series', f'week mean ({w_lo} < d <= {w_hi}, known at T_c)', 'n (week, T_c)',
               f'previous-week mean ({p_lo} < d <= {p_hi}, known at T_p)', 'n (previous week, T_p)',
               'previous-week mean (known at T_c)', 'n (previous week, T_c)', 'difference of means',
               'largest daily revision in stored vintages', 'beyond revision noise', 'week obs dates (known at T_c)'],
              mean_rows, question=3,
              note=('Daily values are published with a lag of one day or more, so the latest dates of each week are '
                    'usually not known at its cutoff: compare the n columns. The revision noise of a mean is bounded '
                    'by the largest revision of a single daily value.'))
    _blocks(ctx, res, moves, 'inflation')


# ---------------------------------------------------------------- Q4

def _q4(ctx, res, data, thr, version):
    rows = []
    d = data.get('USEPUINDXD')
    spec = SERIES['USEPUINDXD']
    if _ok(d):
        wm = _weekly_means(ctx, d)
        noise = _noise(d, lambda get, obs: _qty(spec, get, obs))
        out = _weekly_mean_record(ctx, res, d, 4, wm, noise, thr.get('USEPUINDXD'))
        rows.append(['USEPUINDXD', spec['label'], 'mean of daily values dated in the week',
                     None if wm['mean_p'] is None else f"{_fmt(wm['mean_p'], 2)} (n {len(wm['prev_p'])}, "
                                                       f"{wm['pw'][0]} < d <= {wm['pw'][1]})",
                     None if wm['mean_c'] is None else f"{_fmt(wm['mean_c'], 2)} (n {len(wm['cur'])}, "
                                                       f"{wm['w'][0]} < d <= {wm['w'][1]})",
                     _num(wm['diff']), _new_text(spec, d), _num(noise['max']),
                     None if not out or out['beyond'] is None else ('yes' if out['beyond'] else 'no'),
                     out['record']['level'] if out else UNAVAILABLE,
                     f"previous week as known at T_c: {_fmt(wm['mean_pc'], 2)} (n {len(wm['prev_c'])}); "
                     f"revisions vs T_p vintage: {_revision_text(spec, _revisions(d))}"])
    else:
        res.add(unavailable('overall', 4, f'USEPUINDXD ({spec["label"]})', _missing_reason(d)))
        rows.append(['USEPUINDXD', spec['label'], 'mean of daily values dated in the week'] + [None] * 6
                    + [NOT_EVALUATED if d is None else UNAVAILABLE, _missing_reason(d)])
    d = data.get('GEPUCURRENT')
    spec = SERIES['GEPUCURRENT']
    if _ok(d):
        a = _asknown(ctx, res, d, 4, thr.get('GEPUCURRENT'))
        rows.append(['GEPUCURRENT', spec['label'], 'latest monthly value',
                     None if a['qp'] is None else f"{_fmt(a['qp'], 2)} ({_period(spec, a['dp'])})",
                     None if a['qc'] is None else f"{_fmt(a['qc'], 2)} ({_period(spec, a['dc'])})",
                     _num(a['delta']), _new_text(spec, d), _num(a['noise']['max']),
                     None if a['beyond'] is None else ('yes' if a['beyond'] else 'no'),
                     a['record']['level'] if a.get('record') else UNAVAILABLE,
                     f"revisions vs T_p vintage: {_revision_text(spec, a['revs'])}"])
    else:
        res.add(unavailable('overall', 4, f'GEPUCURRENT ({spec["label"]})', _missing_reason(d)))
        rows.append(['GEPUCURRENT', spec['label'], 'latest monthly value'] + [None] * 6
                    + [NOT_EVALUATED if d is None else UNAVAILABLE, _missing_reason(d)])
    res.table('Policy-uncertainty indices (FRED; newspaper-based, NOT records of geopolitical events)',
              ['series', 'description', 'measure', 'as known at T_p', 'as known at T_c', 'difference',
               'new release in window (first publication)', 'largest revision in stored vintages',
               'beyond revision noise', 'level', 'note'],
              rows, question=4,
              note=('USEPUINDXD and GEPUCURRENT count newspaper articles about economic-policy uncertainty; they do not '
                    'identify any geopolitical event and are heavily revised (USEPUINDXD: weekly means only, never a '
                    'single day). Geopolitical event sources (GPR, GDELT, official primary documents) are DATA '
                    'UNAVAILABLE in this environment; news stories are handled by the news section (aggregator, '
                    f'UNCERTAIN at most). Thresholds {version}.'))


# ---------------------------------------------------------------- Q5

def _q5(ctx, res, data, thr, version):
    tm = ctx.tm
    rows, claims, moves = [], [], []
    for sid, spec in SERIES.items():
        if spec['q'] != 5:
            continue
        d = data.get(sid)
        if not _ok(d):
            reason = _missing_reason(d)
            res.add(unavailable('overall', 5, f'{sid} ({spec["label"]})', reason))
            rows.append([sid, spec['label'], spec['unit']] + [None] * 10
                        + [NOT_EVALUATED if d is None else UNAVAILABLE, reason])
            if sid in ('ICSA', 'CCSA'):
                claims.append([sid] + [None] * 4 + [reason])
            if spec['block']:
                moves.append({'sid': sid, 'status': 'not evaluated' if d is None else 'unavailable'})
            continue
        t = thr.get(sid)
        a = _release(ctx, res, d, 5, t)
        dc, vc = d['latest_c'][0], d['latest_c'][1]
        rows.append([sid, spec['label'], spec['unit'], 'yes' if d['new'] else 'no',
                     a['m'] and _period(spec, a['m']), _num(a['first_val']), _when(a['first_pub']) if a['m'] else None,
                     _num(a['prior_val']), _num(a['chg']), _num(a['noise']['max']),
                     None if a['beyond'] is None else ('yes' if a['beyond'] else 'no'),
                     _revision_text(spec, a['revs']),
                     f"{_val(spec, vc)} ({_period(spec, dc)}; first published {_when(d['first'].get(dc))})",
                     a['record']['level'], spec['note']])
        if sid in ('ICSA', 'CCSA'):
            claims.append(_claims_row(spec, d))
        if spec['block']:
            moves.append({'sid': sid, 'status': 'ok', 'new': bool(d['new']), 'change': a['chg'],
                          'beyond': a['beyond'], 'items': a['items'],
                          'below_threshold': t is not None and a['chg'] is not None and abs(a['chg']) < t,
                          'unit': spec['diff_unit'], 'spec': spec})
    res.table('Socio-economic indicators: releases in the window (FRED vintages)',
              ['series', 'description', 'unit', 'new release in window', 'period', 'first print',
               'first published', 'prior period (T_c vintage)', 'change vs prior period (T_c vintage)',
               'largest revision of that change in stored vintages', 'beyond revision noise',
               'revisions vs T_p vintage', 'latest as known at T_c', 'level', 'note'],
              rows, question=5,
              note=(f'FRED (rank 1). Window (T_p, T_c] = ({tm.previous_cutoff}, {tm.cutoff}]. A release date is the '
                    'FRED vintage date; the reference period is not the release date. Changes: absolute for levels, '
                    'percent for RSAFS, HOUST and CES0500000003; PAYEMS change = monthly payroll change. "Beyond '
                    'revision noise" only when |change| > the largest revision of that change between first print '
                    'and the T_c vintage over the stored vintages. No pre-declared macro materiality threshold in '
                    f'thresholds {version}. Official sampling errors are not available.'))
    res.table('Weekly unemployment claims: 4-week averages (each from one vintage)',
              ['series', 'weeks (T_c vintage)', '4-week average, T_c vintage', 'weeks (T_p vintage)',
               '4-week average, T_p vintage', 'note'],
              claims, question=5,
              note='Average of the 4 latest consecutive weekly observations of one vintage; N/A when a week is missing.')
    _real_earnings(ctx, res, data)
    _blocks(ctx, res, moves, 'labour')
    _blocks(ctx, res, moves, 'consumer')


def _four_week(snap):
    keys = sorted(snap)
    if not keys:
        return None, None
    last = date.fromisoformat(keys[-1])
    weeks = [(last - timedelta(days=7 * k)).isoformat() for k in range(4)]
    if any(w not in snap for w in weeks):
        return None, f'{weeks[-1]}..{weeks[0]} (incomplete)'
    return sum(snap[w] for w in weeks) / 4, f'{weeks[-1]}..{weeks[0]}'


def _claims_row(spec, d):
    avg_c, w_c = _four_week(d['snap_c'])
    avg_p, w_p = _four_week(d['snap_p'])
    return [d['sid'], w_c, _num(avg_c), w_p, _num(avg_p),
            'CCSA is published one week later than ICSA' if d['sid'] == 'CCSA' else None]


def _real_earnings(ctx, res, data):
    """Derived real average hourly earnings (AHE / CPI-U SA x 100, 1982-84 USD), same month, T_c vintage."""
    ahe, cpi = data.get('CES0500000003'), data.get('CPIAUCSL')
    item = 'derived real average hourly earnings (CES0500000003 / CPIAUCSL)'
    if not (_ok(ahe) and _ok(cpi)):
        reasons = '; '.join(f'{sid}: {_missing_reason(x)}' for sid, x in (('CES0500000003', ahe), ('CPIAUCSL', cpi))
                            if not _ok(x))
        res.add(unavailable('overall', 5, item, reasons))
        return
    both = sorted(set(ahe['snap_c']) & set(cpi['snap_c']))
    latest_ahe = max(ahe['snap_c'])
    if not both:
        res.add(unavailable('overall', 5, item, 'no month with both series known at the cutoff'))
        return
    m = both[-1]
    prior = _add_months(m, -1)
    real = ahe['snap_c'][m] / cpi['snap_c'][m] * 100
    real_p = (ahe['snap_c'][prior] / cpi['snap_c'][prior] * 100
              if prior in ahe['snap_c'] and prior in cpi['snap_c'] else None)
    pct = None if real_p is None else (real / real_p - 1) * 100
    lag = (f'; real earnings for {latest_ahe[:7]} cannot be derived yet: CPI for that month is not known at T_c'
           if latest_ahe > m else '')
    rows = [[m[:7], _num(ahe['snap_c'][m]), _num(cpi['snap_c'][m]), round(real, 4),
             None if pct is None else round(pct, 3), 'derived (ESTIMATE), T_c vintage']]
    res.table('Derived: real average hourly earnings (not an official print)',
              ['month', 'average hourly earnings (USD)', 'CPI-U SA (1982-84 = 100)', 'real AHE (1982-84 USD)',
               'change vs prior month %', 'status'], rows, question=5,
              note=('Computed by this report as AHE / CPIAUCSL x 100 with both values of the same month as known at T_c. '
                    'The BLS Real Earnings release (bls.gov blocked) is the official figure.' + lag))
    fresh = _fresh(ctx, m, 'monthly')
    items = [_ev(ctx, ahe, f'{m[:7]} = {_fmt(ahe["snap_c"][m])} USD/h as known at T_c', m, _pub_at(ahe, m, 'c'), fresh),
             _ev(ctx, cpi, f'{m[:7]} = {_fmt(cpi["snap_c"][m], 3)} as known at T_c', m, _pub_at(cpi, m, 'c'), fresh)]
    statement = (f'Derived (not an official print): real average hourly earnings for {m[:7]} = {_fmt(real, 3)} '
                 f'(1982-84 USD; CES0500000003 / CPIAUCSL x 100, both as known at T_c)'
                 + ('' if pct is None else f', {_sfmt(pct, 2)}% vs {prior[:7]} in the same vintage') + lag + '.')
    res.add(conclude('overall', 5, statement, items, 'official_fact',
                     reason_codes=['ESTIMATE'] + _coverage(ahe) + _coverage(cpi),
                     resolve='the BLS Real Earnings release (bls.gov blocked by the proxy)'))


# ---------------------------------------------------------------- direction by block (interpretation)

def _blocks(ctx, res, moves, block):
    info = BLOCKS[block]
    q = info['q']
    rows, counted = [], []
    for mv in moves:
        spec = SERIES[mv['sid']]
        if spec['block'] != block:
            continue
        if mv['status'] != 'ok':
            rows.append([info['name'], mv['sid'], None, None, None, None, f"no ({mv['status']})"])
            continue
        direction = None
        if mv['change'] is not None and abs(mv['change']) > EPS:
            direction = info['up'] if mv['change'] * spec['sign'] > 0 else info['down']
        ok = bool(mv['new'] and mv['beyond'] and direction and not mv['below_threshold'])
        why = ('yes' if ok else 'no: no new release in the window' if not mv['new']
               else 'no: change not computable' if mv['change'] is None
               else 'no: below the pre-declared threshold' if mv['below_threshold']
               else 'no: not beyond revision noise' if not mv['beyond'] else 'no: unchanged')
        rows.append([info['name'], mv['sid'], 'yes' if mv['new'] else 'no',
                     None if mv['change'] is None else _diff(spec, mv['change']),
                     None if mv['beyond'] is None else ('yes' if mv['beyond'] else 'no'), direction, why])
        if ok:
            counted.append((mv, direction))
    res.table(f'{info["name"]}: direction of changes beyond revision noise (sign convention {DIRECTION_CONVENTION})',
              ['block', 'series', 'new release in window', 'change', 'beyond revision noise',
               'direction under the convention', 'counted'], rows, question=q,
              note=('Pre-declared sign convention: ' + ', '.join(
                  f"{sid} {'+' if s['sign'] > 0 else '-'}" for sid, s in SERIES.items() if s['block'] == block)
                    + f" (+ = an increase is '{info['up']}'). A directional reading needs >= 2 indicators with a new "
                      'release in the window and a change beyond revision noise, all pointing the same way; it is '
                      'always an interpretation (UNCERTAIN by rule).'))
    directions = {d for _, d in counted}
    if len(counted) >= 2 and len(directions) == 1:
        word = directions.pop()
        listed = ', '.join(f"{mv['sid']} {_diff(mv['spec'], mv['change'])}" for mv, _ in counted)
        items = [i for mv, _ in counted for i in mv['items']]
        statement = (f"{info['name']}: {len(counted)} pre-declared indicators with a new release in the window changed "
                     f"beyond revision noise, all in the '{word}' direction under sign convention "
                     f"{DIRECTION_CONVENTION} ({listed}). Reading these together as a '{word}' {block} picture is an "
                     'interpretation: official sampling errors and consensus are not available.')
        res.add(conclude('overall', q, statement, items, 'interpretation'))


# ---------------------------------------------------------------- section

def build(ctx, series=None):
    """
    series: optional iterable of series ids to evaluate (testing / request budgets); the others are
    shown in the full tables as NOT EVALUATED and listed as DATA UNAVAILABLE with that reason.
    """
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    selected = list(SERIES) if series is None else list(dict.fromkeys(series))
    unknown = [s for s in selected if s not in SERIES]
    if unknown:
        raise ValueError(f'series not pre-declared in the macro section: {", ".join(unknown)}')
    data = {sid: (_load(ctx, sid) if sid in selected else None) for sid in SERIES}
    thresholds, version = _thresholds(ctx)
    macro_thr = {k: float(v) for k, v in (thresholds.get('macro_abs_change') or {}).items()
                 if isinstance(v, (int, float))}
    _q3(ctx, res, data, macro_thr, version)
    _q4(ctx, res, data, macro_thr, version)
    _q5(ctx, res, data, macro_thr, version)
    for q, item, reason in STATIC_UNAVAILABLE:
        res.add(unavailable('overall', q, item, reason))
    (w_lo, w_hi), (p_lo, p_hi) = _week_ranges(tm)
    res.notes.append(f'Window (T_p, T_c] = ({tm.previous_cutoff}, {tm.cutoff}]; week observations {w_lo} < d <= {w_hi}, '
                     f'previous week {p_lo} < d <= {p_hi}. Values as known at T are FRED vintages (publication = end '
                     'of the vintage date, New York, conservative); FRED gives dates only, no time of day.')
    res.notes.append(f'Thresholds {version}: ' + (
        'macro materiality thresholds applied from weekly.thresholds.macro_abs_change.' if macro_thr else
        'no pre-declared macro materiality threshold (weekly.thresholds has no macro_abs_change): differences are '
        'reported as facts and tested only against revision noise; no "material change" is claimed.'))
    res.notes.append('USEPUINDXD and GEPUCURRENT measure economic-policy uncertainty from newspaper coverage; they '
                     'are not records of geopolitical events. Geopolitical events have no rank-1 source here.')
    res.notes.append('Macro and socio-economic data are economy-wide: no company-level attribution is made; any link '
                     'with a company or a price move is timing only ("coincided with").')
    res.notes.append(f'Directional block readings use sign convention {DIRECTION_CONVENTION} and are always '
                     'interpretations (UNCERTAIN by rule).')
    skipped = [s for s in SERIES if data[s] is None]
    if skipped:
        res.notes.append(f'Series override: {len(skipped)} pre-declared series not evaluated in this run '
                         f'({", ".join(skipped)}).')
    return res
