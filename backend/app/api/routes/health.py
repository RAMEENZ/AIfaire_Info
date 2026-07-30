import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import ConnectorStatus, Event
from app.pipeline.ingestor import CONNECTORS, ingestion_in_progress
from app.pipeline.scheduler import get_next_ingest_time
from app.schemas import HealthResponse, ConnectorStatusSchema

logger = logging.getLogger(__name__)

router = APIRouter()

# Routeur séparé, monté SANS le préfixe /api : /healthz est une sonde
# d'infrastructure (healthcheck Docker), pas un endpoint de l'API publique.
healthz_router = APIRouter()

# Instant de démarrage du processus (import du module ≈ boot de l'app) :
# référence de la fenêtre de grâce pendant laquelle des données absentes ou
# périmées sont tolérées (l'ingestion de démarrage n'a pas encore fini).
STARTED_AT = datetime.now(timezone.utc)

# Liste canonique dérivée des connecteurs réellement enregistrés : évite la
# dérive entre cette liste et CONNECTORS (auparavant figée à 8 noms, alors que
# 15 connecteurs tournent — cert_fr, irsn, air_quality, opensky n'apparaissaient
# jamais dans la barre de statut).
KNOWN_CONNECTORS = [c.name for c in CONNECTORS]

WARNING_THRESHOLD_HOURS = 25
ERROR_THRESHOLD_HOURS = 49

# Au-delà de ce nombre d'échecs consécutifs, une panne cesse d'être « transitoire »
# (dégradé) et devient « chronique » (erreur) — quel que soit le délai écoulé.
CHRONIC_FAILURE_THRESHOLD = 3


def _compute_status(
    last_run: Optional[datetime],
    last_error: Optional[str],
    consecutive_failures: int = 0,
) -> str:
    # Panne chronique : plusieurs runs d'affilée en échec → erreur franche.
    if last_error and consecutive_failures >= CHRONIC_FAILURE_THRESHOLD:
        return "error"
    # Échec isolé (1 ou 2 runs) : dégradé plutôt qu'erreur — évite l'alarme rouge
    # sur un simple 5xx amont transitoire.
    if last_error:
        return "warning"
    if last_run is None:
        return "warning"
    now = datetime.now(timezone.utc)
    lr = last_run if last_run.tzinfo else last_run.replace(tzinfo=timezone.utc)
    hours_since = (now - lr).total_seconds() / 3600
    if hours_since > ERROR_THRESHOLD_HOURS:
        return "error"
    if hours_since > WARNING_THRESHOLD_HOURS:
        return "warning"
    return "ok"


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    result = await db.execute(select(ConnectorStatus))
    rows = {row.name: row for row in result.scalars().all()}

    connectors: list[ConnectorStatusSchema] = []
    for name in KNOWN_CONNECTORS:
        row = rows.get(name)
        if row:
            status = _compute_status(row.last_run, row.last_error, row.consecutive_failures)
            connectors.append(
                ConnectorStatusSchema(
                    name=name,
                    last_run=row.last_run,
                    last_error=row.last_error,
                    last_count=row.last_count,
                    last_success=row.last_success,
                    consecutive_failures=row.consecutive_failures,
                    status=status,
                )
            )
        else:
            connectors.append(
                ConnectorStatusSchema(
                    name=name,
                    last_run=None,
                    last_error=None,
                    last_count=None,
                    last_success=None,
                    consecutive_failures=0,
                    status="warning",
                )
            )

    # L'endpoint de santé ne doit jamais renvoyer 500 : on protège le parsing.
    next_ingest_at = None
    next_ingest_raw = get_next_ingest_time()
    if next_ingest_raw:
        try:
            next_ingest_at = datetime.fromisoformat(next_ingest_raw)
        except (ValueError, TypeError):
            logger.warning("Could not parse next_ingest time: %r", next_ingest_raw)

    return HealthResponse(
        connectors=connectors,
        checked_at=datetime.now(timezone.utc),
        next_ingest_at=next_ingest_at,
    )


def next_ingest_at_iso() -> Optional[str]:
    raw = get_next_ingest_time()
    return raw if raw else None


@router.get("/health/feeds")
async def feeds_health() -> dict:
    """Rapport des flux RSS en échec (circuit-breaker + dernière erreur).

    Avec 800+ flux, l'érosion est permanente (403 anti-bot, URLs déplacées,
    sites disparus) : ce rapport transforme le tri des flux morts en lecture
    de quelques minutes. État en mémoire — vide juste après un redémarrage,
    rempli après la première ingestion.
    """
    for connector in CONNECTORS:
        feed_health = getattr(connector, "feed_health", None)
        if callable(feed_health):
            return feed_health()
    return {"total_feeds": 0, "failing_count": 0, "sidelined_count": 0, "failing": []}


# --- Healthcheck de fraîcheur (/healthz) ------------------------------------
# L'ancien healthcheck Docker testait GET / : il validait que l'API répond,
# pas que le pipeline produit. Un scheduler mort dans un processus vivant
# laissait le conteneur « healthy » indéfiniment (panne silencieuse de
# plusieurs jours en 07/2026). /healthz répond 503 dès que le scheduler ne
# planifie plus rien ou que plus aucun événement n'est ingéré : la panne
# devient visible dans `docker compose ps` et autoheal peut redémarrer le
# conteneur.

def _tz(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def compute_healthz_reasons(
    now: datetime,
    started_at: datetime,
    next_ingest_at: Optional[datetime],
    newest_created_at: Optional[datetime],
    *,
    max_data_age_hours: int,
    scheduler_grace_minutes: int,
    boot_grace_minutes: int,
) -> list[str]:
    """Logique pure du healthcheck : liste des raisons d'être unhealthy.

    Liste vide = sain. Séparée de l'endpoint pour être testable hors-ligne.
    """
    reasons: list[str] = []

    if next_ingest_at is None:
        # get_next_ingest_time() ne renvoie None que si le scheduler est
        # arrêté ou n'a plus de jobs d'ingestion : état mort, pas transitoire.
        reasons.append("scheduler_stopped")
    elif _tz(next_ingest_at) < now - timedelta(minutes=scheduler_grace_minutes):
        # Le job existe mais son heure de passage est dépassée depuis plus
        # que la marge de rattrapage : il ne se déclenche plus.
        reasons.append("ingestion_overdue")

    # Fraîcheur des données — hors fenêtre de démarrage uniquement.
    if now - _tz(started_at) > timedelta(minutes=boot_grace_minutes):
        if newest_created_at is None:
            reasons.append("no_events_ingested")
        elif _tz(newest_created_at) < now - timedelta(hours=max_data_age_hours):
            reasons.append("stale_data")

    return reasons


@healthz_router.get("/healthz")
async def healthz(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    now = datetime.now(timezone.utc)

    next_ingest: Optional[datetime] = None
    raw = get_next_ingest_time()
    if raw:
        try:
            next_ingest = datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            logger.warning("healthz: could not parse next_ingest time: %r", raw)

    try:
        # created_at (heure d'ingestion) et non date_publication : les
        # vigilances J1 sont datées de demain, une date de publication
        # « récente » ne prouve pas que le pipeline tourne.
        newest = (await db.execute(select(func.max(Event.created_at)))).scalar_one()
    except Exception as exc:
        logger.warning("healthz: database check failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "reasons": ["database_unreachable"]},
        )

    reasons = compute_healthz_reasons(
        now,
        STARTED_AT,
        next_ingest,
        newest,
        max_data_age_hours=settings.HEALTHZ_MAX_DATA_AGE_HOURS,
        scheduler_grace_minutes=settings.HEALTHZ_SCHEDULER_GRACE_MINUTES,
        boot_grace_minutes=settings.HEALTHZ_BOOT_GRACE_MINUTES,
    )
    if reasons:
        logger.warning("healthz: unhealthy (%s)", ", ".join(reasons))

    return JSONResponse(
        status_code=503 if reasons else 200,
        content={
            "status": "unhealthy" if reasons else "ok",
            "reasons": reasons,
            "next_ingest_at": next_ingest.isoformat() if next_ingest else None,
            "newest_event_created_at": newest.isoformat() if newest else None,
            "uptime_seconds": int((now - STARTED_AT).total_seconds()),
        },
    )


@router.get("/metrics")
async def metrics(db: AsyncSession = Depends(get_db)) -> dict:
    """Métriques d'exploitation compactes (JSON), pour supervision/alerting.

    Distinct de `/stats` (statistiques produit) : ici on expose l'état
    opérationnel — santé des connecteurs, fraîcheur des données, ingestion en
    cours — dans un format facile à scraper par un job de monitoring.
    """
    now = datetime.now(timezone.utc)
    h24_ago = now - timedelta(hours=24)

    total_events = (await db.execute(select(func.count()).select_from(Event))).scalar_one()
    events_24h = (
        await db.execute(
            select(func.count()).select_from(Event).where(Event.date_publication >= h24_ago)
        )
    ).scalar_one()
    newest = (await db.execute(select(func.max(Event.date_publication)))).scalar_one()

    rows = {row.name: row for row in (await db.execute(select(ConnectorStatus))).scalars().all()}
    status_counts = {"ok": 0, "warning": 0, "error": 0}
    for name in KNOWN_CONNECTORS:
        row = rows.get(name)
        if row:
            status = _compute_status(row.last_run, row.last_error, row.consecutive_failures)
        else:
            status = "warning"
        status_counts[status] += 1

    return {
        "total_events": total_events,
        "events_last_24h": events_24h,
        "newest_event": newest.isoformat() if newest else None,
        "connectors": {"total": len(KNOWN_CONNECTORS), **status_counts},
        "ingestion_in_progress": ingestion_in_progress(),
        "next_ingest_at": next_ingest_at_iso(),
        "checked_at": now.isoformat(),
    }
