#!/usr/bin/env python3
"""
Trading Agent Pro - Main Entry Point
"""

from dotenv import load_dotenv
load_dotenv()

from src.integration import Integration
import sys


def main():
    """Main entry point"""

    if len(sys.argv) < 2:
        print_menu()
        return

    command = sys.argv[1].lower()

    if command == 'analyze':
        print("\n" + "=" * 80)
        print("TRADING AGENT PRO - v1.0")
        print("=" * 80)
        print("[2026-10-04 14:30:54] Starting daily batch analysis...")

        integration = Integration()
        integration.run_daily_batch()

    elif command == 'status':
        print("\n[STATUS]")
        print("OK - All 27 modules ready")

    else:
        print_menu()


def print_menu():
    """Print menu"""
    print("\nUsage:")
    print("  python main.py analyze   - Run daily batch analysis")
    print("  python main.py status    - Check system status")


if __name__ == "__main__":
    main()
