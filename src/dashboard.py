#!/usr/bin/env python3
"""
Dashboard - HTML overview built ONLY from analysis results

P0.1: the previous dashboard contained hardcoded, invented recommendations, analyst
alerts and backtest performance metrics. It now renders exclusively the
analysis results passed in; anything missing shows "N/A — source unavailable".
The full dashboard (prediction history, model performance) is phase P3.3.
"""

from html import escape
from pathlib import Path

from .common import DATA_UNAVAILABLE, NA_DISPLAY, display, reports_dir, utc_now_iso


def _cell(value, fmt=None, suffix=''):
    text = display(value, fmt, suffix)
    css = ' class="na"' if text == NA_DISPLAY else ''
    return f'<span{css}>{escape(text)}</span>'


class Dashboard:
    """Overview dashboard rendered from Integration.run_daily_batch() results."""

    def __init__(self):
        self.last_update = None

    def create_live_dashboard_html(self, analysis_results):
        """analysis_results: list of per-ticker results from Integration."""
        self.last_update = utc_now_iso()
        cards = []
        for result in analysis_results or []:
            m = result.get('modules', {})
            sig = m.get('signal', {})
            tech = m.get('technical', {})
            price = tech.get('components', {}).get('bollinger', {}).get('price')
            avail = result.get('data_availability', {})
            missing = [n for n, s in avail.items() if s not in ('OK', 'PROVISIONAL')]
            cards.append(
                '<div class="card">'
                f'<div class="ticker">{escape(result.get("ticker", "?"))}</div>'
                f'<div>Last close: {_cell(price)} ({_cell(tech.get("last_price_date"))})</div>'
                f'<div>Signal: {_cell(sig.get("signal"))}</div>'
                f'<div>Heuristic score: {_cell(sig.get("combined_score"))} '
                f'(coverage {_cell(sig.get("coverage"))})</div>'
                f'<div>P(up): {_cell(None)} <span class="small">(no calibrated model yet)</span></div>'
                f'<div>Risk: {_cell(None)} <span class="small">(risk engine: phase P3.1)</span></div>'
                f'<div class="small">Unavailable: {escape(", ".join(missing) or "none")}</div>'
                '</div>')
        if not cards:
            cards.append(f'<div class="card">{escape(NA_DISPLAY)}</div>')

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trading Agent Pro - Dashboard</title>
<style>
body {{ font-family: Arial, sans-serif; background: #0f1228; color: #e6e6e6; margin: 0; padding: 16px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }}
.card {{ background: #1a1f3a; padding: 16px; border-radius: 8px; line-height: 1.6; }}
.ticker {{ font-size: 20px; font-weight: bold; color: #7cc4ff; }}
.na {{ color: #8a8a8a; font-style: italic; }}
.small {{ color: #9a9a9a; font-size: 12px; }}
</style></head><body>
<h1>Trading Agent Pro - Dashboard</h1>
<p class="small">Generated {escape(self.last_update)} (UTC). Values come only from the latest analysis run;
missing values are shown as "{escape(NA_DISPLAY)}". Scores are heuristic, not probabilities.</p>
<div class="grid">{''.join(cards)}</div>
<p class="small">Prediction history and model performance: {escape(DATA_UNAVAILABLE)} (phase P3.3).
Educational purposes only. Not financial advice.</p>
</body></html>"""

    def save_dashboard_html(self, html_content, filename='dashboard.html'):
        path = Path(reports_dir()) / filename
        path.write_text(html_content, encoding='utf-8')
        return str(path)


if __name__ == "__main__":
    import json
    source = Path(reports_dir()) / 'analysis.json'
    results = json.loads(source.read_text(encoding='utf-8')) if source.exists() else []
    d = Dashboard()
    print(d.save_dashboard_html(d.create_live_dashboard_html(results)))
