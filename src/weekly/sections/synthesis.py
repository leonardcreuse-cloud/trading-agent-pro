#!/usr/bin/env python3
"""
Weekly report section 'synthesis' - report parts 1 (executive summary), 19 (bull / base / bear scenarios) and 22
(conclusions and key uncertainties), and the per-asset questions of the master mission (P5), rules
SYNTHESIS_RULES_VERSION. Built LAST from the results of the other sections (build(ctx, previous)) plus a few
point-in-time recomputations (prices, insider summary); it adds no new data source.

Pillar readings (pre-declared rules; anything missing is 'unknown', never a default):
  fundamentals  quarterly revenue YoY and operating-margin change vs a year earlier (valuation section table):
                improving when YoY > 0 and margin change >= 0; deteriorating when YoY < 0 and margin change < 0;
                else mixed
  valuation     P/S and EV/sales against the pre-declared peer median (valuation section): above / below / n/a
                (relative position only, never 'cheap' or 'expensive')
  technical     trend rule of src/technicals.py on the adjusted closes up to s_0: up / down / mixed
  macro         real-yield state of the regime section; transmission stated for high-multiple companies
                (P/S above 10: long-duration cash flows are more sensitive to discount rates) - an
                interpretation, correlation is not causation
  sentiment     facts only: open-market insider purchases and discretionary sales in the 90 days to T_c (stored
                Form 4), high-materiality news clusters (news section); no direction (no validated measure)
  quant         ex-news heuristic label at T_c (quant section) and the validation status: NOT DEMONSTRATED means no
                predictive ability has been shown
  risk          volatility regime and drawdown (technicals), event risk (an earnings date in the catalyst horizon)
Agreement: fundamentals (+1 improving / -1 deteriorating / 0 mixed), technical (+1 up / -1 down / 0 mixed) and the
quant label (+1 POSITIVE / -1 NEGATIVE / 0 NEUTRAL) are compared on the pillars WITH a direction (non-zero): 'agree'
when at least two have one and all of these have the same sign, 'conflict' when their signs differ, 'not comparable'
otherwise; pillars without a direction are listed as neutral. Agreement between pillars is a hypothesis, not evidence of
future returns: no combination of them has been tested. Scenarios are conditional descriptions built from the
report's own figures (DCF scenarios, technical levels, catalysts); no probability is attached to any of them.
"""

import re

from ...insider_tracker import InsiderTracker
from ...technicals import analyze
from ..core import SectionResult, conclude, unavailable

NAME = 'synthesis'
QUESTIONS = [1, 13]
SYNTHESIS_RULES_VERSION = 'synthesis-v1-2026-10-12'
HIGH_MULTIPLE_PS = 10.0


def _num(v):
    try:
        if isinstance(v, str):
            v = v.split(' ')[0]
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _tables(previous, section, prefix):
    for s in previous:
        if s['name'] == section:
            for t in s['tables']:
                if t['title'].startswith(prefix):
                    yield t


def _table(previous, section, prefix):
    return next(_tables(previous, section, prefix), None)


def _row(table, label, col):
    if not table or col not in table['columns']:
        return None
    i = table['columns'].index(col)
    for r in table['rows']:
        if r and r[0] == label:
            return r[i]
    return None


def _items(previous, scope, limit=4):
    out = []
    for s in previous:
        for c in s['conclusions']:
            if c['scope'] == scope:
                out += c['evidence']
    seen, uniq = set(), []
    for e in out:
        key = (e.get('source'), e.get('fact'))
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    return uniq[:limit]


def _signs_text(signs):
    marks = {1: '+', -1: '-', 0: 'no direction', None: 'unknown'}
    return ', '.join(f'{k} {marks[v]}' for k, v in signs.items())


def _dcf_context(previous, t):
    """Reliability and market-implied growth stated by the valuation section's DCF conclusion for `t`."""
    for s in previous:
        if s['name'] == 'valuation':
            for c in s['conclusions']:
                if c['scope'] == t and 'two-stage FCF model' in c['statement']:
                    rel = re.search(r'Reliability ([A-Z][A-Z -]*[A-Z])', c['statement'])
                    implied = re.search(r'starting growth of (-?[0-9.]+|None)%', c['statement'])
                    return (rel.group(1) if rel else None), (implied.group(1) if implied else None)
    return None, None


def _sign(reading, positive, negative):
    return 1 if reading == positive else -1 if reading == negative else 0 if reading else None


def pillars(ctx, previous, t):
    tm = ctx.tm
    out = {}
    fund = _table(previous, 'valuation', f'{t}: fundamentals')
    yoy = _num(_row(fund, 'quarterly revenue YoY (%)', 'known at T_c'))
    margin = _num(_row(fund, 'operating margin change vs 1 year (pts)', 'known at T_c'))
    if yoy is None or margin is None:
        out['fundamentals'] = ('unknown', 'quarterly revenue YoY or operating-margin change unavailable')
    else:
        state = 'improving' if yoy > 0 and margin >= 0 else 'deteriorating' if yoy < 0 and margin < 0 else 'mixed'
        out['fundamentals'] = (state, f'quarterly revenue {yoy:+.1f}% YoY, operating margin {margin:+.2f} pts vs a year')
    peers = _table(previous, 'valuation', f'{t}: valuation versus pre-declared peers')
    ps = _num(_row(peers, t, 'price / sales TTM'))
    med = _num(_row(peers, 'peer median (n)', 'price / sales TTM'))
    if ps is None or med is None:
        out['valuation'] = ('n/a', 'P/S or peer median unavailable')
    else:
        out['valuation'] = ('above peers' if ps > med else 'below peers', f'P/S {ps} vs peer median {med}')
    p = ctx.prices(t)
    frame = p.get('frame')
    a = analyze(frame) if p.get('status') == 'OK' and frame is not None and len(frame) > 60 else None
    trend = (a or {}).get('price_action', {}).get('trend') if a else None
    out['technical'] = ((trend or {}).get('state') or 'unknown',
                        'trend rule (close vs SMA50 / SMA200)' if trend else 'not enough price history')
    regime = _table(previous, 'regime', 'Market regime')
    real = _row(regime, 'real yield (10y TIPS)', 'state')
    note = ''
    if ps is not None and ps > HIGH_MULTIPLE_PS:
        note = f'; P/S {ps} > {HIGH_MULTIPLE_PS:g}: long-duration cash flows are more sensitive to discount rates'
    out['macro'] = (f'real yields {real}' if real else 'unknown', 'regime section' + note)
    try:
        s = InsiderTracker(sec_parser=ctx.sec).summarize(t, known_at=tm.cutoff)
        ins = f"{s['insider_buys']} open-market purchase(s), discretionary sales {s['discretionary_sell_value_usd']:,.0f} USD"
    except Exception as e:  # noqa: BLE001 - reported as unknown
        ins = f'insider summary unavailable ({type(e).__name__})'
    news = _table(previous, 'news', f'{t} — news events')
    high = sum(1 for r in (news or {}).get('rows', []) if len(r) > 5 and r[5] == 'high')
    out['sentiment'] = ('facts only', f'{ins}; {high} high-materiality news cluster(s) (keyword classes)')
    quant = _table(previous, 'quant', 'Universe — heuristic signal at T_c')
    label = _row(quant, t, 'label ex-news (T_c)')
    out['quant'] = (label or 'unknown', 'ex-news heuristic label; validation NOT DEMONSTRATED (no predictive ability shown)')
    regime_v = ((a or {}).get('price_action') or {}).get('volatility_regime') or {}
    dd = ((a or {}).get('values') or {}).get('drawdown_from_52w_high')
    cat = _table(previous, 'catalysts', f'{t} — company catalysts')
    earnings = _row(cat, 'next earnings date (as known at T_c)', 'value')
    out['risk'] = (f"volatility {regime_v.get('regime', 'unknown')}",
                   f'{dd * 100:+.1f}% from the 52-week high' if dd is not None else 'drawdown n/a')
    out['events'] = (f'next earnings date (yfinance, estimate): {earnings}' if earnings else
                     'next earnings date not known at the cutoff', 'catalyst calendar (part 13)')
    return out


def agreement(p):
    signs = {'fundamentals': _sign(p['fundamentals'][0], 'improving', 'deteriorating'),
             'technical': _sign(p['technical'][0], 'up', 'down'),
             'quant': _sign(p['quant'][0], 'POSITIVE', 'NEGATIVE')}
    nonzero = {k: v for k, v in signs.items() if v}
    if len(set(nonzero.values())) > 1:
        return 'conflict', signs
    if len(nonzero) >= 2:
        return 'agree', signs
    return 'not comparable', signs


def build(ctx, previous=None):
    res = SectionResult(NAME, QUESTIONS)
    previous = previous or []
    tm = ctx.tm
    for t in ctx.universe:
        p = pillars(ctx, previous, t)
        res.table(f'{t}: four pillars (rules {SYNTHESIS_RULES_VERSION})', ['pillar', 'reading', 'basis'],
                  [[k, v[0], v[1]] for k, v in p.items() if k != 'events'], scope=t, question=1,
                  note='Readings follow pre-declared rules (src/weekly/sections/synthesis.py); unknown is never filled.')
        verdict, signs = agreement(p)
        items = _items(previous, t)
        unknown_items = [u for s in previous for u in s['unavailable'] if u['scope'] == t]
        frame = ctx.prices(t).get('frame')
        week = None
        if frame is not None and len(frame) > 5:
            week = (float(frame['close'].iloc[-1]) / float(frame['close'].iloc[-6]) - 1) * 100
        strong = sum(1 for s in previous for c in s['conclusions'] if c['scope'] == t and c['level'] == 'STRONGLY SUPPORTED')
        geo = [c for s in previous if s['name'] in ('geopolitics', 'commodities') for c in s['conclusions'] if c['scope'] == t]
        risks = [c for s in previous if s['name'] == 'risks' for c in s['conclusions'] if c['scope'] == t]
        qa = [
            ['What changed this week?', f'adjusted close {week:+.2f}% over the week' if week is not None else 'n/a', '2, 11'],
            ['What reliable new information became available?', f'{strong} strongly supported conclusion(s) for {t}', '9, 12, 14'],
            ['What improved or deteriorated fundamentally?', f"{p['fundamentals'][0]}: {p['fundamentals'][1]}", '9'],
            ['Which macroeconomic factors could influence the company?', f"{p['macro'][0]} ({p['macro'][1]})", '3, 4'],
            ['Which geopolitical or socioeconomic factors are relevant?',
             f'{len(geo)} pre-declared exposure / event match(es)' if geo else 'none matched by the pre-declared maps', '5, 6, 7'],
            ['What does technical analysis show?', f"{p['technical'][0]}; {p['risk'][0]}", '11'],
            ['What does market sentiment show?', p['sentiment'][1], '12, 14, 15'],
            ['Which facts conflict?', f'pillars: {verdict} ({_signs_text(signs)})', '1'],
            ['Which events should be monitored?', f"{p['events'][0]}; see the catalyst calendar", '13'],
            ['Which risks are increasing?', f'{len(risks)} risk conclusion(s) in the risk section', '18'],
            ['What does the quantitative model actually say?', f"ex-news heuristic label {p['quant'][0]}", '17'],
            ['Has predictive ability been demonstrated?', 'No: validation NOT DEMONSTRATED (walk-forward); stage 3 '
                                                          'pre-registered test pending (52 weeks)', '17, 21'],
            ['What remains unknown?', f'{len(unknown_items)} DATA UNAVAILABLE item(s), e.g. '
             + '; '.join(u['item'] for u in unknown_items[:3]) if unknown_items else 'no DATA UNAVAILABLE item', '20'],
        ]
        res.table(f'{t}: the questions of the weekly analysis', ['question', 'answer from this report', 'report part'],
                  qa, scope=t, question=1)
        if items:
            res.add(conclude(t, 1, f'{t}: pillars {verdict} (fundamentals {p["fundamentals"][0]}, technical '
                                   f'{p["technical"][0]}, quant label {p["quant"][0]}); valuation {p["valuation"][0]} '
                                   f'({p["valuation"][1]}); {p["macro"][0]}; risk {p["risk"][0]}. Agreement between '
                                   'pillars is a hypothesis, not evidence of future returns: no combination has been '
                                   'tested.', items, 'interpretation'))
        else:
            res.add(unavailable(t, 1, 'pillar synthesis', 'no cited conclusion for this company in the report'))
        # scenarios
        dcf = _table(previous, 'valuation', f'{t}: intrinsic-value scenarios')
        per = {r[0]: r for r in (dcf or {}).get('rows', [])}
        tech = _table(previous, 'technicals', f'{t}: technical indicators')
        reliability, implied = _dcf_context(previous, t)
        rows = []
        for name, cond in (('bull', 'fundamentals keep improving and growth exceeds the base assumption'),
                           ('base', 'growth fades as assumed in the base case'),
                           ('bear', 'growth falls short (bear assumption) or the pillars turn negative')):
            r = per.get(name)
            rows.append([name, cond, f'{r[2]} USD per share ({r[3]:+.1f}% vs close; starting growth {r[1]}%'
                         + (f'; DCF reliability {reliability})' if reliability else ')')
                         if r and r[2] is not None and r[3] is not None else 'DCF not reliable or unavailable',
                         f"{p['events'][0]}; {p['risk'][1]}"])
        res.table(f'{t}: bull / base / bear scenarios (conditional descriptions, no probabilities)',
                  ['scenario', 'condition', 'DCF figure under that condition (assumption-driven)', 'events and risks'],
                  rows, scope=t, question=1,
                  note='Scenarios restate the report\'s own figures under stated conditions; no probability and no '
                       'expected price are given.' + (f' DCF reliability {reliability}; the close is consistent with a '
                                                      f'starting growth of {implied}% under the same rates (reverse DCF).'
                                                      if reliability else '')
                       + ('' if tech else ' Technical table unavailable.'))
    # executive summary and key uncertainties (overall)
    counts = {'strong': sum(1 for s in previous for c in s['conclusions'] if c['level'] == 'STRONGLY SUPPORTED'),
              'uncertain': sum(1 for s in previous for c in s['conclusions'] if c['level'] == 'UNCERTAIN'),
              'unavailable': sum(len(s['unavailable']) for s in previous)}
    failed = [s['name'] for s in previous if any('section failed' in u['reason'] for u in s['unavailable'])]
    regime = next((c['statement'] for s in previous if s['name'] == 'regime' for c in s['conclusions']), None)
    res.add(conclude('overall', 1, f'Executive summary for the week ending {tm.s0}: the analysis sections hold '
                                   f'{counts["strong"]} strongly supported and {counts["uncertain"]} uncertain '
                                   f'conclusions, {counts["unavailable"]} DATA UNAVAILABLE items' + (f'; failed sections: {", ".join(failed)}' if failed else '')
                                   + '. ' + (regime or 'Market regime unavailable.') + ' No predictive ability of the '
                                   'quantitative signal has been demonstrated; nothing here is a recommendation.',
                     [], 'system_output'))
    uncertainties = [
        'predictive ability of the heuristic signal: NOT DEMONSTRATED (walk-forward; stage 2: 0 of 4; stage 3 pending)',
        'prices come from one secondary source (yfinance); the only cross-check is SPY vs FRED SP500',
        'news is an aggregator (NewsAPI); the sentiment lexicon is not validated and not used by the signal',
        'interpretations (pillars, regime, exposures, event themes) follow pre-declared rules, not tested models',
        'valuation scenarios rest on configurable assumptions (equity risk premium, terminal growth)',
        f'{counts["unavailable"]} DATA UNAVAILABLE items this week (see part 20)',
    ]
    res.table('Key uncertainties (part 22)', ['uncertainty'], [[u] for u in uncertainties], question=13)
    return res
