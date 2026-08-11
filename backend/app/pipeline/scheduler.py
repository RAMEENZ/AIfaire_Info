import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.pipeline.brief import generate_daily_brief
from app.pipeline.freshness import check_data_freshness
from app.pipeline.ingestor import ingest_alerts, ingest_all
from app.pipeline.purge import purge_old_events

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Repli si INGEST_HOURS est vide ou illisible : mieux vaut un rythme par défaut
# qu'un ordonnanceur muet, qui laisserait le site se figer sans bruit.
_INGEST_HOURS_DEFAUT = (7, 12, 17, 22)


def ingest_hours() -> tuple[int, ...]:
    """Heures d'ingestion complète, lues dans INGEST_HOURS.

    Dédoublonnées et triées : deux fois la même heure créerait deux tâches
    APScheduler de même identifiant, dont la seconde écraserait la première.
    Toute valeur hors 0-23 est ignorée avec une trace, plutôt que de faire
    échouer le démarrage — une faute de frappe dans le .env ne doit pas
    empêcher le backend de tourner.
    """
    heures: set[int] = set()
    for morceau in (settings.INGEST_HOURS or "").split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        try:
            heure = int(morceau)
        except ValueError:
            logger.warning("INGEST_HOURS : « %s » n'est pas un nombre, ignoré", morceau)
            continue
        if 0 <= heure <= 23:
            heures.add(heure)
        else:
            logger.warning("INGEST_HOURS : %d hors de 0-23, ignoré", heure)

    if not heures:
        logger.warning(
            "INGEST_HOURS inutilisable (%r) — repli sur %s",
            settings.INGEST_HOURS, _INGEST_HOURS_DEFAUT,
        )
        return _INGEST_HOURS_DEFAUT
    return tuple(sorted(heures))


async def _run_ingestion_job() -> None:
    logger.info("Scheduled ingestion triggered at %s", datetime.now(timezone.utc).isoformat())
    try:
        summary = await ingest_all()
        logger.info("Scheduled ingestion done: %s", summary)
    except Exception as exc:
        logger.error("Scheduled ingestion failed: %s", exc, exc_info=True)


async def _run_alert_ingestion_job() -> None:
    logger.info("Scheduled alert ingestion triggered at %s", datetime.now(timezone.utc).isoformat())
    try:
        summary = await ingest_alerts()
        logger.info("Scheduled alert ingestion done: %s", summary)
    except Exception as exc:
        logger.error("Scheduled alert ingestion failed: %s", exc, exc_info=True)


async def _run_freshness_check_job() -> None:
    try:
        await check_data_freshness()
    except Exception as exc:
        logger.error("Freshness check failed: %s", exc, exc_info=True)


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
    # Agrégats AVANT purge : une fois les événements supprimés, leurs comptes
    # quotidiens seraient définitivement perdus.
    try:
        from app.pipeline.stats import aggregate_daily_stats
        written = await aggregate_daily_stats()
        logger.info("Daily stats aggregated: %d rows", written)
    except Exception as exc:
        logger.error("Daily stats aggregation failed: %s", exc, exc_info=True)
    try:
        deleted = await purge_old_events()
        logger.info("Scheduled purge done: %d events deleted", deleted)
    except Exception as exc:
        logger.error("Scheduled purge failed: %s", exc, exc_info=True)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            timezone=settings.SCHEDULER_TIMEZONE,
            # misfire_grace_time par défaut d'APScheduler = 1 s : si la boucle
            # asyncio est occupée ne serait-ce qu'une seconde à l'heure pile, le
            # job cron est SILENCIEUSEMENT sauté (ingestion/brief manqués — d'où
            # l'impression que « ça ne se fait plus »). On accorde 1h de marge,
            # avec coalesce (un seul rattrapage même si plusieurs occurrences ont
            # été ratées, ex. après une coupure).
            job_defaults={
                "misfire_grace_time": 3600,
                "coalesce": True,
                "max_instances": 1,
            },
        )

        # Ingestions complètes : heures lues dans INGEST_HOURS (défaut 07h, 12h,
        # 17h, 22h — un passage toutes les 5 heures à partir de 7 h).
        for hour in ingest_hours():
            _scheduler.add_job(
                _run_ingestion_job,
                trigger=CronTrigger(hour=hour, minute=0, timezone=settings.SCHEDULER_TIMEZONE),
                id=f"ingest_{hour:02d}h",
                name=f"Ingestion complète ({hour:02d}h00)",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        # Passage horaire des sources d'alerte (météo, crues, séismes) : APIs
        # structurées sans coût LLM. À :30 pour ne pas chevaucher les runs
        # complets de :00 (le verrou d'ingestion protège de toute façon).
        if settings.HOURLY_ALERT_INGESTION:
            _scheduler.add_job(
                _run_alert_ingestion_job,
                trigger=CronTrigger(minute=30, timezone=settings.SCHEDULER_TIMEZONE),
                id="ingest_alerts_hourly",
                name="Hourly alert sources ingestion (:30)",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        # Contrôle horaire de fraîcheur des données → webhook si plus rien
        # n'est ingéré (voir app/pipeline/freshness.py).
        _scheduler.add_job(
            _run_freshness_check_job,
            trigger=CronTrigger(minute=45, timezone=settings.SCHEDULER_TIMEZONE),
            id="freshness_check_hourly",
            name="Hourly data freshness check (:45)",
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

        for hour, job_id, label in [
            (9,  "brief_morning", "Morning brief (09h00)"),
            (13, "brief_midday",  "Midday brief (13h00)"),
            (20, "brief_evening", "Evening brief (20h00)"),
        ]:
            _scheduler.add_job(
                _run_brief_job,
                trigger=CronTrigger(hour=hour, minute=0, timezone=settings.SCHEDULER_TIMEZONE),
                id=job_id,
                name=label,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

    return _scheduler


async def startup_ingestion() -> None:
    logger.info("Running startup ingestion")
    await _run_ingestion_job()
    await _run_purge_job()
    await _run_brief_job()


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
    # Les identifiants suivent INGEST_HOURS : on les redérive au lieu de les
    # figer, sinon un changement d'horaire ferait taire cette information sans
    # que rien ne le signale (la StatusBar afficherait « prochaine MàJ : — »).
    for hour in ingest_hours():
        j = _scheduler.get_job(f"ingest_{hour:02d}h")
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
