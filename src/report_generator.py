#!/usr/bin/env python3
"""
Report Generator - HTML and text reports

P0.1 changes:
- Missing values are rendered as "N/A — source unavailable", never as a number;
  the report no longer crashes on None (previous `${revenue:,}` formatting).
- Data availability table per ticker and source.
- Historical base rates are labelled as such (not predictions); the provisional
  backtest is shown with its majority-class baseline and warning.
- Values are HTML-escaped; emoji mojibake removed.
"""

from html import escape

from .common import DATA_UNAVAILABLE, NA_DISPLAY, display, utc_now_iso

STYLE = """
body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; color: #222; }
.container { max-width: 1200px; margin: 0 auto; background: #fff; padding: 20px; border-radius: 8px; }
h1 { border-bottom: 3px solid #0066cc; padding-bottom: 10px; }
h2 { color: #0066cc; margin-top: 30px; }
.ticker-section { margin: 20px 0; padding: 15px; background: #f9f9f9; border-left: 4px solid #0066cc; }
.warning { background: #fff4e5; border-left: 4px solid #e69500; padding: 10px; margin: 10px 0; }
.na { color: #999; font-style: italic; }
.ok { color: #1a7f37; } .bad { color: #b42318; } .prov { color: #b26b00; }
table { width: 100%; border-collapse: collapse; margin: 12px 0; }
th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #ddd; vertical-align: top; }
th { background: #0066cc; color: #fff; }
.small { color: #666; font-size: 0.9em; }
"""


def cell(value, fmt=None, suffix=''):
    """HTML cell content; missing values get the N/A marker."""
    text = display(value, fmt, suffix)
    if text == NA_DISPLAY:
        return f'<span class="na">{escape(NA_DISPLAY)}</span>'
    return escape(text)


def status_cell(status):
    css = {'OK': 'ok', 'PROVISIONAL': 'prov'}.get(status, 'bad')
    return f'<span class="{css}">{escape(str(status))}</span>'


class ReportGenerator:
    """Generate analysis reports in HTML and text"""

    def generate_html(self, all_results, run_started=None, macro_provenance=None):
        parts = [
            '<!DOCTYPE html><html><head><meta charset="UTF-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
            f'<title>Trading Agent Pro - Analysis</title><style>{STYLE}</style></head><body>',
            '<div class="container"><h1>Trading Agent Pro - Analysis Report</h1>',
            f'<p class="small">Run started: {escape(run_started or "")} | '
            f'Generated: {escape(utc_now_iso())} (UTC)</p>',
            '<div class="warning">Scores are heuristic (0-100) and not probabilities. '
            'No calibrated prediction model exists yet (phase P1). Values marked '
            f'"{escape(NA_DISPLAY)}" could not be obtained and were not replaced.</div>',
            self._summary_table(all_results),
            self._availability_table(all_results),
            self._provenance_table(all_results, macro_provenance),
        ]
        for result in all_results:
            parts.append(self._ticker_section(result))
        macro = next((r['modules'].get('macro') for r in all_results
                      if r.get('modules', {}).get('macro')), None)
        parts.append(self._macro_section(macro))
        parts.append('</div></body></html>')
        return '\n'.join(parts)

    @staticmethod
    def _summary_table(all_results):
        rows = ['<h2>Summary</h2><table><tr><th>Ticker</th><th>Signal</th><th>Heuristic score</th>'
                '<th>Coverage</th><th>Agreement</th><th>Technical</th><th>Fundamentals</th>'
                '<th>News</th></tr>']
        for r in all_results:
            sig = r.get('modules', {}).get('signal', {})
            comp = sig.get('component_scores', {})
            rows.append(
                f"<tr><td><strong>{escape(r['ticker'])}</strong></td>"
                f"<td>{cell(sig.get('signal'))}</td><td>{cell(sig.get('combined_score'))}</td>"
                f"<td>{cell(sig.get('coverage'))}</td><td>{cell(sig.get('signal_agreement'), suffix='%')}</td>"
                f"<td>{cell(comp.get('technical'))}</td><td>{cell(comp.get('fundamentals'))}</td>"
                f"<td>{cell(comp.get('news'))}</td></tr>")
        rows.append('</table>')
        return ''.join(rows)

    @staticmethod
    def _availability_table(all_results):
        names = []
        for r in all_results:
            for name in r.get('data_availability', {}):
                if name not in names:
                    names.append(name)
        rows = ['<h2>Data availability</h2><table><tr><th>Ticker</th>'
                + ''.join(f'<th>{escape(n)}</th>' for n in names) + '</tr>']
        for r in all_results:
            avail = r.get('data_availability', {})
            rows.append(f"<tr><td>{escape(r['ticker'])}</td>"
                        + ''.join(f"<td>{status_cell(avail.get(n, DATA_UNAVAILABLE))}</td>" for n in names)
                        + '</tr>')
        rows.append('</table>')
        return ''.join(rows)

    @staticmethod
    def _provenance_table(all_results, macro_provenance=None):
        """Source, rank, fetch, retrieval / publication time and freshness of each input."""
        entries = []
        for r in all_results:
            for name, prov in (r.get('provenance') or {}).items():
                entries.append((r['ticker'], name, prov))
        for name, prov in (macro_provenance or {}).items():
            entries.append(('macro', name, prov))
        rows = ['<h2>Data provenance</h2><p class="small">Rank 1 = official source. '
                'Published = when the value became public at the source (estimate when noted); '
                'values are only used once published and retrieved. Raw payloads: data/raw/ '
                '(SHA-256 prefix shown).</p><table><tr><th>Scope</th><th>Input</th><th>Source</th>'
                '<th>Rank</th><th>Fetch</th><th>Retrieved</th><th>As of</th><th>Published</th>'
                '<th>Freshness</th><th>Raw</th></tr>']
        for scope, name, p in entries:
            fresh = p.get('freshness') or {}
            age = fresh.get('age_days')
            fresh_text = fresh.get('status', 'UNKNOWN') + (f' ({age} d)' if age is not None else '')
            css = {'FRESH': 'ok', 'STALE': 'bad'}.get(fresh.get('status'), 'prov')
            sha = p.get('raw_sha256')
            rows.append(
                f"<tr><td>{escape(str(scope))}</td><td>{escape(str(name))}</td>"
                f"<td>{cell(p.get('source'))}</td><td>{cell(p.get('source_rank'))}</td>"
                f"<td>{cell(p.get('fetch_id'))}</td><td>{cell(p.get('retrieved_at'))}</td>"
                f"<td>{cell(p.get('as_of_date'))}</td>"
                f"<td title=\"{escape(str(p.get('published_at_basis') or ''))}\">{cell(p.get('published_at'))}</td>"
                f"<td><span class=\"{css}\">{escape(fresh_text)}</span></td>"
                f"<td>{cell(sha[:12] if sha else None)}</td></tr>")
        if not entries:
            rows.append(f'<tr><td colspan="10">{cell(None)}</td></tr>')
        rows.append('</table>')
        return ''.join(rows)

    @staticmethod
    def _reason(module):
        if module.get('reason'):
            return f'<p class="small">Reason: {escape(str(module["reason"]))}</p>'
        return ''

    def _ticker_section(self, result):
        m = result.get('modules', {})
        ticker = escape(result['ticker'])
        out = [f'<div class="ticker-section"><h2>{ticker}</h2>']

        sec = m.get('sec', {})
        latest = sec.get('latest_periodic_filing') or {}
        out.append('<h3>SEC EDGAR</h3><table>'
                   f"<tr><td>CIK</td><td>{cell(sec.get('cik'))}</td></tr>"
                   f"<tr><td>Latest 10-K/10-Q</td><td>{cell(latest.get('form'))} "
                   f"filed {cell(latest.get('filing_date'))}</td></tr>"
                   f"<tr><td>Form 4 filings (90d)</td><td>{cell(sec.get('form4_filings_90d'))}</td></tr>"
                   f"<tr><td>Revenue</td><td>{cell(sec.get('revenue'), ',.0f')}</td></tr>"
                   f"<tr><td>Debt / equity</td><td>{cell(sec.get('debt_to_equity'))}</td></tr>"
                   '</table>')
        if sec.get('error'):
            out.append(f'<p class="small">SEC error: {escape(str(sec["error"]))}</p>')

        tech = m.get('technical', {})
        comps = tech.get('components', {})
        out.append('<h3>Technical</h3><table>'
                   f"<tr><td>Signal / score</td><td>{cell(tech.get('signal'))} / {cell(tech.get('technical_score'))}</td></tr>"
                   f"<tr><td>RSI(14)</td><td>{cell(comps.get('rsi', {}).get('value'))}</td></tr>"
                   f"<tr><td>MACD histogram</td><td>{cell(comps.get('macd', {}).get('histogram'))}</td></tr>"
                   f"<tr><td>Last close</td><td>{cell(comps.get('bollinger', {}).get('price'))}"
                   f" ({cell(tech.get('last_price_date'))})</td></tr></table>")
        out.append(self._reason(tech))

        fund = m.get('fundamentals', {})
        out.append(f"<h3>Fundamentals</h3><p>Score: {cell(fund.get('fundamental_score'))} "
                   f"(coverage {cell(fund.get('coverage'))})</p>")
        out.append(self._reason(fund))

        news = m.get('news', {})
        out.append('<h3>News (NewsAPI aggregator)</h3><table>'
                   f"<tr><td>Query</td><td>{cell(news.get('query'))}</td></tr>"
                   f"<tr><td>Articles</td><td>{cell(news.get('articles_count'))}</td></tr>"
                   f"<tr><td>Published range</td><td>{cell(news.get('oldest_article_published_at'))} → "
                   f"{cell(news.get('newest_article_published_at'))}</td></tr>"
                   f"<tr><td>Score</td><td>{cell(news.get('news_score'))}</td></tr></table>")
        out.append(self._reason(news))

        pred = m.get('prediction', {})
        out.append('<h3>Historical base rates (not a prediction)</h3>')
        if pred.get('status') == 'OK':
            out.append(f'<div class="warning">{escape(pred.get("method", ""))} Window: '
                       f'{escape(str(pred.get("window_start")))} to {escape(str(pred.get("window_end")))}.</div>')
            out.append('<table><tr><th>Horizon</th><th>Up-frequency</th><th>Mean return</th>'
                       '<th>Independent windows</th></tr>')
            for horizon, h in pred.get('horizons', {}).items():
                flag = ' (insufficient)' if h.get('insufficient_sample') else ''
                out.append(f"<tr><td>{escape(horizon)}</td><td>{cell(h.get('historical_up_frequency_pct'), suffix='%')}</td>"
                           f"<td>{cell(h.get('mean_return_pct'), suffix='%')}</td>"
                           f"<td>{cell(h.get('n_independent'))}{escape(flag)}</td></tr>")
            out.append('</table>')
        else:
            out.append(f'<p>{cell(None)}</p>' + self._reason(pred))

        bt = m.get('backtest', {})
        metrics = bt.get('backtest_results', {})
        out.append('<h3>Momentum signal check (provisional)</h3>')
        if metrics:
            out.append(f'<div class="warning">{escape(bt.get("warning", ""))}</div><table>'
                       f"<tr><td>3-class accuracy</td><td>{cell(metrics.get('accuracy_3class_pct'), suffix='%')}</td></tr>"
                       f"<tr><td>Majority-class baseline</td><td>{cell(metrics.get('baseline_accuracy_pct'), suffix='%')}</td></tr>"
                       f"<tr><td>Independent 5d periods</td><td>{cell(metrics.get('independent_5d_periods'))}</td></tr>"
                       '</table>')
        else:
            out.append(f'<p>{cell(None)}</p>' + self._reason(bt))

        wf = m.get('walk_forward', {})
        out.append(f"<h3>Walk-forward validation</h3><p>{status_cell(wf.get('status', DATA_UNAVAILABLE))}</p>")
        out.append(self._reason(wf))
        out.append('</div>')
        return '\n'.join(out)

    @staticmethod
    def _macro_section(macro):
        out = ['<h2>Macro (FRED)</h2>']
        if not macro or not macro.get('indicators'):
            out.append(f'<p>{cell(None)}</p>')
            return '\n'.join(out)
        out.append('<table><tr><th>Indicator</th><th>Value</th><th>Observation date</th><th>Source</th></tr>')
        for name, d in macro['indicators'].items():
            if d.get('status') == 'OK':
                out.append(f"<tr><td>{escape(name)}</td><td>{cell(d['value'])} {escape(d['unit'])}</td>"
                           f"<td>{cell(d['observation_date'])}</td><td>{escape(d['series_id'])}</td></tr>")
            else:
                out.append(f"<tr><td>{escape(name)}</td><td>{cell(None)}</td><td></td>"
                           f"<td class='small'>{escape(str(d.get('reason', '')))}</td></tr>")
        out.append('</table>')
        return '\n'.join(out)

    @staticmethod
    def generate_summary(all_results):
        lines = ['', '=' * 80, 'TRADING AGENT PRO - ANALYSIS SUMMARY', '=' * 80]
        for r in all_results:
            sig = r.get('modules', {}).get('signal', {})
            lines.append(f"\n{r['ticker']}")
            lines.append(f"  Signal:   {display(sig.get('signal'))}")
            lines.append(f"  Score:    {display(sig.get('combined_score'))} (heuristic, coverage {display(sig.get('coverage'))})")
            unavailable_sources = [n for n, s in r.get('data_availability', {}).items() if s not in ('OK', 'PROVISIONAL')]
            if unavailable_sources:
                lines.append(f"  Unavailable / not implemented: {', '.join(unavailable_sources)}")
        lines.append('=' * 80)
        return '\n'.join(lines)


if __name__ == "__main__":
    print(ReportGenerator().generate_summary([]))
