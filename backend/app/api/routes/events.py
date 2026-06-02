import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Event
from app.schemas import EventDetail, EventList
from app.pipeline.ingestor import ingest_all, ingestion_in_progress

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
    q: Optional[str] = Query(None, max_length=200, description="Recherche textuelle (titre, résumé, lieu)"),
    limit: int = Query(default=settings.DEFAULT_EVENTS_LIMIT, ge=1, le=settings.MAX_EVENTS_LIMIT),
    national_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> EventList:
    if categories:
        invalid = [c for c in categories if c not in VALID_CATEGORIES]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid categories: {invalid}")

    if niveau and niveau not in VALID_NIVEAUX:
        raise HTTPException(status_code=422, detail=f"Invalid niveau: {niveau}. Must be one of {VALID_NIVEAUX}")

    since_dt = depuis or (datetime.now(timezone.utc) - timedelta(hours=settings.DEFAULT_SINCE_HOURS))
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

    if q:
        q_safe = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{q_safe}%"
        stmt = stmt.where(
            Event.titre.ilike(pattern, escape="\\")
            | Event.resume_ia.ilike(pattern, escape="\\")
            | Event.lieu_nom.ilike(pattern, escape="\\")
            | Event.auteur.ilike(pattern, escape="\\")
        )

    if bbox:
        if not BBOX_RE.match(bbox):
            raise HTTPException(status_code=422, detail="bbox must be 'lat_min,lon_min,lat_max,lon_max'")
        parts = [float(x) for x in bbox.split(",")]
        lat_min, lon_min, lat_max, lon_max = parts
        if lat_min >= lat_max or lon_min >= lon_max:
            raise HTTPException(status_code=422, detail="bbox: lat_min < lat_max and lon_min < lon_max required")
        if not (-90 <= lat_min <= 90 and -90 <= lat_max <= 90):
            raise HTTPException(status_code=422, detail="bbox: latitudes must be in [-90, 90]")
        if not (-180 <= lon_min <= 180 and -180 <= lon_max <= 180):
            raise HTTPException(status_code=422, detail="bbox: longitudes must be in [-180, 180]")
        bbox_wkt = f"POLYGON(({lon_min} {lat_min},{lon_max} {lat_min},{lon_max} {lat_max},{lon_min} {lat_max},{lon_min} {lat_min}))"
        stmt = stmt.where(
            func.ST_Within(
                Event.geom,
                func.ST_GeomFromText(bbox_wkt, 4326),
            )
        )

    # Une seule requête : la fonction fenêtre count() OVER() renvoie le total
    # filtré sur chaque ligne, ce qui évite un second passage des prédicats WHERE
    # (un COUNT séparé doublait l'évaluation du filtre, bbox spatial compris).
    stmt = (
        stmt.add_columns(func.count().over().label("total_count"))
        .order_by(Event.gravite.desc(), Event.date_publication.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()
    events = [row[0] for row in rows]
    total = rows[0].total_count if rows else 0

    return EventList(
        events=events,
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
async def trigger_ingest(
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None),
) -> dict:
    """Déclenche manuellement l'ingestion de tous les connecteurs.

    Idempotent : si une ingestion est déjà en cours, le déclenchement est
    ignoré (ingest_all pose un verrou global) afin d'éviter tout empilement.
    Si INGEST_API_KEY est configuré, le header X-Api-Key est requis. En
    production, l'absence de clé verrouille l'endpoint (fail-closed) : on refuse
    plutôt que d'exposer un déclencheur de pipeline non authentifié sur le net.
    """
    if not settings.INGEST_API_KEY:
        if settings.APP_ENV == "production":
            raise HTTPException(
                status_code=503,
                detail="Ingestion désactivée : INGEST_API_KEY non configuré en production",
            )
        # dev/test : pas de clé requise, on laisse passer.
    elif x_api_key != settings.INGEST_API_KEY:
        raise HTTPException(status_code=401, detail="X-Api-Key manquant ou incorrect")
    if ingestion_in_progress():
        return {"status": "already_running", "message": "Une ingestion est déjà en cours"}
    background_tasks.add_task(ingest_all)
    return {"status": "started", "message": "Ingestion déclenchée en arrière-plan"}


@router.get("/events/{event_id}", response_model=EventDetail)
async def get_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> EventDetail:
    result = await db.execute(select(Event).where(Event.id == str(event_id)))
    event = result.scalar_one_or_none()

    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    return event
