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
        study = Study(stage=stage)
        if '--prefetch-insider' in sys.argv:
            study.prefetch_insider()
        else:
            study.run(rebuild='--rebuild' in sys.argv)
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
    print("  python main.py research [--stage 1|2] [--rebuild] [--prefetch-insider] - Predictive-edge study")
    print("  python main.py weekly [--cutoff ISO] - Weekly analyst report (source-verified)")
    print("  python main.py status    - Show configuration status")


if __name__ == "__main__":
    main()
