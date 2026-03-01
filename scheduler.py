"""
Life OS Scheduler — runs ingestion pipelines on a cron schedule.
Run with: python scheduler.py
Keeps running in the background, pulling fresh data daily.
"""
import logging
import sys
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scheduler.log"),
    ],
)
log = logging.getLogger(__name__)


def run_whoop():
    log.info("▶ Whoop ingestion starting...")
    try:
        from ingestion.whoop import run
        # Pull last 3 days to catch any delayed scoring
        since = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT00:00:00Z")
        run(since=since)
        log.info("✅ Whoop ingestion complete")
    except Exception as e:
        log.error(f"❌ Whoop ingestion failed: {e}", exc_info=True)


def run_oura():
    log.info("▶ Oura ingestion starting...")
    try:
        from ingestion.oura import run
        # Pull last 3 days to catch any delayed scoring
        start = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        run(start_date=start, end_date=end)
        log.info("✅ Oura ingestion complete")
    except Exception as e:
        log.error(f"❌ Oura ingestion failed: {e}", exc_info=True)


def run_all():
    run_whoop()
    run_oura()


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="America/Los_Angeles")

    # Run every day at 8 AM — data is usually synced from overnight by then
    scheduler.add_job(run_all, CronTrigger(hour=8, minute=0), id="daily_ingestion")

    # Also run at noon to catch any workouts logged in the morning
    scheduler.add_job(run_all, CronTrigger(hour=12, minute=0), id="midday_ingestion")

    log.info("⚡ Life OS Scheduler started. Running ingestion at 8 AM and 12 PM PT daily.")
    log.info("   Press Ctrl+C to stop.")

    # Run immediately on startup
    log.info("Running initial ingestion now...")
    run_all()

    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Scheduler stopped.")
