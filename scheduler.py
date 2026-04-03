"""
APScheduler configuration for automated LinkedIn outreach.

The scheduled job runs Monday–Friday at 09:00 AM (local time).
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(timezone="America/New_York")


def _outreach_job(app):
    """Wrapper executed by APScheduler – runs inside the Flask app context."""
    logger.info("Scheduled outreach job starting…")
    from linkedin_bot import LinkedInBot
    bot = LinkedInBot()
    summary = bot.run_daily_outreach(app=app)
    logger.info(f"Scheduled outreach job finished: {summary}")


def start_scheduler(app):
    """
    Configure and start the background scheduler.

    The job fires Monday–Friday at 09:00 using a CronTrigger so that
    APScheduler handles DST and weekday filtering automatically.
    """
    if _scheduler.running:
        logger.warning("Scheduler is already running.")
        return

    _scheduler.add_job(
        func=_outreach_job,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=9,
            minute=0,
        ),
        args=[app],
        id="daily_outreach",
        name="Daily LinkedIn Outreach",
        replace_existing=True,
        misfire_grace_time=3600,  # allow up to 1 h late start
    )

    _scheduler.start()

    job = _scheduler.get_job("daily_outreach")
    if job and job.next_run_time:
        logger.info(f"Scheduler started. Next outreach run: {job.next_run_time}")
    else:
        logger.info("Scheduler started (next run time unavailable).")


def shutdown_scheduler():
    """Gracefully stop the scheduler."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down.")


def get_next_run_time() -> str:
    """Return a human-readable string of the next scheduled run time."""
    if not _scheduler.running:
        return "Scheduler not running"
    job = _scheduler.get_job("daily_outreach")
    if job and job.next_run_time:
        return job.next_run_time.strftime("%A, %B %d %Y at %I:%M %p %Z")
    return "Not scheduled"
