import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Event
from app.schemas import EventDetail, EventList
from app.pipeline.ingestor import ingest_all

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


@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)) -> dict:
    """Statistiques générales sur les événements en base."""
    # Total
    total_result = await db.execute(select(func.count()).select_from(Event))
    total_events: int = total_result.scalar_one()

    # Par source
    by_source_result = await db.execute(
        select(Event.source, func.count().label("cnt"))
        .group_by(Event.source)
        .order_by(func.count().desc())
    )
    by_source = {row.source: row.cnt for row in by_source_result}

    # Par catégorie
    by_cat_result = await db.execute(
        select(Event.categorie, func.count().label("cnt"))
        .group_by(Event.categorie)
        .order_by(func.count().desc())
    )
    by_categorie = {row.categorie: row.cnt for row in by_cat_result}

    # Localisés vs nationaux
    localized_result = await db.execute(
        select(func.count()).select_from(Event).where(Event.lieu_lat.is_not(None))
    )
    localized: int = localized_result.scalar_one()
    national: int = total_events - localized

    # Dates extrêmes
    dates_result = await db.execute(
        select(
            func.min(Event.date_publication).label("oldest"),
            func.max(Event.date_publication).label("newest"),
        )
    )
    dates_row = dates_result.one()

    return {
        "total_events": total_events,
        "by_source": by_source,
        "by_categorie": by_categorie,
        "localized": localized,
        "national": national,
        "oldest_event": dates_row.oldest,
        "newest_event": dates_row.newest,
    }


@router.post("/ingest/run")
async def trigger_ingest() -> dict:
    """Déclenche manuellement l'ingestion de tous les connecteurs."""
    import asyncio
    asyncio.create_task(ingest_all())
    return {"status": "started", "message": "Ingestion déclenchée en arrière-plan"}


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
