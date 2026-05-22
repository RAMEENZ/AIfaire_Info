import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Event
from app.schemas import EventDetail, EventList

router = APIRouter()

VALID_CATEGORIES = {"meteo", "crue", "seisme", "energie", "sante", "transport", "ordre_public", "actualite"}
VALID_NIVEAUX = {"commune", "departement", "region", "national"}
BBOX_RE = re.compile(r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?$")


@router.get("/events", response_model=EventList)
async def list_events(
    bbox: Optional[str] = Query(None, description="lat_min,lon_min,lat_max,lon_max"),
    categories: Optional[list[str]] = Query(None),
    gravite_min: Optional[int] = Query(None, ge=0, le=3),
    niveau: Optional[str] = Query(None),
    depuis: Optional[datetime] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    national_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> EventList:
    if categories:
        invalid = [c for c in categories if c not in VALID_CATEGORIES]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid categories: {invalid}")

    if niveau and niveau not in VALID_NIVEAUX:
        raise HTTPException(status_code=422, detail=f"Invalid niveau: {niveau}. Must be one of {VALID_NIVEAUX}")

    since_dt = depuis or (datetime.now(timezone.utc) - timedelta(hours=48))
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=timezone.utc)

    stmt = select(Event).where(Event.date_publication >= since_dt)

    if categories:
        stmt = stmt.where(Event.categorie.in_(categories))

    if gravite_min is not None:
        stmt = stmt.where(Event.gravite >= gravite_min)

    if niveau:
        stmt = stmt.where(Event.lieu_niveau == niveau)

    if national_only:
        stmt = stmt.where(Event.geom.is_(None))

    if bbox:
        if not BBOX_RE.match(bbox):
            raise HTTPException(status_code=422, detail="bbox must be 'lat_min,lon_min,lat_max,lon_max'")
        parts = [float(x) for x in bbox.split(",")]
        lat_min, lon_min, lat_max, lon_max = parts
        if lat_min >= lat_max or lon_min >= lon_max:
            raise HTTPException(status_code=422, detail="bbox: lat_min < lat_max and lon_min < lon_max required")
        bbox_wkt = f"POLYGON(({lon_min} {lat_min},{lon_max} {lat_min},{lon_max} {lat_max},{lon_min} {lat_max},{lon_min} {lat_min}))"
        stmt = stmt.where(
            func.ST_Within(
                Event.geom,
                func.ST_GeomFromText(bbox_wkt, 4326),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    stmt = stmt.order_by(Event.date_publication.desc()).limit(limit)
    result = await db.execute(stmt)
    events = result.scalars().all()

    return EventList(
        events=list(events),
        total=total,
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/events/{event_id}", response_model=EventDetail)
async def get_event(
    event_id: str,
    db: AsyncSession = Depends(get_db),
) -> EventDetail:
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()

    if event is None:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found")

    return event
