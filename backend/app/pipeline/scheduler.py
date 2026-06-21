import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.pipeline.brief import generate_daily_brief
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


async def _run_brief_job() -> None:
    logger.info("Scheduled brief generation triggered at %s", datetime.now(timezone.utc).isoformat())
    try:
        content = await generate_daily_brief()
        if content:
            logger.info("Brief generated: %d chars", len(content))
        else:
            logger.info("Brief generation skipped (no events or no AI key)")
    except Exception as exc:
        logger.error("Brief generation failed: %s", exc, exc_info=True)


async def _run_weekly_brief_job() -> None:
    logger.info("Scheduled weekly brief triggered at %s", datetime.now(timezone.utc).isoformat())
    try:
        from app.pipeline.brief import generate_weekly_brief
        content = await generate_weekly_brief()
        if content:
            logger.info("Weekly brief generated: %d chars", len(content))
        else:
            logger.info("Weekly brief skipped")
    except Exception as exc:
        logger.error("Weekly brief failed: %s", exc, exc_info=True)


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

        # Deux ingestions par jour : 07h00 et 19h00 (cycle 12h)
        for hour, job_id, label in [
            (7,  "ingest_morning", "Morning ingestion (07h00)"),
            (19, "ingest_evening", "Evening ingestion (19h00)"),
        ]:
            _scheduler.add_job(
                _run_ingestion_job,
                trigger=CronTrigger(hour=hour, minute=0, timezone=settings.SCHEDULER_TIMEZONE),
                id=job_id,
                name=label,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        _scheduler.add_job(
            _run_purge_job,
            trigger=CronTrigger(hour=3, minute=0, timezone=settings.SCHEDULER_TIMEZONE),
            id="purge_daily",
            name="Daily purge (03h00)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        _scheduler.add_job(
            _run_brief_job,
            trigger=CronTrigger(hour=9, minute=0, timezone=settings.SCHEDULER_TIMEZONE),
            id="brief_morning",
            name="Daily brief (09h00)",
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
    earliest = None
    for jid in ("ingest_morning", "ingest_evening"):
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
