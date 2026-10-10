#!/usr/bin/env python3
"""
Weekly report section 'quant' - Q10 "What does the quantitative model currently say?" and Q11
"How reliable is that quantitative signal?" (phase P3.0)

Q10 - the live heuristic signal recomputed POINT-IN-TIME with the production code, at T_c and T_p
  technical     PriceTechnical().score_closes(adjusted closes of ctx.prices(t) up to s_0 / s_-5)
  fundamentals  ScoringFundamentals(ctx.sec).score_inputs(ctx.sec.fundamentals(t, known_at=T))
  insider       insider_score(InsiderTracker(sec_parser=ctx.sec).summarize(t, known_at=T)): stored
                Form 4 transactions only (ingest / run are never called: they would contact SEC). The
                score is computed only when every Form 4 listed in the submissions feed for (T - 90 d, T]
                has its document stored AND its stored form4:transaction rows match the dated
                transactions of that document re-parsed locally (else the stored rows would read as "no
                transaction" = a neutral 50), and the feed was retrieved after T and reaches back to the
                window start (or ctx.filings says it is the whole, untruncated history).
  news          only at T_c, and only from the latest daily run file reports/analysis.json when its
                timestamp is <= T_c (nothing is fetched). The file is overwritten by each daily run,
                so news is normally DATA UNAVAILABLE for a report generated later; never at T_p.
  Combined with ScoringSignalFixed().combine_scores / generate_final_signal (>= 2 components, weights
  0.25 / 0.40 / 0.20 / 0.15 renormalized over the available components, labels POSITIVE >= 65,
  NEGATIVE <= 40). Shown: the ex-news variant first (technical + fundamentals + insider: the variant
  the walk-forward evaluated), then the live 4-component variant; per-component contributions
  w_i' x s_i with renormalized weights; the delta S(T_c) - S(T_p) split into a score effect on the
  components available at both cutoffs (sum of w_i^C x (s_i(T_c) - s_i(T_p))) and a coverage effect
  (the rest, from components present at one cutoff only); the distance to the nearest threshold.
  "Borderline" is flagged only when config weekly.thresholds declares signal_borderline_points.
  Kinds: "the heuristic outputs X" is a statement about this system (system_output); any reading of
  the signal as information about future returns is model_output (MODEL_NOT_VALIDATED unless the
  validation is DEMONSTRATED; HEURISTIC_THRESHOLD always). The universe summary carries every ticker's
  T_c ex-news evidence and the walk-forward run it cites, so it is never stronger than its premises.
  Every statement about what the walk-forward found cites the run (computed_at, IC, p per horizon) and
  reads significance from the corrected p-value and the IC sign (validation_text): "not significant"
  only when p >= 0.05 / k, "significantly NEGATIVE" when p < 0.05 / k with IC < 0, and a stale run is
  said to be stale; without an admissible run the status (NOT VALIDATED) is stated as is.
Q11 - validation_status(walk_forward.latest_summary(now=T_c), research summaries computed <= T_c)
  as the banner conclusion (system_output); validation figures per horizon with an approximate 95 %
  interval for the IC; runs computed after the cutoff are listed as such and never used; data
  reliability per component at T_c (coverage, freshness at the cutoff, source rank) kept separate from
  signal validity; model prediction, prediction confidence and risk score are NOT IMPLEMENTED.
No score is ever converted into a probability. Sections never call the wall clock and never write files.
"""

import json
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

from ...common import DATA_UNAVAILABLE, reports_dir, to_utc_iso
from ...insider_tracker import (FORM4_METRIC, LOOKBACK_DAYS, InsiderTracker, form4_xml_url, insider_score,
                                parse_form4)
from ...market_data import session_close_utc
from ...price_technical import PriceTechnical
from ...scoring_fundamentals import ScoringFundamentals
from ...scoring_signal_fixed import (NOT_A_RECOMMENDATION, VALIDATION_ALPHA, ScoringSignalFixed,
                                     not_implemented_fields, research_summary, two_sided_p, validation_status)
from ...walk_forward import STALE_AFTER_DAYS, latest_summary
from ..core import LookAheadError, SectionResult, conclude, evidence, unavailable

NAME = 'quant'
QUESTIONS = [10, 11]

COMPONENTS = ('technical', 'fundamentals', 'news', 'insider')
EX_NEWS = ('technical', 'fundamentals', 'insider')
MIN_CLOSES = 70                     # PriceTechnical.analyze: 70 closes required
SEC_SOURCE, YF_SOURCE, NEWS_SOURCE = 'SEC EDGAR', 'yfinance', 'NewsAPI'
RANKS = {'technical': (YF_SOURCE, 2), 'fundamentals': (SEC_SOURCE, 1), 'insider': (SEC_SOURCE, 1),
         'news': (NEWS_SOURCE, 3)}
CADENCES = {'technical': 'daily_market', 'fundamentals': 'quarterly_filing', 'insider': 'daily', 'news': 'news'}
SYSTEM_SOURCE = 'this system'
RESEARCH_STAGES = (1, 2)
CI_Z = 1.96
BORDERLINE_TOL = 1e-9               # stated tolerance of the borderline-band comparison (float noise only)


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def _r(v, digits=2):
    return None if v is None else round(v, digits)


def _fresh(ctx, as_of, cadence, at=None):
    """Freshness flag at the cutoff, or at another instant `at` (T_p inputs), via ctx.freshness."""
    if as_of is None:
        return None
    status = (ctx.freshness(str(as_of)[:10], cadence, at=at) or {}).get('status')
    return True if status == 'FRESH' else False if status == 'STALE' else None


def _fresh_text(flag):
    return 'FRESH' if flag is True else 'STALE' if flag is False else 'UNKNOWN'


def _tp_note(ctx, at):
    return '' if at == ctx.tm.cutoff else '; freshness evaluated at T_p (input of the previous cutoff)'


def _comp(name, score=None, reason=None, as_of=None, item=None, detail=None, fresh=None):
    source, rank = RANKS[name]
    return {'name': name, 'score': score, 'reason': reason, 'as_of': as_of, 'evidence': item,
            'detail': detail, 'fresh': fresh, 'source': source, 'rank': rank}


# ---------------------------------------------------------------- components (point-in-time)

def technical(ctx, t, session, at):
    p = ctx.prices(t)
    frame = p.get('frame')
    if p.get('status') != 'OK' or frame is None or 'close' not in getattr(frame, 'columns', []):
        return _comp('technical', reason=f"yfinance prices unavailable: {p.get('reason') or 'no data'}")
    close = frame['close']
    close = close[[d.date().isoformat() <= session for d in close.index]].dropna()
    if len(close) < MIN_CLOSES:
        return _comp('technical', reason=f'only {len(close)} adjusted closes up to {session} ({MIN_CLOSES} required)')
    last = close.index[-1].date().isoformat()
    scored = PriceTechnical().score_closes(close.to_numpy(dtype=float))
    if scored is None:
        return _comp('technical', reason='indicator computation returned NaN', as_of=last)
    fetch = p.get('fetch') or {}
    fresh = _fresh(ctx, last, CADENCES['technical'], at)
    c = scored['components']
    detail = (f"RSI {c['rsi']['value']} ({c['rsi']['score']}), MACD histogram {c['macd']['histogram']} "
              f"({c['macd']['score']}), Bollinger ({c['bollinger']['signal']}, {c['bollinger']['score']}); "
              f"{min(len(close), 150)} closes up to {last}" + ('' if last == session else f' (no bar for {session})'))
    item = evidence(ctx.tm, YF_SOURCE, 2, f'{t}: adjusted closes up to {last} -> technical score '
                                          f"{scored['technical_score']} ({detail})",
                    as_of=last, published_at=session_close_utc(last), retrieved_at=fetch.get('retrieved_at'),
                    fetch_id=fetch.get('fetch_id'), fresh=fresh,
                    basis='session close 21:00 UTC (estimate)' + _tp_note(ctx, at))
    return _comp('technical', score=_num(scored['technical_score']), as_of=last, item=item, detail=detail,
                 fresh=fresh)


def _latest_periodic(ctx, t, at):
    try:
        feed = ctx.filings(t)
    except LookAheadError:
        raise
    except Exception:  # noqa: BLE001 - optional (freshness fallback only)
        return None, None
    if feed.get('status') != 'OK':
        return None, feed
    rows = [f for f in feed.get('filings') or [] if f.get('form') in ('10-Q', '10-K', '10-Q/A', '10-K/A')
            and f.get('published_at') and to_utc_iso(f['published_at']) <= at]
    return (max(rows, key=lambda f: to_utc_iso(f['published_at'])) if rows else None), feed


def fundamentals(ctx, t, at):
    fin = ctx.sec.fundamentals(t, known_at=at) or {}
    composite, parts = ScoringFundamentals(ctx.sec).score_inputs({
        'revenue': fin.get('revenue'), 'revenue_growth_pct': fin.get('revenue_growth_pct'),
        'debt_to_equity': fin.get('debt_to_equity')})
    if composite is None:
        return _comp('fundamentals', reason=f"SEC XBRL inputs unavailable at {at}: "
                                            f"{fin.get('reason') or 'no usable XBRL financial facts'}")
    pub = fin.get('revenue_published_at')
    basis = 'latest acceptance time of the revenue facts used (XBRL replayed by acceptance time)'
    if not pub:
        latest, _ = _latest_periodic(ctx, t, at)
        pub = latest and latest['published_at']
        basis = 'acceptance time of the latest 10-Q / 10-K known at that instant'
    if pub and to_utc_iso(pub) > to_utc_iso(at):
        raise LookAheadError(f'{t}: fundamentals input published {pub} after {at}')
    rev, g, de = fin.get('revenue'), fin.get('revenue_growth_pct'), fin.get('debt_to_equity')
    detail = (f"revenue TTM {None if rev is None else f'{rev:,.0f} USD'} (period end {fin.get('revenue_period_end')}), "
              f"growth {g}%, debt/equity {de} (balance sheet {fin.get('balance_sheet_date')}); component scores "
              + ', '.join(f'{k} {v}' for k, v in parts.items()))
    fresh = _fresh(ctx, pub, CADENCES['fundamentals'], at) if pub else None
    fetch = fin.get('fetch') or {}
    item = None
    if pub:
        item = evidence(ctx.tm, SEC_SOURCE, 1, f'{t}: XBRL facts known at {at} -> fundamentals score {composite} '
                                               f'({detail})',
                        as_of=str(pub)[:10], published_at=pub, retrieved_at=fetch.get('retrieved_at'),
                        fetch_id=fetch.get('fetch_id'), fresh=fresh, basis=basis + _tp_note(ctx, at))
    return _comp('fundamentals', score=_num(composite), as_of=str(pub)[:10] if pub else None, item=item,
                 detail=detail + ('' if pub else '; publication instant of the inputs not established'),
                 fresh=fresh)


def _stored_transactions(db, t, start, at):
    """{accession: number of stored form4:transaction rows} available in (start, at] (what summarize reads)."""
    counts = {}
    for e in db.events(t, FORM4_METRIC, published_from=start, published_to=at, source=SEC_SOURCE):
        try:
            acc = (json.loads(e.get('value_text') or '{}') or {}).get('accession')
        except (TypeError, ValueError, AttributeError):
            acc = None
        counts[acc] = counts.get(acc, 0) + 1
    return counts


def _list(values, n=5):
    values = [str(v) for v in values]
    return ', '.join(values[:n]) + (f' (+{len(values) - n} more)' if len(values) > n else '')


def insider_coverage(ctx, t, at):
    """
    (ok, problem, n_filings, n_transactions). ok only when every Form 4 of (at - 90 d, at] listed in the
    feed has its document stored AND the stored form4:transaction rows of that accession match the dated
    non-derivative transactions of the stored document, re-parsed locally (no network): a document stored
    without its transactions (prefetch, parse failure) would otherwise read as "no transaction".
    """
    try:
        feed = ctx.filings(t)
    except LookAheadError:
        raise
    except Exception as e:  # noqa: BLE001
        return False, f'SEC submissions feed unavailable: {type(e).__name__}: {e}', None, None
    if feed.get('status') != 'OK':
        return False, f"SEC submissions feed unavailable: {feed.get('reason')}", None, None
    retrieved = to_utc_iso((feed.get('fetch') or {}).get('retrieved_at'))
    if not retrieved or retrieved < to_utc_iso(at):
        return False, (f'submissions feed retrieved at {retrieved}, before {at}: Form 4 filings accepted after '
                       'that retrieval are not listed'), None, None
    start = to_utc_iso(datetime.fromisoformat(to_utc_iso(at)) - timedelta(days=LOOKBACK_DAYS))
    rows = feed.get('filings') or []
    # 'truncated' False: the feed holds the company's whole filing history, so the window is fully
    # listed even when nothing older exists (recent registrant); unknown / True: the recent block must
    # reach back past the window start.
    if feed.get('truncated') is not False and not any(
            f.get('published_at') and to_utc_iso(f['published_at']) <= start for f in rows):
        return False, ('the submissions feed (recent block) lists no filing older than the window start '
                       f'{start}: the {LOOKBACK_DAYS}-day Form 4 window may not be fully listed'), None, None
    window = [f for f in rows if f.get('form') == '4' and f.get('published_at')
              and start < to_utc_iso(f['published_at']) <= to_utc_iso(at)]
    if not window:
        return True, None, 0, 0
    cik = ctx.sec.get_cik(t)
    if not cik:
        return False, f'CIK of {t} not resolved: Form 4 documents cannot be checked', None, None
    db = ctx.db
    if not hasattr(db, 'read_raw') or not hasattr(db, 'events'):
        return False, 'stored Form 4 documents cannot be re-read from this database', len(window), None
    stored = _stored_transactions(db, t, start, at)
    missing, unreadable, mismatch, n_txn = [], [], [], 0
    for f in window:
        acc = f.get('accession_number')
        if not acc or not f.get('primary_document'):
            missing.append(acc)
            continue
        fetch = db.latest_fetch(SEC_SOURCE, form4_xml_url(cik, acc, f['primary_document']))
        if not fetch:
            missing.append(acc)
            continue
        try:
            doc = parse_form4(db.read_raw(fetch['fetch_id']))
        except (ET.ParseError, RuntimeError, OSError, ValueError, TypeError, AttributeError) as e:
            unreadable.append(f'{acc} ({type(e).__name__})')
            continue
        expected = sum(1 for x in doc['transactions'] if x.get('date'))      # what ingest stores
        n_txn += expected
        if stored.get(acc, 0) != expected:
            mismatch.append(f'{acc}: {stored.get(acc, 0)} stored vs {expected} in the document')
    problems = []
    if missing:
        problems.append(f'{len(missing)} of {len(window)} Form 4 filings accepted in ({start}, {at}] have no stored '
                        f'document ({_list(missing)}; never ingested or unreadable)')
    if unreadable:
        problems.append(f'{len(unreadable)} stored Form 4 documents cannot be re-read or parsed '
                        f'({_list(unreadable)}): their transactions cannot be confirmed')
    if mismatch:
        problems.append(f'{len(mismatch)} stored Form 4 documents do not match the stored {FORM4_METRIC} rows '
                        f'({_list(mismatch)}): stored without ingesting their transactions (e.g. a prefetch or a '
                        'parse failure)')
    if problems:
        return False, ('; '.join(problems) + ': the stored transactions would read them as "no transaction" '
                       '(this report does not call InsiderTracker.ingest, which would contact SEC)'), len(window), None
    return True, None, len(window), n_txn


def insider(ctx, t, at):
    ok, problem, n, n_txn = insider_coverage(ctx, t, at)
    if not ok:
        return _comp('insider', reason=problem)
    summary = InsiderTracker(sec_parser=ctx.sec).summarize(t, known_at=at)
    score = insider_score(summary)
    detail = (f"{n} Form 4 filings accepted in the {LOOKBACK_DAYS}-day window, all documents stored and their "
              f"{n_txn} dated non-derivative transactions ingested (re-checked against the stored documents); "
              f"{summary['insider_buys']} open-market purchases by {summary['distinct_buyers']} insider(s), "
              f"{summary['insider_sells']} open-market sales ({summary['discretionary_sellers']} discretionary "
              f"seller(s)); other codes {summary['other_transaction_codes']}")
    as_of = to_utc_iso(at)[:10]
    fresh = _fresh(ctx, as_of, CADENCES['insider'], at)
    feed = ctx.filings(t)
    fetch = feed.get('fetch') or {}
    item = evidence(ctx.tm, SEC_SOURCE, 1, f'{t}: Form 4 window ending {at} -> insider score {score} ({detail})',
                    as_of=as_of, published_at=at, retrieved_at=fetch.get('retrieved_at'),
                    fetch_id=fetch.get('fetch_id'), fresh=fresh,
                    basis=f'window summary of Form 4 transactions ({FORM4_METRIC}) filed by that instant; feed '
                          'retrieved after it' + _tp_note(ctx, at))
    return _comp('insider', score=_num(score), as_of=as_of, item=item, detail=detail, fresh=fresh)


def load_daily_run(path=None):
    """{ticker: entry} of reports/analysis.json, or (None, reason)."""
    path = Path(path) if path else reports_dir() / 'analysis.json'
    if not path.exists():
        return None, f'no daily run file {path.name}'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        return None, f'daily run file {path.name} unreadable: {type(e).__name__}'
    rows = data if isinstance(data, list) else [data]
    return {r.get('ticker'): r for r in rows if isinstance(r, dict)}, None


def news(ctx, t, daily, daily_problem):
    tm = ctx.tm
    if daily is None:
        return _comp('news', reason=f'{daily_problem}: nothing is fetched by this report')
    entry = daily.get(t)
    if not entry:
        return _comp('news', reason=f'{t} not in the latest daily run file')
    ts = to_utc_iso(entry.get('timestamp'))
    if not ts or ts > tm.cutoff:
        return _comp('news', reason=f'the latest daily run ({ts}) is after the cutoff {tm.cutoff}; analysis.json is '
                                    'overwritten by each daily run, so no news score computed at or before the '
                                    'cutoff is stored (nothing is fetched by this report)')
    n = (entry.get('modules') or {}).get('news') or {}
    score = _num(n.get('news_score'))
    if score is None:
        return _comp('news', reason=f"no news score in the daily run of {ts}: {n.get('reason') or n.get('status')}")
    prov = n.get('provenance') or {}
    newest = n.get('newest_article_published_at')
    as_of = str(newest or prov.get('as_of_date') or ts)[:10]
    fresh = _fresh(ctx, as_of, CADENCES['news'])
    detail = (f"{n.get('articles_count')} articles {n.get('oldest_article_published_at')} -> {newest}; "
              f"{n.get('method') or 'naive lexicon'}; PROVISIONAL (naive lexicon, never validated)")
    retrieved = to_utc_iso(prov.get('retrieved_at'))
    item = evidence(tm, NEWS_SOURCE, 3, f'{t}: news score {score} from the daily run of {ts} ({detail})',
                    as_of=as_of, published_at=ts, retrieved_at=retrieved,
                    fetch_id=prov.get('fetch_id'), fresh=fresh, basis='timestamp of the daily run that computed it')
    return _comp('news', score=score, as_of=as_of, item=item, detail=detail, fresh=fresh)


def _safe(fn, name, *args):
    try:
        return fn(*args)
    except LookAheadError:
        raise
    except Exception as e:  # noqa: BLE001 - one component must not stop the section
        return _comp(name, reason=f'{type(e).__name__}: {e}')


# ---------------------------------------------------------------- combination

def combine(signal, comps, names):
    """{'score' (production, rounded), 'label', 'available', 'missing', 'weights', 'contrib', 'raw'}."""
    scores = {k: comps[k]['score'] for k in names}
    available = [k for k in names if scores[k] is not None]
    missing = [k for k in names if scores[k] is None]
    score = signal.combine_scores(scores) if len(available) >= signal.MIN_COMPONENTS else None
    label = signal.generate_final_signal(score)
    # no S (INSUFFICIENT DATA): no renormalized weight and no contribution to a score that does not exist
    total = sum(signal.WEIGHTS[k] for k in available) if score is not None else 0
    weights = {k: signal.WEIGHTS[k] / total for k in available} if total else {}
    contrib = {k: weights[k] * scores[k] for k in weights}
    raw = sum(contrib.values()) if score is not None else None
    return {'score': score, 'label': label, 'available': available, 'missing': missing, 'weights': weights,
            'contrib': contrib, 'raw': raw, 'n': len(names), 'scores': scores}


def decompose(signal, now, before):
    """Score effect per common component + coverage effect; sums to raw(now) - raw(before)."""
    if now['raw'] is None or before['raw'] is None:
        return None
    common = [k for k in now['available'] if k in before['available']]
    total = sum(signal.WEIGHTS[k] for k in common)
    effects = {k: signal.WEIGHTS[k] / total * (now['scores'][k] - before['scores'][k]) for k in common} if total else {}
    delta = now['raw'] - before['raw']
    return {'common': common, 'effects': effects, 'score_effect': sum(effects.values()),
            'coverage_effect': delta - sum(effects.values()), 'delta': delta}


def nearest_threshold(signal, score):
    if score is None:
        return None, None
    pos, neg = signal.POSITIVE_THRESHOLD, signal.NEGATIVE_THRESHOLD
    thr = pos if abs(score - pos) <= abs(score - neg) else neg
    return thr, score - thr


def _borderline(ctx):
    v = ((getattr(ctx, 'weekly', None) or {}).get('thresholds') or {}).get('signal_borderline_points')
    return _num(v)


def is_borderline(dist, band):
    """|distance to the nearest threshold| <= band, with tolerance BORDERLINE_TOL (float noise); None if not assessed."""
    if band is None or dist is None:
        return None
    return abs(dist) <= band + BORDERLINE_TOL


def _items(*comp_sets):
    return [c['evidence'] for comps in comp_sets for c in comps.values() if c.get('evidence')]


# ---------------------------------------------------------------- Q11 validation

def _admissible_research(tm, paths=None):
    ok, late, missing = [], [], []
    for stage in RESEARCH_STAGES:
        path = (paths or {}).get(stage)
        r = research_summary(stage, Path(path) if path else None)
        if r is None:
            missing.append(stage)
        elif not r.get('computed_at') or to_utc_iso(r['computed_at']) > tm.cutoff:
            late.append(r)
        else:
            ok.append(r)
    return ok, late, missing


def _horizon_reading(x, threshold):
    """Wording of one horizon from validation_status()['tests'] (the production criterion decides)."""
    ic, p = _num(x.get('cross_sectional_ic')), _num(x.get('p_value'))
    if ic is None or p is None:
        return f'IC {ic}, p not available: not assessed'
    head = f'IC {ic:+.4f}, p {p}'
    if x.get('significant_after_correction'):
        return f'{head} < {threshold:.4f}: positive and significant after correction'
    if p < threshold and ic < 0:
        return f'{head} < {threshold:.4f}: significantly NEGATIVE after correction (adverse ranking)'
    if p < threshold:
        return f'{head} < {threshold:.4f} but IC not positive: criterion not met'
    return f'{head} >= {threshold:.4f}: not significant after correction'


def validation_text(validation, wf):
    """
    What the walk-forward run admissible at the cutoff found, citing it (computed_at, numbers), or what
    is missing. Never "not significant" unless the corrected p-value says so; the status is stated as is.
    """
    status = validation['status']
    if wf.get('status') != 'OK':
        return (f"no walk-forward validation run is admissible at the cutoff ({wf.get('reason') or 'no results'}): "
                f'validation status {status}')
    tests = validation.get('tests') or {}
    if not tests:
        return (f"the walk-forward run computed {wf.get('computed_at')} reports no tested horizon: validation status "
                f'{status}')
    threshold = VALIDATION_ALPHA / len(tests)
    text = (f"the walk-forward run computed {wf.get('computed_at')} (ex-news combined score, cross-sectional IC over "
            f"the validation universe; required p < {threshold:.4f} = {VALIDATION_ALPHA} / {len(tests)} horizons, IC > 0) "
            'found ' + '; '.join(f'{h} {_horizon_reading(x, threshold)}' for h, x in tests.items()))
    if wf.get('stale'):
        text += (f'; the run is stale at the cutoff (computed more than {STALE_AFTER_DAYS} days before it), so it '
                 'cannot demonstrate validity whatever its p-values')
    return text + f': validation status {status}'


def _validation(ctx, res, wf_path, research_paths):
    tm = ctx.tm
    path = Path(wf_path) if wf_path else None
    wf_c = latest_summary(path, now=tm.cutoff)
    wf_g = latest_summary(path, now=tm.generated_at)
    research, late, missing = _admissible_research(tm, research_paths)
    v = validation_status(wf_c, research)
    admissible = wf_c.get('status') == 'OK'
    items = []
    if admissible:
        items.append(evidence(tm, SYSTEM_SOURCE, None,
                              f"walk-forward run (reports/walk_forward.json) computed {wf_c['computed_at']}: "
                              f"{wf_c['n_tickers']} tickers, components {', '.join(wf_c['validated_components'])}, "
                              f"validation {v['status']}; {validation_text(v, wf_c)}",
                              as_of=wf_c['computed_at'][:10], published_at=wf_c['computed_at'],
                              fresh=not wf_c.get('stale'), basis='computed_at of the run'))
    for r in research:
        items.append(evidence(tm, SYSTEM_SOURCE, None,
                              f"research stage {r['stage']} computed {r['computed_at']}: {r['n_significant_bh']} of "
                              f"{r['n_tests']} tests significant after BH", as_of=r['computed_at'][:10],
                              published_at=r['computed_at'], basis='computed_at of the results file'))
    extra = []
    if 2 in missing:
        extra.append('Stage 2 holdout results: DATA UNAVAILABLE (no results file).')
    elif any(r['stage'] == 2 for r in late):
        extra.append('Stage 2 holdout results: DATA UNAVAILABLE at this cutoff (computed after it).')
    head = v['statement'].strip()
    statement = ' '.join([head if head.endswith('.') else head + '.'] + extra)
    record = conclude('overall', 11, statement, items, 'system_output')
    record['banner'] = True
    res.add(record)

    # per-horizon table (the run admissible at T_c, plus the run visible at G when it differs)
    rows = []
    runs = [('at T_c', wf_c)]
    if wf_g.get('status') == 'OK' and (not admissible or wf_g.get('computed_at') != wf_c.get('computed_at')):
        runs.append(('computed after the cutoff (information only, not used in any conclusion)', wf_g))
    k_tests = None
    for tag, wf in runs:
        if wf.get('status') != 'OK':
            rows.append([tag, wf.get('computed_at'), None, None, None, None, None, None, None, None,
                         wf.get('reason')])
            continue
        hs = wf.get('horizons') or {}
        k_tests = len(hs)
        for h, d in hs.items():
            ic = _num((d.get('ic_cross_sectional') or {}).get('combined'))
            t_stat = _num((d.get('ic_cross_sectional_t') or {}).get('combined'))
            p = None if t_stat is None else round(two_sided_p(t_stat), 4)     # as validation_status
            ci = None
            if ic is not None and t_stat:
                se = abs(ic / t_stat)
                ci = f'[{ic - CI_Z * se:+.4f}, {ic + CI_Z * se:+.4f}]'
            threshold = VALIDATION_ALPHA / len(hs)
            below = None if p is None else p < threshold
            met = bool(below) and ic is not None and ic > 0
            rows.append([tag, wf.get('computed_at'), h, ic, t_stat, p, round(threshold, 4),
                         None if below is None else 'yes' if below else 'no', 'yes' if met else 'no', ci,
                         d.get('folds_with_positive_ic'),
                         f"fitted model out-of-sample IC {d.get('model_oos_ic')}; stale at that instant: "
                         f"{wf.get('stale')}" + ('; significantly NEGATIVE IC (adverse)' if below and ic is not None
                                                 and ic < 0 else '')])
    res.table('Walk-forward validation of the ex-news combined score (cross-sectional IC)',
              ['run', 'computed_at', 'horizon', 'cross-sectional IC', 't', 'two-sided p', 'required p (0.05 / k)',
               'p < required p', 'criterion met (IC > 0 and p < required p)',
               'approx. 95% interval (IC +/- 1.96 IC/t)', 'folds with positive IC (pooled)', 'note'], rows,
              question=11,
              note=('Validation = cross-sectional rank IC of the combined score WITHOUT news over the validation '
                    'universe (not per company). p is the production two-sided p rounded to 4 decimals and compared '
                    'strictly with 0.05 / k, as in validation_status (no tolerance: the criterion is pre-declared). '
                    'A significant NEGATIVE IC does not meet the criterion and is flagged as adverse. DEMONSTRATED '
                    'also requires a run that is not stale at the cutoff. The interval is a normal approximation '
                    'from the reported t; "not significant" does not mean "zero". A run computed after the cutoff '
                    'is not admissible at T_c.'))
    rr = [[f"research stage {r['stage']}", r['computed_at'], 'admissible', r['n_stocks'], r['n_tests'],
           r['n_significant_bh'], r['n_significant_bonferroni']] for r in research]
    rr += [[f"research stage {r['stage']}", r['computed_at'], 'computed after the cutoff: not used', r['n_stocks'],
            r['n_tests'], r['n_significant_bh'], r['n_significant_bonferroni']] for r in late]
    rr += [[f'research stage {s}', None, 'no results file', None, None, None, None] for s in missing]
    res.table('Separate research studies (not the live heuristic)', ['study', 'computed_at', 'status at T_c',
                                                                     'stocks', 'tests', 'significant (BH)',
                                                                     'significant (Bonferroni)'],
              rr, question=11, note='The research studies tested candidate factors and models, not the live '
                                     'heuristic or its weights.')
    if not admissible:
        res.add(unavailable('overall', 11, 'walk-forward validation run admissible at the cutoff',
                            wf_c.get('reason') or 'no walk-forward results'))
    for r in late:
        res.add(unavailable('overall', 11, f"research stage {r['stage']} results at the cutoff",
                            f"results file computed {r['computed_at']}, after the cutoff {tm.cutoff}"))
    for s in missing:
        res.add(unavailable('overall', 11, f'research stage {s} results',
                            f'no results file reports/research_stage{s}.json'
                            + (' (stage 2 holdout not run yet)' if s == 2 else '')))
    if admissible:
        for h, d in (wf_c.get('horizons') or {}).items():
            ic = _num((d.get('ic_cross_sectional') or {}).get('combined'))
            t_stat = _num((d.get('ic_cross_sectional_t') or {}).get('combined'))
            if ic is None or not t_stat:
                continue
            se = abs(ic / t_stat)
            lo, hi = ic - CI_Z * se, ic + CI_Z * se
            reading = ('which includes zero as well as small positive and negative values: "not significant" is '
                       'not "no effect", and the test has limited power' if lo <= 0 <= hi
                       else 'which excludes zero (approximation; the pre-declared criterion is the corrected p-value)')
            res.add(conclude('overall', 11, f"At {h}, in the walk-forward run computed {wf_c['computed_at']} (IC "
                                            f'{ic:+.4f}, t {t_stat:+.2f}), the approximate 95% interval of the ex-news '
                                            f'cross-sectional IC (IC +/- 1.96 IC/t) is [{lo:+.4f}, {hi:+.4f}], '
                                            f'{reading}.', items[:1], 'interpretation'))
    res.add(unavailable('overall', 11, 'per-company signal reliability',
                        'the walk-forward validation is cross-sectional over the validation universe (ranking tickers '
                        'against each other); no per-company validation exists'))
    res.add(unavailable('overall', 11, 'prospective record of weekly signals and realized outcomes',
                        'insufficient sample: no archived weekly signal with a realized outcome is evaluated yet; the '
                        'pre-declared minimum is >= 52 weekly reports over a universe of >= 10 tickers (the report '
                        'covers the configured universe only)'))
    for field, info in not_implemented_fields().items():
        res.add(unavailable('overall', 11, field, f"{info['status']}: {info['reason']}"))
    return v, wf_c, (items[0] if admissible else None)


# ---------------------------------------------------------------- per company

def _signal_rows(sig, label_name, now, before, thr_c, dist_c, band):
    flag = is_borderline(dist_c, band)
    border = None if flag is None else 'yes' if flag else 'no'
    delta = None if now['score'] is None or before['score'] is None else round(now['score'] - before['score'], 2)
    return [label_name, before['score'], before['label'], f"{len(before['available'])}/{before['n']}",
            now['score'], now['label'], f"{len(now['available'])}/{now['n']}", delta, thr_c, _r(dist_c), border]


def _uncited(comps, comb):
    """Components used by a combined score that carry no evidence item (publication instant not established)."""
    return [k for k in comb['available'] if not comps[k].get('evidence')]


def _company(ctx, res, t, daily, daily_problem, validation, band, wf_c=None, wf_item=None):
    tm = ctx.tm
    wf_c = wf_c or {}
    sig = ScoringSignalFixed()
    s0, s_m5 = tm.s0, tm.sessions[-6]
    c = {'technical': _safe(technical, 'technical', ctx, t, s0, tm.cutoff),
         'fundamentals': _safe(fundamentals, 'fundamentals', ctx, t, tm.cutoff),
         'insider': _safe(insider, 'insider', ctx, t, tm.cutoff),
         'news': _safe(news, 'news', ctx, t, daily, daily_problem)}
    p = {'technical': _safe(technical, 'technical', ctx, t, s_m5, tm.previous_cutoff),
         'fundamentals': _safe(fundamentals, 'fundamentals', ctx, t, tm.previous_cutoff),
         'insider': _safe(insider, 'insider', ctx, t, tm.previous_cutoff),
         'news': _comp('news', reason='news is not recomputed at T_p: no daily run computed at or before T_p is '
                                      'archived (analysis.json holds the latest run only)')}
    ex_c, ex_p = combine(sig, c, EX_NEWS), combine(sig, p, EX_NEWS)
    live_c, live_p = combine(sig, c, COMPONENTS), combine(sig, p, COMPONENTS)
    thr_ex, dist_ex = nearest_threshold(sig, ex_c['score'])
    thr_live, dist_live = nearest_threshold(sig, live_c['score'])

    res.table(f'{t} — heuristic signal at T_p and T_c (ex-news variant first)',
              ['variant', 'S(T_p)', 'label T_p', 'coverage T_p', 'S(T_c)', 'label T_c', 'coverage T_c',
               'delta S', 'nearest threshold at T_c', 'distance to it (points)',
               'borderline' + (f' (+/- {band})' if band is not None else ' (no pre-declared band)')],
              [_signal_rows(sig, 'ex-news (technical + fundamentals + insider; walk-forward variant)', ex_c, ex_p,
                            thr_ex, dist_ex, band),
               _signal_rows(sig, 'live (4 components, news weight 0.20; never validated)', live_c, live_p,
                            thr_live, dist_live, band)],
              scope=t, question=10,
              note=(f'Production ScoringSignalFixed: weights {sig.WEIGHTS} renormalized over available components '
                    f'(>= {sig.MIN_COMPONENTS}); POSITIVE >= {sig.POSITIVE_THRESHOLD}, NEGATIVE <= '
                    f'{sig.NEGATIVE_THRESHOLD} (heuristic, never fitted). T_p = {tm.previous_cutoff} (closes up to '
                    f'{s_m5}); T_c = {tm.cutoff} (closes up to {s0}). Heuristic 0-100 scores: not probabilities, not '
                    'recommendations.'))

    rows = []
    for k in COMPONENTS:
        cc, pp = c[k], p[k]
        row = [k, sig.WEIGHTS[k], _r(pp['score']), _r(cc['score'])]
        for comb in (ex_p, ex_c) if k in EX_NEWS else ():
            row.append(_r(comb['weights'].get(k), 4))
        if k not in EX_NEWS:
            row += [None, None]
        row += [_r(ex_p['contrib'].get(k), 3) if k in EX_NEWS else None,
                _r(ex_c['contrib'].get(k), 3) if k in EX_NEWS else None,
                _r(live_c['weights'].get(k), 4), _r(live_c['contrib'].get(k), 3),
                cc['as_of'], f"{cc['source']} (rank {cc['rank']})",
                cc['detail'] if cc['score'] is not None else f"T_c unavailable: {cc['reason']}",
                pp['detail'] if pp['score'] is not None else f"T_p unavailable: {pp['reason']}"]
        rows.append(row)
    res.table(f'{t} — components and contributions (renormalized weights)',
              ['component', 'nominal weight', 'score T_p', 'score T_c', 'ex-news weight T_p', 'ex-news weight T_c',
               'ex-news contribution T_p', 'ex-news contribution T_c', 'live weight T_c', 'live contribution T_c',
               'input as of (T_c)', 'source', 'T_c inputs', 'T_p inputs'],
              rows, scope=t, question=10,
              note='contribution = renormalized weight x component score; contributions sum to S (before the '
                   'production rounding to 2 decimals). When S is not computed (INSUFFICIENT DATA: fewer than '
                   f'{sig.MIN_COMPONENTS} components) no weight or contribution is shown. N/A = component unavailable '
                   '(reason in the last columns), never a neutral 50.')

    drows = []
    for name, now, before in (('ex-news', ex_c, ex_p), ('live', live_c, live_p)):
        d = decompose(sig, now, before)
        if d is None:
            drows.append([name, None, None, None, None, 'S unavailable at T_p or T_c (INSUFFICIENT DATA)'])
            continue
        for k in d['common']:
            drows.append([name, f'score effect: {k}', _r(before['scores'][k]), _r(now['scores'][k]),
                          _r(d['effects'][k], 3), f"weight on common set {sig.WEIGHTS[k] / sum(sig.WEIGHTS[x] for x in d['common']):.4f}"])
        drows.append([name, 'coverage effect (components present at one cutoff only)', None, None,
                      _r(d['coverage_effect'], 3),
                      'none' if abs(d['coverage_effect']) < 1e-9 else
                      f"T_p {', '.join(before['available'])} -> T_c {', '.join(now['available'])}"])
        drows.append([name, 'total delta S', _r(before['raw']), _r(now['raw']), _r(d['delta'], 3),
                      'score effect + coverage effect'])
    res.table(f'{t} — delta decomposition S(T_c) - S(T_p)', ['variant', 'term', 'T_p', 'T_c', 'effect (points)',
                                                             'detail'], drows, scope=t, question=10)

    # conclusions (Q10)
    status = validation['status']
    for name, now, before, thr, dist, ncomp in (
            ('ex-news variant (technical + fundamentals + insider, the variant the walk-forward evaluated)',
             ex_c, ex_p, thr_ex, dist_ex, 3),
            ('live variant (technical, fundamentals, news, insider; news never validated)', live_c, live_p,
             thr_live, dist_live, 4)):
        short = 'ex-news' if ncomp == 3 else 'live'
        if now['score'] is None:
            res.add(unavailable(t, 10, f'{short} heuristic signal at T_c',
                                f"INSUFFICIENT DATA: {len(now['available'])} of {ncomp} components available (at least "
                                f"{sig.MIN_COMPONENTS} required); missing: "
                                + '; '.join(f"{k}: {c[k]['reason']}" for k in now['missing'])))
            continue
        items = _items({k: c[k] for k in now['available']}, {k: p[k] for k in before['available']})
        parts = [f"{t}: the heuristic {name} outputs {now['score']:.2f} ({now['label']}) at T_c with coverage "
                 f"{len(now['available'])}/{ncomp}"
                 + (f" (missing: {', '.join(now['missing'])})" if now['missing'] else '')]
        if before['score'] is not None:
            parts.append(f"at T_p it output {before['score']:.2f} ({before['label']}, coverage "
                         f"{len(before['available'])}/{ncomp}); change {now['score'] - before['score']:+.2f} points"
                         + ('; label unchanged' if now['label'] == before['label']
                            else f"; label changed {before['label']} -> {now['label']}"))
        else:
            parts.append(f"S(T_p) unavailable ({len(before['available'])}/{ncomp} components)")
        if short == 'live' and 'news' in now['missing']:
            parts.append('identical to the ex-news variant (news unavailable at T_c)')
        parts.append(f'nearest threshold {thr} at {dist:+.2f} points')
        codes = ['PARTIAL_COVERAGE'] if (now['missing'] or before['missing']) else []
        uncited = _uncited(c, now) + ([f'{k} at T_p' for k in _uncited(p, before)] if before['score'] is not None
                                      else [])
        if uncited:
            codes.append('TIMESTAMP_AMBIGUOUS')
            parts.append(f"publication instant of the inputs not established for {', '.join(uncited)}")
        res.add(conclude(t, 10, '; '.join(parts) + '. This describes the system\'s output, not the stock.', items,
                         'system_output', reason_codes=codes,
                         resolve='all components available at both cutoffs, with established publication '
                                 'instants' if codes else None))
        if short == 'ex-news' and items:
            border = f' (borderline: within +/- {band} points)' if is_borderline(dist, band) else ''
            head = (f"{t}: read as information about future returns, the ex-news label {now['label']} at T_c "
                    f"(S {now['score']:.2f}, {dist:+.2f} points from the {thr} threshold{border})")
            found = validation_text(validation, wf_c)
            if status == 'DEMONSTRATED':
                body = (f'rests only on past cross-sectional ranking skill: {found}. That skill is the ex-news score '
                        'ranking the validation universe: it is not a per-company validation and not a validation '
                        'of this label threshold, and past skill does not guarantee future skill')
            else:
                body = f'has no demonstrated predictive value: {found}'
            res.add(conclude(t, 10, f'{head} {body}. It is not a probability and not a recommendation.',
                             items + ([wf_item] if wf_item else []), 'model_output',
                             reason_codes=['HEURISTIC_THRESHOLD'] + (['TIMESTAMP_AMBIGUOUS'] if uncited else []),
                             validation_demonstrated=status == 'DEMONSTRATED'))
    return {'ticker': t, 'ex_c': ex_c, 'ex_p': ex_p, 'live_c': live_c, 'c': c}


def _reliability(ctx, res, info):
    t, c = info['ticker'], info['c']
    rows, parts = [], []
    for k in COMPONENTS:
        comp = c[k]
        fr = (ctx.freshness(comp['as_of'], CADENCES[k]) if comp['as_of'] else
              {'status': 'UNKNOWN', 'age_days': None, 'max_age_days': None})
        avail = comp['score'] is not None
        rows.append([k, 'yes' if avail else 'no', comp['source'], comp['rank'], comp['as_of'], fr.get('status'),
                     fr.get('age_days'), fr.get('max_age_days'),
                     ('PROVISIONAL: naive lexicon, never validated' if k == 'news' and avail else None)
                     if avail else comp['reason']])
        parts.append(f"{k} {'available' if avail else 'unavailable'}"
                     + (f" ({comp['source']} rank {comp['rank']}, {fr.get('status')})" if avail else ''))
    res.table(f'{t} — data reliability of the signal inputs at T_c (not signal validity)',
              ['component', 'available', 'source', 'rank', 'as of', 'freshness at T_c', 'age (days)',
               'max age (days)', 'note'], rows, scope=t, question=11,
              note='Data reliability (coverage, freshness evaluated at the cutoff, source rank) is a property of the '
                   'inputs; it says nothing about whether the signal predicts returns (see the validation table).')
    n = sum(1 for k in COMPONENTS if c[k]['score'] is not None)
    items = _items({k: c[k] for k in COMPONENTS})
    res.add(conclude(t, 11, f'{t}: data reliability at T_c (inputs, not signal validity): {n}/4 components available; '
                            + '; '.join(parts) + '.', items, 'system_output',
                     reason_codes=['PARTIAL_COVERAGE'] if n < 4 else [],
                     resolve='all four inputs available and fresh at the cutoff' if n < 4 else None))


# ---------------------------------------------------------------- section

def build(ctx, analysis_path=None, walk_forward_path=None, research_paths=None, tickers=None):
    """
    analysis_path / walk_forward_path / research_paths ({stage: path}): result files (default: the
    reports directory). Nothing is downloaded by this section.
    """
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    band = _borderline(ctx)
    version = (getattr(ctx, 'weekly', None) or {}).get('thresholds_version')
    validation, wf_c, wf_item = _validation(ctx, res, walk_forward_path, research_paths)
    found = validation_text(validation, wf_c)
    daily, daily_problem = load_daily_run(analysis_path)
    universe = list(tickers or ctx.universe)
    infos = [_company(ctx, res, t, daily, daily_problem, validation, band, wf_c, wf_item) for t in universe]
    for info in infos:
        _reliability(ctx, res, info)

    # overall: label distribution and cross-sectional ranks (ex-news first)
    scored = sorted((i for i in infos if i['ex_c']['score'] is not None), key=lambda i: -i['ex_c']['score'])
    rank = {i['ticker']: n for n, i in enumerate(scored, 1)}
    rows = [[i['ticker'], i['ex_c']['score'], i['ex_c']['label'], rank.get(i['ticker']), i['ex_p']['score'],
             i['ex_p']['label'], i['live_c']['score'], i['live_c']['label'],
             f"{len(i['live_c']['available'])}/4"] for i in infos]
    res.table('Universe — heuristic signal at T_c (ex-news first)',
              ['ticker', 'S ex-news (T_c)', 'label ex-news (T_c)', 'rank ex-news (1 = highest)', 'S ex-news (T_p)',
               'label ex-news (T_p)', 'S live (T_c)', 'label live (T_c)', 'coverage live (T_c)'], rows, question=10,
              note=(f'Thresholds {version}; borderline band '
                    + (f'+/- {band} points (|S - threshold| <= band, tolerance {BORDERLINE_TOL:g})'
                       if band is not None else 'not pre-declared (config weekly.thresholds has no '
                                                'signal_borderline_points): not assessed')
                    + f'. Ranks describe the heuristic only; at the cutoff {found} (see Q11).'))
    labels = {}
    for i in infos:
        labels[i['ex_c']['label']] = labels.get(i['ex_c']['label'], 0) + 1
    dist = ', '.join(f'{labels.get(k, 0)} {k}' for k in ('POSITIVE', 'NEUTRAL', 'NEGATIVE', 'INSUFFICIENT DATA'))
    # weakest premise: the universe summary carries every ticker's T_c ex-news evidence and the walk-forward
    # run it cites, so a stale input, a partial coverage or a stale run caps it like the per-ticker conclusions
    items = [e for i in infos for e in _items({k: i['c'][k] for k in i['ex_c']['available']})]
    items += [wf_item] if wf_item else []
    partial = [i['ticker'] for i in infos if i['ex_c']['missing']]
    uncited = [f"{i['ticker']} {k}" for i in infos for k in _uncited(i['c'], i['ex_c'])]
    codes = (['PARTIAL_COVERAGE'] if partial else []) + (['TIMESTAMP_AMBIGUOUS'] if uncited else [])
    extra = ((f"; ex-news components missing at T_c for {', '.join(partial)}" if partial else '')
             + (f"; publication instant not established for {', '.join(uncited)}" if uncited else ''))
    res.add(conclude('overall', 10, f'Ex-news heuristic labels at T_c over the {len(infos)}-ticker universe: {dist}'
                                    f'{extra}; {found}. A statement about the system\'s outputs.', items,
                     'system_output', reason_codes=codes,
                     resolve='all ex-news components available for every ticker, fresh at the cutoff, and a '
                             'walk-forward run that is not stale' if codes else None))
    res.notes.append(f"{validation['statement'].strip()} {NOT_A_RECOMMENDATION}")
    res.notes.append(f'T_c {tm.cutoff} (closes up to {tm.s0}); T_p {tm.previous_cutoff} (closes up to '
                     f'{tm.sessions[-6]}); thresholds {version}. News enters only at T_c and only from a daily run '
                     'computed at or before the cutoff; the technical score uses the last 150 adjusted closes (the '
                     'walk-forward convention; the daily run uses a 180-calendar-day window, so its number can differ '
                     'slightly). Scores are never converted into probabilities.')
    return res
