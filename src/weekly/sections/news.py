#!/usr/bin/env python3
"""
Weekly report section 'news' - Q4 "What changed geopolitically?" and news complement of Q1
(phase P3.0). NewsAPI /v2/everything is an AGGREGATOR (rank 3): every news-based conclusion is
kind 'aggregator' (UNCERTAIN by rule) whatever the number of copies or outlets; news alone never
establishes that an event happened.

Queries (window from = T_p, to = T_c; language en; sortBy relevancy; pageSize 100)
  (a) ONE global geopolitical query over the pre-declared topic list GEO_TOPICS (TOPICS_VERSION)
      -> Q4, scope 'overall';
  (b) one query per company (ctx.universe or the `tickers` subset): the configured company name
      ctx.company(t), quoted -> Q1, scope t. A ticker without a configured name is not queried
      (a bare ticker such as NET or MP is ambiguous).
  Free plan facts: at most 100 results per query (pagination beyond 100 returns HTTP 426), results
  end ~24 h before retrieval (ctx.tm.news_complete() says whether the window can be complete), a
  ~1 month history and 100 requests per day shared with the daily batch. Selection inside the 100
  results follows NewsAPI's relevancy ranking (opaque). Coverage = returned / totalResults
  (PARTIAL_COVERAGE when < 1 or when the window is not complete) and the publishedAt span returned
  are recorded for every query.
  Every call is logged with ctx.db.record_fetch(source='NewsAPI') with its raw payload; the key is
  sent in the X-Api-Key header and never stored or printed. An identical request already stored
  is reused instead of spending budget: when the report is generated after T_c + 26 h, only a
  fetch retrieved after that instant (complete window); before, a fetch at most 12 h old.

Processing (pre-declared)
  - publishedAt must be in (T_p, T_c] (anything after the cutoff is excluded and counted);
  - drop code / package hosts (CODE_HOSTS);
  - relevance: the query term (topic stem, or the company name) must appear in title or description;
  - de-duplicate on canonical URL (scheme, www., query and fragment removed; the query is kept only
    for script endpoints such as firehose.pl?id=..., where it identifies the document) and on the
    normalized title (lower case, punctuation removed, trailing ' - <outlet>' removed): duplicates
    and syndicated copies are counted ONCE and listed as copies. A canonical-URL match counts as a
    duplicate only when the titles also match (identical or token-set Jaccard >= JACCARD_MIN):
    pages identified by their query alone (consent walls, item?id=...) share one canonical URL. The
    title of a URL duplicate is registered too, so a later copy of an updated headline is matched.
    Topic membership stays per original article: a copy never lends its topics to the article it
    was folded into; topic evidence cites the article (or copy) whose own title / description
    matched. An identical generic headline from two outlets is folded as a copy (outlet counts
    conservative);
  - cluster near-duplicate titles: leader clustering in publishedAt order, token-set Jaccard >=
    JACCARD_MIN with the cluster's first title.
  Tables list EVERY cluster and every topic (no selection on what is 'interesting'); conclusions:
  one per topic with articles (Q4) or per company (Q1); one per global story cluster reported by at
  least STORY_MIN_OUTLETS distinct outlets (at most MAX_STORY_CONCLUSIONS); one per company story
  cluster ('reported by N outlet(s) (aggregator)' with its outlets and publishedAt; at most
  MAX_COMPANY_STORY_CONCLUSIONS per company); order: most outlets first, then earliest. Headlines are
  quoted verbatim, never adopted; a headline containing causal or move-attribution wording (a move
  verb followed by as / on / after / amid / following, or 'N% on / after ...') is listed in the
  table only (keyword list: a wording outside it can still be quoted). Relevance is a keyword
  match: off-topic matches (e.g. sports 'sanctions') are possible and are not removed by hand; the
  simple title clustering can split one story written with different words (outlet counts are
  then conservative).
Sections never call the wall clock, never write files themselves (fetch logging goes through
ctx.db) and never download outside this documented NewsAPI call.
"""

import html
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit

import requests
from dotenv import load_dotenv

from ...common import DATA_UNAVAILABLE, redact, secret_env, to_utc_iso
from ...database import source_rank
from ..core import NEWS_DELAY_HOURS, SectionResult, conclude, evidence, unavailable

load_dotenv()

NAME = 'news'
QUESTIONS = [4, 1]
Q_GEO, Q_COMPANY = 4, 1

NEWS_URL = 'https://newsapi.org/v2/everything'
DB_SOURCE = 'NewsAPI'
RANK = source_rank(DB_SOURCE)
PAGE_SIZE = 100
SORT_BY = 'relevancy'
LANGUAGE = 'en'
TIMEOUT = 15
REUSE_MAX_AGE = timedelta(hours=12)
BASIS = 'NewsAPI publishedAt (an aggregator re-post time can be later than the original publication)'

TOPICS_VERSION = 'geo-topics-v1-2026-10-07'
# (label, query term, stems matched at a word start in title / description)
GEO_TOPICS = (
    ('sanctions', 'sanctions', ('sanction',)),
    ('export controls', '"export controls"', ('export control',)),
    ('tariffs', 'tariffs', ('tariff',)),
    ('armed conflict', '"armed conflict"', ('armed conflict',)),
    ('elections', 'elections', ('election',)),
    ('government shutdown', '"government shutdown"', ('government shutdown',)),
)
GEO_QUERY = ' OR '.join(term for _, term, _ in GEO_TOPICS)
CODE_HOSTS = ('pypi.org', 'github.com')
SCRIPT_SUFFIXES = ('.pl', '.php', '.asp', '.aspx', '.cgi', '.jsp')
JACCARD_MIN = 0.6
STORY_MIN_OUTLETS = 2           # global (Q4) story conclusions: clusters reported by >= 2 outlets
MAX_STORY_CONCLUSIONS = 10      # ... at most 10, most outlets first
COMPANY_STORY_MIN_OUTLETS = 1   # company (Q1) story conclusions: every cluster ...
MAX_COMPANY_STORY_CONCLUSIONS = 20   # ... at most 20 per company, most outlets first, then earliest

CAUSAL_WORDING = re.compile(
    r'\b(because|due to|driven by|drove|caus(e|es|ed|ing)|trigger(s|ed)?|spark(s|ed)?|fuel(l)?ed|'
    r'on the back of|thanks to|in response to|as a result|sen(d|ds|t) shares|boost(s|ed|ing)?|lift(s|ed|ing)?|'
    r'push(es|ed|ing)?|spur(s|red|ring)?|weigh(s|ed|ing)? on|hurt(s|ing)?|prompt(s|ed|ing)?|led by|lead(s)? to|'
    r'propel(s|led|ling)?|dragg?(ed|ing|s)? down)\b', re.IGNORECASE)
MOVE_VERBS = (
    r'falls?|fell|falling|drops?|dropped|dropping|slips?|slipped|slipping|sinks?|sank|sinking|slides?|slid|'
    r'sliding|tumbles?|tumbled|tumbling|plunges?|plunged|plunging|jumps?|jumped|jumping|soars?|soared|soaring|'
    r'surges?|surged|surging|rises?|rose|rising|climbs?|climbed|climbing|gains?|gained|gaining|'
    r'rall(y|ies|ied|ying)|spikes?|spiked|eases?|eased|nudges?|nudged|ticks?|ticked|sheds?|shedding|pops?|'
    r'popped|slumps?|slumped|advanc(e|es|ed|ing)|edg(e|es|ed|ing)\s+(up|down|higher|lower)|'
    r'declin(e|es|ed|ing)|dips?|dipped|dipping|rebound(s|ed|ing)?|retreat(s|ed|ing)?|adds?|added|adding|'
    r'loses?|lost|losing|sto(ck|cks) (up|down)|(trades?|trading|ends?|ended|closes?|closed|is|are|was|were) '
    r'(up|down|higher|lower)')
MOVE_CONNECTORS = r'as|on|after|amid|following'
MOVE_ATTRIBUTION = re.compile(
    r'\b(' + MOVE_VERBS + r')\b.*\b(' + MOVE_CONNECTORS + r')\b'
    r'|\d+(\.\d+)?\s*%(\s+(higher|lower|up|down))?\s+(' + MOVE_CONNECTORS + r')\b', re.IGNORECASE)
NOT_ESTABLISHED = ('aggregator only, not confirmed by a primary document: that any reported event happened '
                   'is not established by news alone')


# ---------------------------------------------------------------- small helpers

def _clean(text):
    return html.unescape(text or '').strip()


def fresh_flag(ctx, as_of, cadence):
    if as_of is None:
        return None
    status = (ctx.freshness(str(as_of)[:10], cadence) or {}).get('status')
    return True if status == 'FRESH' else False if status == 'STALE' else None


def thresholds_version(ctx):
    return (getattr(ctx, 'weekly', None) or {}).get('thresholds_version')


def canonical_url(url):
    """host + path without scheme, 'www.', trailing '/', query and fragment (query kept for scripts)."""
    parts = urlsplit(_clean(url))
    host = (parts.hostname or '').lower()
    host = host[4:] if host.startswith('www.') else host
    path = parts.path.rstrip('/')
    keep_query = parts.query and (not path or path.lower().endswith(SCRIPT_SUFFIXES))
    query = '&'.join(sorted(parts.query.split('&'))) if keep_query else ''
    return host + path + (f'?{query}' if query else '') if host or path else None


def normalized_title(title, outlet=None):
    t = _clean(title).lower()
    o = _clean(outlet).lower()
    for sep in (' - ', ' | ', ' — ', ' – '):
        if o and t.endswith(sep + o):
            t = t[:-len(sep + o)]
    return re.sub(r'[\W_]+', ' ', t).strip()


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def similar_titles(t1, t2):
    """Normalized titles identical or token-set Jaccard >= JACCARD_MIN."""
    return t1 == t2 or jaccard(set(t1.split()), set(t2.split())) >= JACCARD_MIN


def members(a):
    """The article and the duplicate / syndicated copies folded into it."""
    return [a] + a.get('copies', [])


def topic_member(a, label):
    """First of the article and its copies whose OWN title / description matched `label` (None if none)."""
    return next((m for m in members(a) if label in m['topics']), None)


def code_host(url, outlet):
    host = (urlsplit(_clean(url)).hostname or '').lower()
    name = _clean(outlet).lower()
    return any(host == h or host.endswith('.' + h) or name == h for h in CODE_HOSTS)


def quotable(title):
    return not (CAUSAL_WORDING.search(title or '') or MOVE_ATTRIBUTION.search(title or ''))


def headline_ref(title):
    if quotable(title):
        return f'headline (verbatim, unverified) "{title}"'
    return ('headline not quoted in this statement (it contains causal or move-attribution wording; it is listed '
            'verbatim in the table and not adopted)')


def coverage(returned, total):
    return None if not total else returned / total


def fmt_cov(cov):
    return 'N/A' if cov is None else f'{100 * cov:.1f}%'


# ---------------------------------------------------------------- NewsAPI call (logged, reusable)

def request_params(tm, q):
    return {'q': q, 'from': to_utc_iso(tm.previous_cutoff)[:19], 'to': to_utc_iso(tm.cutoff)[:19],
            'language': LANGUAGE, 'sortBy': SORT_BY, 'pageSize': PAGE_SIZE, 'page': 1}


def endpoint_for(params):
    """Fetch-log endpoint: the URL with the (key-free) parameters, so identical requests can be reused."""
    return NEWS_URL + '?' + urlencode(sorted(params.items()))


def _reuse_since(tm):
    complete_at = datetime.fromisoformat(tm.cutoff) + timedelta(hours=NEWS_DELAY_HOURS)
    generated = datetime.fromisoformat(tm.generated_at)
    if generated >= complete_at:
        return complete_at
    return max(generated - REUSE_MAX_AGE, datetime.fromisoformat(tm.cutoff))


def fetch_query(ctx, q, http_get=None):
    """
    {'status', 'payload', 'fetch', 'reason', 'reused', 'params', 'requested'}; one logged NewsAPI
    request at most (none when an identical stored request is reusable or the key is unusable).
    """
    params = request_params(ctx.tm, q)
    endpoint = endpoint_for(params)
    out = {'status': DATA_UNAVAILABLE, 'payload': None, 'fetch': None, 'reason': None, 'reused': False,
           'params': params, 'requested': False}
    db = ctx.db
    if hasattr(db, 'latest_fetch') and hasattr(db, 'read_raw'):
        stored = db.latest_fetch(DB_SOURCE, endpoint, since=_reuse_since(ctx.tm))
        if stored:
            try:
                payload = json.loads(db.read_raw(stored['fetch_id']))
                if isinstance(payload, dict) and payload.get('status') == 'ok':
                    return dict(out, status='OK', payload=payload, fetch=stored, reused=True)
            except (RuntimeError, ValueError, TypeError, OSError):
                pass                                   # unreadable stored payload: request again
    key, problem = secret_env('NEWSAPI_KEY')
    if problem:
        return dict(out, reason=f'{problem}: no NewsAPI request made')
    get = http_get or requests.get
    response, data, error = None, None, None
    out['requested'] = True
    try:
        response = get(NEWS_URL, params=params, headers={'X-Api-Key': key}, timeout=TIMEOUT)
        try:
            data = response.json()
        except ValueError:
            data = None
        status = getattr(response, 'status_code', None)
        if status != 200 or not isinstance(data, dict) or data.get('status') != 'ok':
            detail = ''
            if isinstance(data, dict) and (data.get('code') or data.get('message')):
                detail = f' ({data.get("code")}: {str(data.get("message") or "")[:200]})'
            error = f'NewsAPI HTTP {status}{detail}'
    except Exception as e:  # noqa: BLE001 - recorded and surfaced as DATA UNAVAILABLE
        error = f'{type(e).__name__}: {e}'
    http_status = getattr(response, 'status_code', None)
    try:
        if error:
            error = redact(error)
            fetch = db.record_fetch(DB_SOURCE, endpoint, params=params, requested_at=ctx.tm.generated_at,
                                    status=DATA_UNAVAILABLE, error=error, http_status=http_status)
            return dict(out, fetch=fetch, reason=error)
        raw = getattr(response, 'content', None)
        fetch = db.record_fetch(DB_SOURCE, endpoint, params=params, requested_at=ctx.tm.generated_at,
                                status='OK', http_status=http_status, n_records=len(data.get('articles') or []),
                                raw=raw if isinstance(raw, (bytes, str)) else data)
    except Exception as e:  # noqa: BLE001 - an unlogged result is never used
        return dict(out, reason=redact(f'the NewsAPI call could not be logged ({type(e).__name__}: {e}); '
                                       'its result is not used'))
    return dict(out, status='OK', payload=data, fetch=fetch)


# ---------------------------------------------------------------- article processing

def select_articles(tm, payload, terms):
    """
    terms: [(label, stems)]. Returns (unique articles sorted by publishedAt, stats). Each article:
    published_at, title, outlet, url, topics, copies (duplicates / syndicated copies counted once).
    """
    articles = (payload or {}).get('articles') or []
    stats = {'returned': len(articles), 'no_timestamp': 0, 'after_cutoff': 0, 'before_window': 0,
             'code_host': 0, 'not_relevant': 0, 'duplicates': 0}
    published = []
    kept = []
    patterns = [(label, [re.compile(r'\b' + re.escape(s.lower())) for s in stems]) for label, stems in terms]
    for a in articles:
        try:
            pub = to_utc_iso(a.get('publishedAt'))
        except (TypeError, ValueError):
            pub = None
        if pub is None:
            stats['no_timestamp'] += 1
            continue
        published.append(pub)
        if pub > tm.cutoff:
            stats['after_cutoff'] += 1                  # look-ahead: never used
            continue
        if pub <= tm.previous_cutoff:
            stats['before_window'] += 1
            continue
        outlet = _clean((a.get('source') or {}).get('name')) or '(unnamed source)'
        url = _clean(a.get('url')) or None
        if code_host(url, outlet):
            stats['code_host'] += 1
            continue
        title, desc = _clean(a.get('title')), _clean(a.get('description'))
        text = f'{title} {desc}'.lower()
        topics = [label for label, pats in patterns if any(p.search(text) for p in pats)]
        if not topics:
            stats['not_relevant'] += 1
            continue
        kept.append({'published_at': pub, 'title': title or '(untitled)', 'outlet': outlet, 'url': url,
                     'topics': topics, 'copies': []})
    stats['span'] = (min(published), max(published)) if published else (None, None)

    kept.sort(key=lambda x: (x['published_at'], x['url'] or ''))
    unique, by_url, by_title = [], {}, {}
    for a in kept:
        cu = canonical_url(a['url']) if a['url'] else None
        nt = normalized_title(a['title'], a['outlet'])
        a.update(canonical_url=cu, norm_title=nt, tokens=set(nt.split()))
        # same canonical URL is a copy only with a matching title (query-identified pages share one path)
        first = next((u for u in by_url.get(cu, []) if similar_titles(u['norm_title'], nt)), None) if cu else None
        if first is None and nt:
            first = by_title.get(nt)
        if first is not None:
            first['copies'].append(a)                   # topics stay with the copy (never merged)
            stats['duplicates'] += 1
            if cu and all(u is not first for u in by_url.get(cu, [])):
                by_url.setdefault(cu, []).append(first)
            if nt:
                by_title.setdefault(nt, first)          # a later copy of this (updated) headline is matched
            continue
        unique.append(a)
        if cu:
            by_url.setdefault(cu, []).append(a)
        if nt:
            by_title.setdefault(nt, a)
    stats['kept'] = len(unique)
    return unique, stats


def _topic_order(label):
    labels = [t[0] for t in GEO_TOPICS]
    return (labels.index(label) if label in labels else len(labels), label)


def cluster(unique, prefix):
    """Leader clustering (publishedAt order) on token-set Jaccard >= JACCARD_MIN with the first title."""
    clusters = []
    for a in unique:
        for c in clusters:
            if jaccard(a['tokens'], c['articles'][0]['tokens']) >= JACCARD_MIN:
                c['articles'].append(a)
                break
        else:
            clusters.append({'articles': [a]})
    for i, c in enumerate(clusters, 1):
        arts = c['articles']
        outlets = {}
        for x in arts:
            outlets.setdefault(x['outlet'].lower(), x['outlet'])
        c['id'] = f'{prefix}{i}'
        c['lead'] = arts[0]
        c['outlets'] = sorted(outlets.values(), key=str.lower)
        c['first'] = min(x['published_at'] for x in arts)
        c['last'] = max(x['published_at'] for x in arts)
        c['topics'] = sorted({t for x in arts for m in members(x) for t in m['topics']}, key=_topic_order)
        c['copies'] = [cp for x in arts for cp in x['copies']]
    return clusters


def article_evidence(ctx, a, fetch):
    fetch = fetch or {}
    return evidence(ctx.tm, DB_SOURCE, RANK, f'{a["outlet"]}: "{a["title"]}" ({a["url"]})',
                    as_of=a['published_at'][:10], published_at=a['published_at'],
                    retrieved_at=fetch.get('retrieved_at'), fetch_id=fetch.get('fetch_id'),
                    fresh=fresh_flag(ctx, a['published_at'][:10], 'news'), basis=BASIS)


def _cluster_rows(clusters, with_topics):
    rows = []
    for c in clusters:
        copies = c['copies']
        row = [c['id'], c['first'], c['last'], c['lead']['title'], len(c['outlets']), ', '.join(c['outlets']),
               len(c['articles']),
               (f'{len(copies)} ({", ".join(sorted({cp["outlet"] for cp in copies}, key=str.lower))})'
                if copies else 0),
               ' | '.join(f'{x["published_at"]} {x["outlet"]}: {x["title"]}' for x in c['articles'][1:]) or None]
        if with_topics:
            row.append(', '.join(c['topics']))
        rows.append(row)
    return rows


CLUSTER_COLUMNS = ['story', 'first publishedAt', 'last publishedAt', 'headline of the first article (verbatim, '
                   'unverified)', 'distinct outlets', 'outlets', 'articles', 'duplicate / syndicated copies '
                   'counted once (outlets)', 'other articles in the cluster (publishedAt outlet: title)']
COVERAGE_COLUMNS = ['scope', 'query', 'from (T_p)', 'to (T_c)', 'sortBy', 'returned', 'totalResults', 'coverage',
                    'first publishedAt returned', 'last publishedAt returned', 'after the cutoff (excluded)',
                    'before the window', 'code hosts dropped', 'not relevant', 'duplicates', 'kept', 'story clusters',
                    'fetch id', 'retrieved at', 'reused stored fetch']


def _coverage_row(scope, got, stats, n_clusters):
    p, fetch = got['params'], got.get('fetch') or {}
    total = (got.get('payload') or {}).get('totalResults')
    return [scope, p['q'], p['from'], p['to'], p['sortBy'], stats['returned'], total,
            fmt_cov(coverage(stats['returned'], total)), stats['span'][0], stats['span'][1], stats['after_cutoff'],
            stats['before_window'], stats['code_host'], stats['not_relevant'], stats['duplicates'], stats['kept'],
            n_clusters, fetch.get('fetch_id'), fetch.get('retrieved_at'), 'yes' if got.get('reused') else 'no']


def _partial_codes(ctx, stats, total):
    partial = (not ctx.tm.news_complete()) or total is None or stats['returned'] < total
    return ['PARTIAL_COVERAGE'] if partial else []


def _story_conclusions(ctx, res, scope, question, label, clusters, fetch, codes, min_outlets, limit):
    """One conclusion per cluster with >= min_outlets outlets (most outlets first, then earliest), at most limit."""
    chosen = [c for c in clusters if len(c['outlets']) >= min_outlets]
    chosen.sort(key=lambda c: (-len(c['outlets']), c['first'], c['id']))
    for c in chosen[:limit]:
        n = len(c['outlets'])
        items = [article_evidence(ctx, a, fetch) for a in c['articles']]
        listing = '; '.join(f'{a["outlet"]} {a["published_at"]}' for a in c['articles'])
        copies = f'; {len(c["copies"])} duplicate / syndicated copies counted once' if c['copies'] else ''
        caveat = (' Outlets can carry the same syndicated or re-posted copy: they are not independent '
                  'confirmations;' if n > 1 else '')
        res.add(conclude(scope, question,
                         f'{label}: story {c["id"]} reported by {n} outlet{"s" if n > 1 else ""} (aggregator) — '
                         f'{headline_ref(c["lead"]["title"])}; articles: {listing}{copies}.{caveat} '
                         f'{NOT_ESTABLISHED[0].upper() + NOT_ESTABLISHED[1:]}.',
                         items, 'aggregator', reason_codes=codes))
    return max(0, len(chosen) - limit)


# ---------------------------------------------------------------- global (Q4)

def _global(ctx, res, http_get, budget):
    tm = ctx.tm
    got = fetch_query(ctx, GEO_QUERY, http_get)
    budget['requests'] += int(got['requested'])
    budget['reused'] += int(got['reused'])
    if got['status'] != 'OK':
        res.add(unavailable('overall', Q_GEO, f'geopolitical news ({TOPICS_VERSION})',
                            f'NewsAPI query unavailable: {got["reason"]}'))
        return
    payload, fetch = got['payload'], got['fetch']
    total = payload.get('totalResults')
    unique, stats = select_articles(tm, payload, [(label, stems) for label, _, stems in GEO_TOPICS])
    clusters = cluster(unique, 'G')
    codes = _partial_codes(ctx, stats, total)
    cov = coverage(stats['returned'], total)
    res.table('Geopolitical news — query and coverage', COVERAGE_COLUMNS,
              [_coverage_row('overall', got, stats, len(clusters))], question=Q_GEO,
              note=(f'NewsAPI /v2/everything (aggregator, rank 3), one query over the pre-declared topics '
                    f'{TOPICS_VERSION}. Free plan: at most {PAGE_SIZE} results per query (no pagination beyond), '
                    f'results end ~24 h before retrieval; news complete for the window: {tm.news_complete()}. '
                    'Selection inside the results follows NewsAPI relevancy ranking (opaque).'))

    topic_rows = []
    for label, term, stems in GEO_TOPICS:
        # one entry per deduplicated article: the article itself, or the copy that matched the topic
        arts = [m for m in (topic_member(a, label) for a in unique) if m is not None]
        cl = [c for c in clusters if label in c['topics']]
        outlets = {a['outlet'].lower() for a in arts}
        topic_rows.append([label, term, ', '.join(stems), len(arts), len(cl),
                           sum(1 for c in cl if len(c['outlets']) >= STORY_MIN_OUTLETS), len(outlets)])
        if not arts:
            res.add(unavailable('overall', Q_GEO, f"geopolitical topic '{label}' (news)",
                                f'no relevant article published in the window among the {stats["returned"]} '
                                f'NewsAPI results returned of {total} (coverage {fmt_cov(cov)}): absence of '
                                'reporting is not established and nothing is concluded'))
            continue
        res.add(conclude('overall', Q_GEO,
                         f"Geopolitical topic '{label}' ({TOPICS_VERSION}): {len(cl)} story cluster(s), {len(arts)} "
                         f'article(s) from {len(outlets)} outlet(s) published in the window, in the NewsAPI sample '
                         f'(returned {stats["returned"]} of {total} results, coverage {fmt_cov(cov)}). '
                         f'{NOT_ESTABLISHED[0].upper() + NOT_ESTABLISHED[1:]}.',
                         [article_evidence(ctx, a, fetch) for a in arts], 'aggregator', reason_codes=codes))
    res.table('Geopolitical news — pre-declared topics', [
        'topic', 'query term', 'stems matched in title / description', 'articles (deduplicated)', 'story clusters',
        f'clusters with >= {STORY_MIN_OUTLETS} outlets', 'distinct outlets'], topic_rows, question=Q_GEO,
        note=f'Full pre-declared topic list {TOPICS_VERSION}, including topics with no article.')
    res.table('Geopolitical news — story clusters (all)', CLUSTER_COLUMNS + ['topics'],
              _cluster_rows(clusters, True), question=Q_GEO,
              note=(f'Every cluster is listed. Clustering: token-set Jaccard >= {JACCARD_MIN} with the first title of '
                    'the cluster (publishedAt order); one story written with different words can be split. Relevance '
                    'is a keyword match in title / description: off-topic matches are possible and are not removed '
                    'by hand. Headlines are quoted verbatim from the aggregator and are not adopted: causal claims in '
                    'headlines are not endorsed.'))
    left = _story_conclusions(ctx, res, 'overall', Q_GEO, 'Geopolitical news', clusters, fetch, codes,
                              STORY_MIN_OUTLETS, MAX_STORY_CONCLUSIONS)
    if left:
        res.notes.append(f'Geopolitical news: {left} further cluster(s) with >= {STORY_MIN_OUTLETS} outlets are listed in '
                         'the cluster table only (pre-declared cap).')


# ---------------------------------------------------------------- companies (Q1)

def _company(ctx, res, ticker, http_get, budget, coverage_rows):
    tm = ctx.tm
    name = ctx.company(ticker)
    if not name or name == ticker:
        res.add(unavailable(ticker, Q_COMPANY, 'company news (aggregator)',
                            'no company name configured (config companies): a bare-ticker query is ambiguous; '
                            'no NewsAPI request made'))
        return
    got = fetch_query(ctx, f'"{name}"', http_get)
    budget['requests'] += int(got['requested'])
    budget['reused'] += int(got['reused'])
    if got['status'] != 'OK':
        res.add(unavailable(ticker, Q_COMPANY, 'company news (aggregator)', f'NewsAPI query unavailable: {got["reason"]}'))
        return
    payload, fetch = got['payload'], got['fetch']
    total = payload.get('totalResults')
    unique, stats = select_articles(tm, payload, [(name, (name,))])
    clusters = cluster(unique, f'{ticker}-')
    codes = _partial_codes(ctx, stats, total)
    cov = coverage(stats['returned'], total)
    coverage_rows.append(_coverage_row(ticker, got, stats, len(clusters)))
    res.table(f'{ticker} — news story clusters (aggregator)', CLUSTER_COLUMNS, _cluster_rows(clusters, False),
              scope=ticker, question=Q_COMPANY,
              note=(f'NewsAPI (aggregator, rank 3), query "{name}" (title or description must contain it), '
                    f'returned {stats["returned"]} of {total} (coverage {fmt_cov(cov)}); every cluster is listed. '
                    'Headlines are quoted verbatim and not adopted; no event is established by news alone.'))
    if not unique:
        res.add(unavailable(ticker, Q_COMPANY, 'company news (aggregator)',
                            f'no relevant article published in the window among the {stats["returned"]} results '
                            f'returned of {total} (coverage {fmt_cov(cov)}): absence of reporting is not established'))
        return
    outlets = {a['outlet'].lower() for a in unique}
    first, last = unique[0]['published_at'], max(a['published_at'] for a in unique)
    res.add(conclude(ticker, Q_COMPANY,
                     f'{ticker} ("{name}"): {len(unique)} relevant article(s) in {len(clusters)} story cluster(s) '
                     f'from {len(outlets)} outlet(s), published {first} to {last} (NewsAPI returned '
                     f'{stats["returned"]} of {total} results, coverage {fmt_cov(cov)}); {NOT_ESTABLISHED}.',
                     [article_evidence(ctx, a, fetch) for a in unique], 'aggregator', reason_codes=codes))
    left = _story_conclusions(ctx, res, ticker, Q_COMPANY, f'{ticker} news', clusters, fetch, codes,
                              COMPANY_STORY_MIN_OUTLETS, MAX_COMPANY_STORY_CONCLUSIONS)
    if left:
        res.notes.append(f'{ticker} news: {left} further story cluster(s) are listed in the cluster table only '
                         f'(pre-declared cap of {MAX_COMPANY_STORY_CONCLUSIONS} conclusions per company).')


# ---------------------------------------------------------------- section

def build(ctx, tickers=None, include_global=True, http_get=None):
    """
    tickers: optional subset of ctx.universe (default: all); include_global: run the Q4 query;
    http_get: injectable requests.get-compatible callable (tests). At most 1 + len(tickers) requests.
    """
    res = SectionResult(NAME, QUESTIONS)
    tm = ctx.tm
    budget = {'requests': 0, 'reused': 0}
    if include_global:
        _global(ctx, res, http_get, budget)
    res.add(unavailable('overall', Q_GEO, 'official primary documents and event datasets for geopolitical events',
                        'not ingested: Federal Register, OFAC, BIS, USTR, GDELT, ACLED and the GPR index were not '
                        'reachable from this environment when checked on 2026-10-07 (egress proxy CONNECT 403); '
                        'geopolitical statements here rest on an aggregator only'))
    coverage_rows = []
    universe = list(tickers) if tickers is not None else list(ctx.universe)
    for t in universe:
        _company(ctx, res, t, http_get, budget, coverage_rows)
    if coverage_rows:
        res.table('Company news queries — coverage', COVERAGE_COLUMNS, coverage_rows, question=Q_COMPANY,
                  note=(f'One NewsAPI query per company (configured name, quoted). At most {PAGE_SIZE} results per '
                        f'query; news complete for the window: {tm.news_complete()}.'))
    if not tm.news_complete():
        res.notes.append(f'Generated at {tm.generated_at}, before cutoff + {NEWS_DELAY_HOURS} h: NewsAPI free-plan '
                         'results end ~24 h before retrieval, so the last part of the window can be missing '
                         '(PARTIAL_COVERAGE on every news conclusion).')
    res.notes.append(f'Window ({tm.previous_cutoff}, {tm.cutoff}]; topics {TOPICS_VERSION}; thresholds '
                     f'{thresholds_version(ctx)}; dedup on canonical URL and normalized title; clusters: token-set '
                     f'Jaccard >= {JACCARD_MIN}; global story conclusions for clusters with >= {STORY_MIN_OUTLETS} '
                     f'distinct outlets (at most {MAX_STORY_CONCLUSIONS}); company story conclusions for every '
                     f'cluster (at most {MAX_COMPANY_STORY_CONCLUSIONS} per company; most outlets first, then '
                     'earliest); every cluster is in the tables.')
    res.notes.append(f'NewsAPI requests made by this section: {budget["requests"]}; stored identical requests '
                     f'reused: {budget["reused"]}. Company queries are name searches, not an exposure map: '
                     'company-specific geopolitical exposure is not assessed.')
    return res
