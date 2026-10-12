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
    elif command == 'weekly':
        from src.weekly.report import run
        cutoff = sys.argv[sys.argv.index('--cutoff') + 1] if '--cutoff' in sys.argv else None
        run(cutoff)
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
    print("  python main.py research [--stage 1|2] [--rebuild] [--prefetch-insider] [--recalc LABEL]")
    print("                              - Predictive-edge study; results are written once, a later run")
    print("                                needs --recalc LABEL (separate file, never the original)")
    print("  python main.py weekly [--cutoff ISO] - Weekly analyst report (source-verified)")
    print("  python main.py collect   - Download external sources (CFTC, FINRA, Cboe, Fed, BLS,")
    print("                              BEA, EIA, Federal Register, GPR, GDELT, options); run it daily")
    print("                              (exit code 2 when a source is unavailable; see docs/LOCAL_RUN.md)")
    print("  python main.py prospective [record|evaluate] - Stage 3 weekly signal record (paper only)")
    print("                              and its evaluation on realised returns (default: both)")
    print("  python main.py evaluate-heuristic - Descriptive metrics of the heuristic on the walk-forward sample")
    print("  python main.py dedupe    - Remove observation versions that repeat an earlier one (backup first)")
    print("  python main.py status    - Show configuration status")


if __name__ == "__main__":
    main()
