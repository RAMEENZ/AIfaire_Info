import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ConnectorStatus, Event
from app.pipeline.ingestor import CONNECTORS, ingestion_in_progress
from app.pipeline.scheduler import get_next_ingest_time
from app.schemas import HealthResponse, ConnectorStatusSchema

logger = logging.getLogger(__name__)

router = APIRouter()

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
