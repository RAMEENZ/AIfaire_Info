from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ConnectorStatus
from app.schemas import HealthResponse, ConnectorStatusSchema

router = APIRouter()

KNOWN_CONNECTORS = [
    "meteo_france",
    "vigicrues",
    "renass",
    "enedis",
    "presse_rss",
]

WARNING_THRESHOLD_HOURS = 25
ERROR_THRESHOLD_HOURS = 49


def _compute_status(last_run: Optional[datetime], last_error: Optional[str]) -> str:
    if last_error:
        return "error"
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
            status = _compute_status(row.last_run, row.last_error)
            connectors.append(
                ConnectorStatusSchema(
                    name=name,
                    last_run=row.last_run,
                    last_error=row.last_error,
                    status=status,
                )
            )
        else:
            connectors.append(
                ConnectorStatusSchema(
                    name=name,
                    last_run=None,
                    last_error=None,
                    status="warning",
                )
            )

    return HealthResponse(
        connectors=connectors,
        checked_at=datetime.now(timezone.utc),
    )
