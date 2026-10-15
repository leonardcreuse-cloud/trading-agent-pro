#!/usr/bin/env python3
"""
Trading Agent Pro - Main Entry Point
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

from src.common import tickers, utc_now_iso  # noqa: E402

REQUIRED_SETTINGS = {
    'SEC_USER_AGENT': 'SEC EDGAR (filings, Form 4)',
    'FRED_API_KEY': 'FRED macro indicators',
    'NEWSAPI_KEY': 'NewsAPI news aggregator',
    'BLS_API_KEY': 'BLS Public Data API v2 (CPI, jobs, PPI)',
    'BEA_API_KEY': 'BEA NIPA tables (GDP, PCE, income)',
    'EIA_API_KEY': 'EIA energy data (oil, gas, stocks)',
}


def print_status():
    """Report configuration only; source health is checked during an actual run."""
    print("\n[STATUS]")
    print(f"  Universe: {', '.join(tickers())}")
    for name, purpose in REQUIRED_SETTINGS.items():
        state = 'set' if os.getenv(name, '').strip() else 'MISSING -> source will be DATA UNAVAILABLE'
        print(f"  {name:15} {state:45} ({purpose})")
    print("  Note: source availability is only known after 'python main.py analyze'.")


def main():
    if len(sys.argv) < 2:
        print_menu()
        return

    command = sys.argv[1].lower()
    if command == 'analyze':
        from src.integration import Integration
        print("\n" + "=" * 80)
        print("TRADING AGENT PRO")
        print("=" * 80)
        print(f"[{utc_now_iso()}] Starting batch analysis...")
        Integration().run_daily_batch()
    elif command == 'walkforward':
        from src.walk_forward import WalkForward
        WalkForward().run([t.upper() for t in sys.argv[2:]] or None)
    elif command == 'weekly' and '--verify' in sys.argv:
        from src.weekly.report import verify
        from src.dashboard import latest_weekly
        i = sys.argv.index('--verify')
        path = sys.argv[i + 1] if len(sys.argv) > i + 1 else str(latest_weekly()[1])
        out = verify(path)
        print(f"[WEEKLY VERIFY] {path} (cutoff {out['cutoff']}): "
              f"{'IDENTICAL' if out['identical'] else 'DIFFERENT'} ({out['archived_items']} archived items, "
              f"{out['rebuilt_items']} rebuilt); code {out['archived_code_version']} -> {out['current_code_version']}")
        for tag, items in (('only in the archive', out['only_archived']), ('only in the rebuild', out['only_rebuilt'])):
            for x in items[:10]:
                print(f'  {tag}: {str(x)[:220]}')
        sys.exit(0 if out['identical'] else 4)                          # 4: the rebuild differs from the archive
    elif command == 'weekly':
        from src.weekly.report import run
        cutoff = sys.argv[sys.argv.index('--cutoff') + 1] if '--cutoff' in sys.argv else None
        payload = run(cutoff)
        sys.exit(3 if payload.get('status') == 'INCOMPLETE' else 0)    # 3: a critical section failed
    elif command == 'research':
        from src.research.experiment import Study
        stage = int(sys.argv[sys.argv.index('--stage') + 1]) if '--stage' in sys.argv else 1
        recalc = sys.argv[sys.argv.index('--recalc') + 1] if '--recalc' in sys.argv else None
        study = Study(stage=stage, recalc=recalc)
        if '--prefetch-insider' in sys.argv:
            study.prefetch_insider()
        else:
            study.run(rebuild='--rebuild' in sys.argv)
    elif command == 'collect':
        from src.external_sources import collect_all, print_results
        results = collect_all()
        print_results(results)
        sys.exit(0 if all(r['status'] == 'OK' for r in results) else 2)    # 2: some source unavailable
    elif command == 'prospective':
        from src.prospective import Recorder, evaluate, print_evaluation
        action = sys.argv[2].lower() if len(sys.argv) > 2 else 'all'
        code = 0
        if action in ('record', 'all'):
            print("\n[PROSPECTIVE] weekly record (docs/research/STAGE3_PREREGISTRATION.md)")
            out = Recorder().run()
            print(f"  {out['status']}: {out['message']}")
            code = 1 if out['status'] in ('DATA UNAVAILABLE', 'LEDGER BROKEN') else 0
        if action in ('evaluate', 'all'):
            result = evaluate()
            print_evaluation(result)
            code = code or (1 if result['status'] == 'DATA UNAVAILABLE' else 0)
        if action not in ('record', 'evaluate', 'all'):
            print_menu()
        sys.exit(code)
    elif command == 'paper':
        from src.paper import Paper
        action = sys.argv[2].lower() if len(sys.argv) > 2 else 'all'
        paper = Paper()
        print("\n[PAPER] strategy PT1 (paper only, no real order; docs/research/PAPER_STRATEGY_PT1.md)")
        if action in ('rebalance', 'all'):
            out = paper.rebalance()
            print(f"  rebalance: {out['status']}: {out['message']}")
        if action in ('update', 'all'):
            out = paper.update()
            print(f"  update: {out['status']}: {out['message']}")
        if action in ('status', 'all'):
            st = paper.status()
            print('  status: ' + ', '.join(f'{k} {v}' for k, v in st.items() if k in (
                'status', 'last_session', 'equity', 'total_return_pct', 'max_drawdown_pct', 'sharpe', 'benchmarks',
                'pending_orders', 'cash')))
        if action == 'report':
            from src.paper_report import outcomes_by_horizon, trades
            print('  positions and trades (P&L, sessions held, worst position value vs cost):')
            for p in trades(paper.tx.entries()):
                print(f"    {p['ticker']:6} in {p['entry_session']} @ {p['entry_price']:.2f}  "
                      f"{p['exit_type'] or 'open':5} {p['exit_session'] or '':10}  P&L {p['pnl']} ({p['pnl_kind']})  "
                      f"held {p['holding_sessions']}  worst {p['worst_drawdown_pct']}%")
            for h, r in outcomes_by_horizon(paper.pred.entries()).items():
                print(f'  predictions, {h} sessions: {r}')
            from src.paper_report import price_crosscheck
            check = price_crosscheck(paper.tx.entries(), paper.db)
            sm = check['summary']
            print(f"  prices used vs Cboe (second source): {sm['compared']} of {sm['prices_used']} compared, "
                  f"{sm['above_tolerance']} above {sm['tolerance_pct']:g}%, largest gap {sm['largest_gap_pct']}%, "
                  f"{sm['missing_cboe']} without a Cboe value")
            for r in check['rows']:
                if r['flagged'] or r['cboe'] is None:
                    print(f"    {r['session']} {r['ticker']:6} {r['price']:16} PT1 {r['pt1']}  Cboe {r['cboe']}  "
                          f"gap {r['gap_pct']}%" + ('  ABOVE TOLERANCE' if r['flagged'] else ''))
        if action not in ('rebalance', 'update', 'status', 'report', 'all'):
            print_menu()
    elif command == 'evaluate-heuristic':
        from src.heuristic_evaluation import run as evaluate_heuristic
        print("\n[HEURISTIC EVALUATION] descriptive metrics on the walk-forward sample")
        evaluate_heuristic()
    elif command == 'dedupe':
        from src.database import Database
        out = Database().remove_redundant_versions()
        print(f"[DEDUPE] {out['removed']} redundant observation versions removed {out['by_source']}"
              + (f"; backup: {out['backup']}" if out['backup'] else ''))
    elif command == 'audit':
        from src.pipeline_audit import PipelineAudit
        report = PipelineAudit().run([t.upper() for t in sys.argv[2:]] or None)
        sys.exit(1 if report['status'] == 'FAIL' else 0)
    elif command == 'sources':
        from src.source_registry import print_report, run as check_sources
        report = check_sources()
        print_report(report)
        s = report['summary']
        sys.exit(0 if s['integrated_reachable'] == s['integrated_total'] else 2)    # 2: an integrated source failed
    elif command == 'verify-report':
        from src.dashboard import latest_weekly
        from src.verify_report import verify as verify_report
        path = sys.argv[2] if len(sys.argv) > 2 else str(latest_weekly()[1])
        out = verify_report(path)
        print(f"[VERIFY REPORT] {path} (cutoff {out['cutoff']}): {out['summary']}")
        for c in out['checks']:
            if c['status'] != 'MATCH':
                print(f"  {c['status']}: {c['claim'][:110]} | report {str(c['report_value'])[:40]} | source "
                      f"{str(c['source_value'])[:40]} | {str(c['detail'] or '')[:100]}")
        print(f"  Results: {out['path']}")
        sys.exit(5 if out['mismatches'] else 0)                          # 5: a report value differs from its source
    elif command == 'dashboard':
        from src.dashboard import Dashboard
        d = Dashboard()
        print(f"[DASHBOARD] {d.save_dashboard_html(d.create_live_dashboard_html())}")
    elif command == 'freshness':
        from src.freshness import check, summary
        rows = check()
        print('\n[FRESHNESS] sources the signal, PT1 and the reports depend on')
        for r in rows:
            print(f"  {r['source']:10} {r['status']:6} last download {r['last_ok']} ({r['fetch_age_h']} h)"
                  + (f", last {r['last_close']}" if r['last_close'] else '')
                  + (f" - {'; '.join(r['problems'])}" if r['problems'] else ''))
        print(f'  {summary(rows)}')
        sys.exit(0 if all(r['status'] == 'OK' for r in rows) else 1)
    elif command == 'backup':
        from src.backup import run as backup
        out = backup()
        print(f"\n[BACKUP] journals to GitHub: {out['status']}")
        for m in out['messages']:
            print(f"  {m}")
        sys.exit(0 if out['backup_branch'] else 1)
    elif command == 'status':
        print_status()
    else:
        print_menu()


def print_menu():
    print("\nUsage:")
    print("  python main.py analyze   - Run batch analysis")
    print("  python main.py walkforward [TICKER ...] - Walk-forward validation on the")
    print("                              validation universe (slow first run)")
    print("  python main.py audit [TICKER ...] - Validate stored data and point-in-time rules")
    print("  python main.py sources    - Probe every registered data source (HTTP status, terms, limits)")
    print("  python main.py dashboard  - Rebuild reports/dashboard.html from the latest outputs")
    print("  python main.py verify-report [archive.json] - Re-fetch report facts at their sources and compare")
    print("  python main.py research [--stage 1|2] [--rebuild] [--prefetch-insider] [--recalc LABEL]")
    print("                              - Predictive-edge study; results are written once, a later run")
    print("                                needs --recalc LABEL (separate file, never the original)")
    print("  python main.py weekly [--cutoff ISO] - Weekly analyst report (source-verified)")
    print("  python main.py collect   - Download external sources (CFTC, FINRA, Cboe, Fed, BLS,")
    print("                              BEA, EIA, Federal Register, GPR, GDELT, options); run it daily")
    print("                              (exit code 2 when a source is unavailable; see docs/LOCAL_RUN.md)")
    print("  python main.py prospective [record|evaluate] - Stage 3 weekly signal record (paper only)")
    print("                              and its evaluation on realised returns (default: both)")
    print("  python main.py paper [rebalance|update|status|report] - Paper strategy PT1 (paper only, no real order)")
    print("  python main.py evaluate-heuristic - Descriptive metrics of the heuristic on the walk-forward sample")
    print("  python main.py dedupe    - Remove observation versions that repeat an earlier one (backup first)")
    print("  python main.py freshness - Alert when SEC, yfinance, Cboe or FRED data are stale (exit 1)")
    print("  python main.py backup    - Commit the journals (reports/paper, reports/prospective) and push them")
    print("                              to GitHub, never with --force (last step of the nightly run)")
    print("  python main.py status    - Show configuration status")


if __name__ == "__main__":
    main()
