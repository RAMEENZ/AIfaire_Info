import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.pipeline.ingestor import ingest_all
from app.pipeline.purge import purge_old_events

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_ingestion_job() -> None:
    logger.info("Scheduled ingestion triggered at %s", datetime.now(timezone.utc).isoformat())
    try:
        summary = await ingest_all()
        logger.info("Scheduled ingestion done: %s", summary)
    except Exception as exc:
        logger.error("Scheduled ingestion failed: %s", exc, exc_info=True)


async def _run_purge_job() -> None:
    logger.info("Scheduled purge triggered at %s", datetime.now(timezone.utc).isoformat())
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
                hour=settings.SCHEDULER_HOUR_MIDDAY,
                minute=0,
                timezone=settings.SCHEDULER_TIMEZONE,
            ),
            id="ingest_midday",
            name=f"Midday ingestion ({settings.SCHEDULER_HOUR_MIDDAY}h00)",
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
            _run_ingestion_job,
            trigger=CronTrigger(
                hour=settings.SCHEDULER_HOUR_NIGHT,
                minute=0,
                timezone=settings.SCHEDULER_TIMEZONE,
            ),
            id="ingest_night",
            name=f"Night ingestion ({settings.SCHEDULER_HOUR_NIGHT}h00)",
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


def get_next_ingest_time() -> str | None:
    if _scheduler is None or not _scheduler.running:
        return None
    job = _scheduler.get_job("ingest_morning") or _scheduler.get_job("ingest_midday") or \
          _scheduler.get_job("ingest_evening") or _scheduler.get_job("ingest_night")
    if job is None:
        return None
    # Find the soonest next run across all ingest jobs
    earliest = None
    for jid in ("ingest_morning", "ingest_midday", "ingest_evening", "ingest_night"):
        j = _scheduler.get_job(jid)
        if j and j.next_run_time:
            if earliest is None or j.next_run_time < earliest:
                earliest = j.next_run_time
    return earliest.isoformat() if earliest else None


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None
