import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.pipeline.ingestor import ingest_all
from app.pipeline.purge import purge_old_events

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_ingestion_job() -> None:
    logger.info("Scheduled ingestion triggered at %s", datetime.utcnow().isoformat())
    try:
        summary = await ingest_all()
        logger.info("Scheduled ingestion done: %s", summary)
    except Exception as exc:
        logger.error("Scheduled ingestion failed: %s", exc, exc_info=True)


async def _run_purge_job() -> None:
    logger.info("Scheduled purge triggered at %s", datetime.utcnow().isoformat())
    try:
        deleted = await purge_old_events()
        logger.info("Scheduled purge done: %d events deleted", deleted)
    except Exception as exc:
        logger.error("Scheduled purge failed: %s", exc, exc_info=True)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=settings.SCHEDULER_TIMEZONE)

        _scheduler.add_job(
            _run_ingestion_job,
            trigger=CronTrigger(
                hour=settings.SCHEDULER_HOUR_MORNING,
                minute=0,
                timezone=settings.SCHEDULER_TIMEZONE,
            ),
            id="ingest_morning",
            name="Morning ingestion (9h00)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        _scheduler.add_job(
            _run_ingestion_job,
            trigger=CronTrigger(
                hour=settings.SCHEDULER_HOUR_EVENING,
                minute=0,
                timezone=settings.SCHEDULER_TIMEZONE,
            ),
            id="ingest_evening",
            name="Evening ingestion (19h00)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        _scheduler.add_job(
            _run_purge_job,
            trigger=CronTrigger(
                hour=3,
                minute=0,
                timezone=settings.SCHEDULER_TIMEZONE,
            ),
            id="purge_daily",
            name="Daily purge (3h00)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    return _scheduler


async def startup_ingestion() -> None:
    logger.info("Running startup ingestion")
    await _run_ingestion_job()
    await _run_purge_job()


def start_scheduler() -> AsyncIOScheduler:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started (jobs: %s)", [j.id for j in scheduler.get_jobs()])
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None
