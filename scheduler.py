#!/usr/bin/env python3
"""
Scheduler - Daily 08:00 AM batch execution
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from src.integration import Integration
from datetime import datetime


def scheduled_job():
    """Daily batch analysis job"""
    print(f"\n[SCHEDULER] Running scheduled job at {datetime.now()}")
    integration = Integration()
    integration.run_daily_batch()
    print(f"[SCHEDULER] Job completed at {datetime.now()}\n")


def start_scheduler():
    """Start 24/7 monitoring scheduler"""
    scheduler = BlockingScheduler()
    
    # Run daily at 08:00 AM
    scheduler.add_job(scheduled_job, 'cron', hour=8, minute=0, second=0)
    
    print("=" * 80)
    print("[SCHEDULER] Trading Agent Pro - Live Monitoring Started")
    print("=" * 80)
    print("Schedule: Daily at 08:00 AM (before market open)")
    print("Reports: reports/analysis_*.json + reports/analysis_*.html")
    print("=" * 80)
    
    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\n[SCHEDULER] Stopped")


if __name__ == "__main__":
    start_scheduler()