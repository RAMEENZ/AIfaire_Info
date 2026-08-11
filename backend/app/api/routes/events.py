import asyncio
import hashlib
import hmac
import json
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response as HTTPResponse, StreamingResponse
from sqlalchemy import case, select, func

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession

from app.categories import CATEGORY_SET
from app.config import settings
from app.database import get_db
from app.models import Event
from app.schemas import EventBase, EventDetail, EventList
from app.pipeline.ingestor import ingest_all, ingestion_in_progress

# ── Cache Redis (optionnel) ──────────────────────────────────────────────────
try:
    import redis.asyncio as aioredis
    _redis_client: "aioredis.Redis | None" = None

    async def _get_redis() -> "aioredis.Redis | None":
        global _redis_client
        if not settings.REDIS_URL:
            return None
        if _redis_client is None:
            try:
                _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
                await _redis_client.ping()
            except Exception:
                _redis_client = None
        return _redis_client
except ImportError:
    async def _get_redis():  # type: ignore[misc]
        return None


async def invalidate_events_cache() -> int:
    """Supprime toutes les réponses /events en cache. Renvoie le nombre de clés.

    Appelée en fin d'ingestion : sans cela, un rafraîchissement manuel juste
    après un run continuait de servir la réponse d'avant pendant la durée de vie
    du cache (REDIS_EVENTS_TTL, 120 s par défaut).
    """
    redis = await _get_redis()
    if not redis:
        return 0
    removed = 0
    try:
        async for key in redis.scan_iter(match="events:*", count=200):
            await redis.delete(key)
            removed += 1
    except Exception as exc:
        logger.warning("Invalidation du cache /events échouée : %s", exc)
    return removed


def _events_cache_key(**params) -> str:
    raw = json.dumps(params, sort_keys=True, default=str)
    return f"events:{hashlib.md5(raw.encode()).hexdigest()}"

router = APIRouter()

# ── Plafond de connexions SSE simultanées ─────────────────────────────────────
# Chaque flux /events/stream garde une coroutine + sonde la base toutes les 30 s.
# On borne le nombre de flux concurrents pour ne pas épuiser le pool de
# connexions PostgreSQL. Compteur simple (pas de verrou) : l'event loop asyncio
# est mono-thread, donc l'incrément/décrément est atomique entre deux points
# d'await.
_sse_active_connections = 0


def _acquire_sse_slot() -> bool:
    """Réserve un créneau SSE. Retourne False si le plafond est atteint."""
    global _sse_active_connections
    if _sse_active_connections >= settings.MAX_SSE_CONNECTIONS:
        return False
    _sse_active_connections += 1
    return True


def _release_sse_slot() -> None:
    global _sse_active_connections
    _sse_active_connections = max(0, _sse_active_connections - 1)


# Longueur du résumé conservée dans les listes. Le texte complet reste servi
# par GET /events/{id} (et par ?full=true) : dans le fil, seul le début est
# visible tant que la carte n'est pas dépliée.
_RESUME_PREVIEW_CHARS = 220


def _truncate_resume(text: Optional[str]) -> Optional[str]:
    if not text or len(text) <= _RESUME_PREVIEW_CHARS:
        return text
    # Coupe au dernier espace pour ne pas trancher un mot en deux.
    cut = text[:_RESUME_PREVIEW_CHARS]
    space = cut.rfind(" ")
    if space > _RESUME_PREVIEW_CHARS * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:.") + "…"


# Un code département sert de PRÉFIXE dans un LIKE : sans validation, « 7 »
# correspond à « 75056 », « 76540 »… et renvoie silencieusement les
# départements 70 à 79. /feed.rss validait déjà, /events et /stats/geo non.
DEPT_RE = re.compile(r"^(\d{2,3}|2[AB])$")


def _validate_dept(dept: Optional[str]) -> Optional[str]:
    if dept is None:
        return None
    dept = dept.strip().upper()
    if not DEPT_RE.match(dept):
        raise HTTPException(
            status_code=422,
            detail="dept doit être un code département : 2 chiffres, 2A/2B, ou 3 chiffres (DOM)",
        )
    return dept


VALID_CATEGORIES = CATEGORY_SET
VALID_NIVEAUX = {"commune", "departement", "region", "national"}
VALID_SORTS = {"gravite", "recent", "pertinence"}
BBOX_RE = re.compile(r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?$")


@router.get("/events", response_model=EventList)
async def list_events(
    bbox: Optional[str] = Query(None, description="lat_min,lon_min,lat_max,lon_max"),
    categories: Optional[list[str]] = Query(None),
    gravite_min: Optional[int] = Query(None, ge=0, le=3),
    niveau: Optional[str] = Query(None),
    depuis: Optional[datetime] = Query(None),
    avant: Optional[datetime] = Query(None, description="Filtrer les événements antérieurs à cette date"),
    q: Optional[str] = Query(None, max_length=200, description="Recherche textuelle (titre, résumé, lieu)"),
    limit: int = Query(default=settings.DEFAULT_EVENTS_LIMIT, ge=1, le=settings.MAX_EVENTS_LIMIT),
    offset: int = Query(default=0, ge=0, le=100_000, description="Rang du premier événement (pagination)"),
    full: bool = Query(
        default=False,
        description="Résumés IA complets. Par défaut ils sont tronqués : "
        "invisibles tant qu'une carte n'est pas dépliée, ils pesaient un tiers de la réponse.",
    ),
    national_only: bool = Query(False),
    dept: Optional[str] = Query(None, max_length=3, description="Filtrer par code département (ex: 75, 13, 2A)"),
    sort: str = Query(
        "gravite",
        description="Ordre de tri : 'gravite' (défaut : gravité puis récence), "
        "'recent' (le plus récent d'abord), 'pertinence' (gravité pondérée par la récence)",
    ),
    db: AsyncSession = Depends(get_db),
) -> EventList:
    if categories:
        invalid = [c for c in categories if c not in VALID_CATEGORIES]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid categories: {invalid}")

    if niveau and niveau not in VALID_NIVEAUX:
        raise HTTPException(status_code=422, detail=f"Invalid niveau: {niveau}. Must be one of {VALID_NIVEAUX}")

    if sort not in VALID_SORTS:
        raise HTTPException(status_code=422, detail=f"Invalid sort: {sort}. Must be one of {sorted(VALID_SORTS)}")

    # ── Cache Redis ────────────────────────────────────────────────────────────
    cache_key = _events_cache_key(
        bbox=bbox, categories=categories, gravite_min=gravite_min, niveau=niveau,
        depuis=depuis, avant=avant, q=q, limit=limit, offset=offset, full=full,
        national_only=national_only, dept=dept, sort=sort,
    )
    redis = await _get_redis()
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return EventList.model_validate_json(cached)
        except Exception:
            pass  # Cache miss ou erreur Redis : on continue normalement
    # ──────────────────────────────────────────────────────────────────────────

    since_dt = depuis or (datetime.now(timezone.utc) - timedelta(hours=settings.DEFAULT_SINCE_HOURS))
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=timezone.utc)

    stmt = select(Event).where(Event.date_publication >= since_dt)

    if avant:
        if avant.tzinfo is None:
            avant = avant.replace(tzinfo=timezone.utc)
        stmt = stmt.where(Event.date_publication <= avant)

    if categories:
        stmt = stmt.where(Event.categorie.in_(categories))

    if gravite_min is not None:
        stmt = stmt.where(Event.gravite >= gravite_min)

    if niveau:
        stmt = stmt.where(Event.lieu_niveau == niveau)

    if national_only:
        stmt = stmt.where(Event.geom.is_(None))

    dept = _validate_dept(dept)
    if dept:
        stmt = stmt.where(Event.lieu_code_insee.like(f"{dept}%"))

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

    # Ordre de tri (défaut 'gravite' = comportement historique).
    # Date bornée à now() : les événements datés dans le futur (vigilances J1
    # « pour demain ») sont triés comme publiés à l'instant — sinon ils
    # squattent la tête du tri 'recent' et reçoivent un bonus en 'pertinence'
    # (âge négatif → score gonflé). Même correctif que sortEvents.ts côté front.
    effective_date = func.least(Event.date_publication, func.now())
    if sort == "recent":
        order_by = (effective_date.desc(), Event.gravite.desc())
    elif sort == "pertinence":
        # Score de fraîcheur : la gravité perd ~1 point par jour écoulé, si bien
        # qu'une alerte ancienne ne squatte plus le haut du fil indéfiniment.
        age_days = func.extract("epoch", func.now() - effective_date) / 86400.0
        order_by = ((Event.gravite - age_days).desc(), effective_date.desc())
    else:  # "gravite"
        order_by = (Event.gravite.desc(), effective_date.desc())

    # Une seule requête : la fonction fenêtre count() OVER() renvoie le total
    # filtré sur chaque ligne, ce qui évite un second passage des prédicats WHERE
    # (un COUNT séparé doublait l'évaluation du filtre, bbox spatial compris).
    stmt = (
        stmt.add_columns(func.count().over().label("total_count"))
        .order_by(*order_by)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()
    events = [row[0] for row in rows]
    total = rows[0].total_count if rows else 0

    payload = [EventBase.model_validate(e) for e in events]
    if not full:
        for item in payload:
            item.resume_ia = _truncate_resume(item.resume_ia)

    response = EventList(
        events=payload,
        total=total,
        generated_at=datetime.now(timezone.utc),
        offset=offset,
        has_more=offset + len(events) < total,
    )

    # Écriture en cache Redis (TTL configurable, défaut 120s).
    if redis:
        try:
            await redis.set(cache_key, response.model_dump_json(), ex=settings.REDIS_EVENTS_TTL)
        except Exception:
            pass

    return response


@router.get("/events/map")
async def list_events_for_map(
    categories: Optional[list[str]] = Query(None),
    gravite_min: Optional[int] = Query(None, ge=0, le=3),
    depuis: Optional[datetime] = Query(None),
    limit: int = Query(default=settings.MAX_EVENTS_LIMIT, ge=1, le=settings.MAX_EVENTS_LIMIT),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Marqueurs de la carte — uniquement les événements localisés.

    Le fil est paginé (200 par page) mais la carte doit rester complète : la
    faire dépendre de cette pagination reviendrait à demander à l'utilisateur
    de « charger plus » pour voir ses points. Cette réponse omet le champ le
    plus lourd (`resume_ia`, ~40 % de la charge utile) : la fiche complète
    reste accessible via GET /events/{id} au clic.
    """
    if categories:
        invalid = [c for c in categories if c not in VALID_CATEGORIES]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid categories: {invalid}")

    since_dt = depuis or (datetime.now(timezone.utc) - timedelta(hours=settings.DEFAULT_SINCE_HOURS))
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=timezone.utc)

    stmt = (
        select(
            Event.id, Event.titre, Event.source, Event.auteur, Event.source_url,
            Event.date_publication, Event.categorie, Event.gravite,
            Event.lieu_nom, Event.lieu_code_insee, Event.lieu_lat, Event.lieu_lon,
            Event.lieu_niveau, Event.cluster_id,
        )
        .where(
            Event.date_publication >= since_dt,
            # Seuls les points plaçables : inutile de transporter les
            # événements nationaux, la carte ne peut rien en faire.
            Event.lieu_lat.isnot(None),
            Event.lieu_lon.isnot(None),
        )
        .order_by(Event.gravite.desc(), Event.date_publication.desc())
        .limit(limit)
    )
    if categories:
        stmt = stmt.where(Event.categorie.in_(categories))
    if gravite_min is not None:
        stmt = stmt.where(Event.gravite >= gravite_min)

    rows = (await db.execute(stmt)).all()
    return {
        "events": [
            {
                "id": r.id,
                "titre": r.titre,
                "source": r.source,
                "auteur": r.auteur,
                "source_url": r.source_url,
                "date_publication": r.date_publication.isoformat(),
                "categorie": r.categorie,
                "gravite": r.gravite,
                "lieu_nom": r.lieu_nom,
                "lieu_code_insee": r.lieu_code_insee,
                "lieu_lat": r.lieu_lat,
                "lieu_lon": r.lieu_lon,
                "lieu_niveau": r.lieu_niveau,
                "cluster_id": r.cluster_id,
                # Champs absents volontairement (voir docstring) : resume_ia,
                # tags, score_confiance, created_at, date_evenement.
            }
            for r in rows
        ],
        "total": len(rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


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


def _require_ingest_key(x_api_key: Optional[str]) -> None:
    """Auth partagée des déclencheurs de pipeline (ingestion, brief).

    Si INGEST_API_KEY est configuré, le header X-Api-Key est requis. En
    production, l'absence de clé verrouille l'endpoint (fail-closed) : on refuse
    plutôt que d'exposer un déclencheur non authentifié sur le net.
    """
    if not settings.INGEST_API_KEY:
        if settings.APP_ENV == "production":
            raise HTTPException(
                status_code=503,
                detail="Endpoint désactivé : INGEST_API_KEY non configuré en production",
            )
        return  # dev/test : pas de clé requise.
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.INGEST_API_KEY):
        raise HTTPException(status_code=401, detail="X-Api-Key manquant ou incorrect")


async def _ingest_then_brief() -> None:
    """Ingestion complète puis régénération du brief, pour que le brief reflète
    immédiatement les nouveaux événements (sinon il n'est rafraîchi qu'aux
    créneaux cron 9h/13h/20h ou au redémarrage)."""
    from app.pipeline.brief import generate_daily_brief

    await ingest_all()
    try:
        await generate_daily_brief()
    except Exception as exc:  # le brief ne doit jamais faire échouer l'ingestion
        logger.warning("Régénération du brief après ingestion échouée : %s", exc)


@router.post("/ingest/run")
async def trigger_ingest(
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None),
) -> dict:
    """Déclenche manuellement l'ingestion de tous les connecteurs, puis régénère
    le brief. Idempotent : si une ingestion est déjà en cours, le déclenchement
    est ignoré (ingest_all pose un verrou global) afin d'éviter tout empilement.
    """
    _require_ingest_key(x_api_key)
    if ingestion_in_progress():
        return {"status": "already_running", "message": "Une ingestion est déjà en cours"}
    background_tasks.add_task(_ingest_then_brief)
    return {"status": "started", "message": "Ingestion + brief déclenchés en arrière-plan"}


@router.post("/brief/run")
async def trigger_brief(
    background_tasks: BackgroundTasks,
    x_api_key: Optional[str] = Header(None),
) -> dict:
    """Régénère le brief à la demande (sans relancer l'ingestion)."""
    from app.pipeline.brief import generate_daily_brief

    _require_ingest_key(x_api_key)
    background_tasks.add_task(generate_daily_brief)
    return {"status": "started", "message": "Génération du brief déclenchée en arrière-plan"}


@router.get("/events/timeline")
async def get_timeline(
    depuis: Optional[datetime] = Query(None, description="Date de début (défaut: 30 jours)"),
    avant: Optional[datetime] = Query(None, description="Date de fin (défaut: maintenant)"),
    categories: Optional[list[str]] = Query(None),
    gravite_min: Optional[int] = Query(None, ge=0, le=3),
    bucket: str = Query(default="day", description="Granularité : 'hour' ou 'day'"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Compte d'événements agrégés par bucket temporel — pour le mini-histogramme."""
    now = datetime.now(timezone.utc)
    since_dt = depuis or (now - timedelta(days=30))
    until_dt = avant or now
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=timezone.utc)
    if until_dt.tzinfo is None:
        until_dt = until_dt.replace(tzinfo=timezone.utc)

    trunc_expr = func.date_trunc("hour" if bucket == "hour" else "day", Event.date_publication)
    stmt = (
        select(
            trunc_expr.label("bucket"),
            func.count().label("count"),
            func.max(Event.gravite).label("max_gravite"),
        )
        .where(Event.date_publication >= since_dt, Event.date_publication <= until_dt)
        .group_by("bucket")
        .order_by("bucket")
    )
    if categories:
        invalid = [c for c in categories if c not in VALID_CATEGORIES]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid categories: {invalid}")
        stmt = stmt.where(Event.categorie.in_(categories))
    if gravite_min is not None:
        stmt = stmt.where(Event.gravite >= gravite_min)

    rows = await db.execute(stmt)
    buckets = [
        {"time": row.bucket.isoformat(), "count": row.count, "max_gravite": row.max_gravite}
        for row in rows
    ]
    return {
        "since": since_dt.isoformat(),
        "until": until_dt.isoformat(),
        "bucket": bucket,
        "buckets": buckets,
    }


# IMPORTANT : cette route doit etre declaree AVANT /events/{event_id}.
# Starlette resout les routes dans l'ordre de declaration : sinon
# GET /api/events/stream est capture par /events/{event_id} qui tente de
# parser "stream" comme un UUID -> 422, et le flux SSE temps reel ne se
# connecte jamais.
@router.get("/events/stream")
async def stream_events(
    categories: Optional[list[str]] = Query(None),
    gravite_min: Optional[int] = Query(None, ge=0, le=3),
    request: Request = None,
) -> StreamingResponse:
    """SSE : pousse les nouveaux événements en temps réel (polling DB toutes les 30s).

    Le client reçoit immédiatement un event ``connected``, puis un event
    ``events`` dès qu'au moins un événement nouveau apparaît, ou un ``ping``
    pour maintenir la connexion ouverte.
    """
    from app.database import AsyncSessionLocal

    if categories:
        invalid = [c for c in categories if c not in VALID_CATEGORIES]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid categories: {invalid}")

    # Pré-contrôle : refuse d'emblée un flux de plus quand le plafond est
    # atteint, pour répondre un vrai 503 (le client retombe sur le polling SWR).
    # La comptabilité réelle, elle, se fait DANS le générateur : réservée ici,
    # une place n'aurait jamais été rendue si le flux n'était pas consommé — le
    # compteur ne redescendait plus et le temps réel restait fermé jusqu'au
    # redémarrage.
    if _sse_active_connections >= settings.MAX_SSE_CONNECTIONS:
        raise HTTPException(
            status_code=503,
            detail="Trop de connexions temps réel simultanées, réessayez plus tard",
        )

    async def generate():
        last_seen = datetime.now(timezone.utc)
        if not _acquire_sse_slot():
            yield ("event: error\ndata: "
                   + json.dumps({"reason": "too_many_connections"}) + "\n\n")
            return
        try:
            yield f"event: connected\ndata: {json.dumps({'ts': last_seen.isoformat()})}\n\n"

            while True:
                if request and await request.is_disconnected():
                    break
                await asyncio.sleep(30)
                try:
                    async with AsyncSessionLocal() as session:
                        stmt = (
                            select(Event)
                            .where(Event.created_at > last_seen)
                            .order_by(Event.created_at.asc())
                            .limit(50)
                        )
                        if categories:
                            stmt = stmt.where(Event.categorie.in_(categories))
                        if gravite_min is not None:
                            stmt = stmt.where(Event.gravite >= gravite_min)

                        result = await session.execute(stmt)
                        found = result.scalars().all()

                        if found:
                            last_seen = max(e.created_at for e in found)
                            yield f"event: events\ndata: {json.dumps([_event_to_dict(e) for e in found])}\n\n"
                        else:
                            yield "event: ping\ndata: {}\n\n"
                except Exception as exc:
                    logger.warning("SSE stream error: %s", exc)
                    yield "event: ping\ndata: {}\n\n"
        finally:
            # Libère le créneau quand le client se déconnecte ou que le flux se
            # termine, quelle qu'en soit la raison.
            _release_sse_slot()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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


@router.get("/trends")
async def get_trends(db: AsyncSession = Depends(get_db)) -> dict:
    """Catégories en tendance : pic d'activité dans les 2 dernières heures vs les 24h."""
    now = datetime.now(timezone.utc)
    h2_ago = now - timedelta(hours=2)
    h24_ago = now - timedelta(hours=24)

    r2h = await db.execute(
        select(Event.categorie, func.count().label("cnt"))
        .where(Event.date_publication >= h2_ago)
        .group_by(Event.categorie)
    )
    counts_2h = {row.categorie: row.cnt for row in r2h}

    r24h = await db.execute(
        select(Event.categorie, func.count().label("cnt"))
        .where(Event.date_publication >= h24_ago)
        .group_by(Event.categorie)
    )
    counts_24h = {row.categorie: row.cnt for row in r24h}

    trends = []
    for cat, cnt_2h in counts_2h.items():
        cnt_24h = counts_24h.get(cat, 0)
        avg_per_2h = cnt_24h / 12
        if cnt_2h >= 3 and avg_per_2h > 0 and cnt_2h >= avg_per_2h * 2:
            trends.append({
                "categorie": cat,
                "recent_count": cnt_2h,
                "daily_avg_per_2h": round(avg_per_2h, 1),
                "ratio": round(cnt_2h / max(avg_per_2h, 0.1), 1),
            })

    trends.sort(key=lambda x: -x["ratio"])
    return {"trends": trends, "generated_at": now.isoformat()}


@router.get("/brief")
async def get_brief() -> dict:
    """Retourne le dernier brief matinal généré par Mistral."""
    from app.pipeline.brief import get_latest_brief
    brief = await get_latest_brief()
    if brief is None:
        return {"brief": None, "message": "Aucun brief disponible. Le prochain sera généré à 09h00."}
    return brief


@router.get("/brief/local")
async def get_local_brief(
    dept: str = Query(..., max_length=3, description="Code département (75, 2A, 971…)"),
    heures: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Volet local du brief : ce qu'il faut retenir dans un département.

    Déterministe et sans appel LLM — le brief national est déjà généré trois
    fois par jour, régénérer un texte par département coûterait 101 appels par
    cycle pour une valeur marginale. On renvoie les faits saillants (les plus
    graves d'abord) et la répartition par catégorie ; la mise en forme est du
    ressort de l'interface.
    """
    dept = _validate_dept(dept) or ""

    since = datetime.now(timezone.utc) - timedelta(hours=heures)
    base = (
        Event.date_publication >= since,
        Event.lieu_code_insee.like(f"{dept}%"),
    )

    rows = (
        await db.execute(
            select(Event)
            .where(*base)
            .order_by(Event.gravite.desc(), Event.date_publication.desc())
            .limit(5)
        )
    ).scalars().all()

    par_cat = (
        await db.execute(
            select(Event.categorie, func.count().label("n"))
            .where(*base)
            .group_by(Event.categorie)
            .order_by(func.count().desc())
        )
    ).all()

    total = sum(r.n for r in par_cat)
    return {
        "dept": dept,
        "heures": heures,
        "total": total,
        "par_categorie": {r.categorie: r.n for r in par_cat},
        "faits": [
            {
                "id": e.id,
                "titre": e.titre,
                "categorie": e.categorie,
                "gravite": e.gravite,
                "lieu_nom": e.lieu_nom,
                "source_url": e.source_url,
                "date_publication": e.date_publication.isoformat(),
            }
            for e in rows
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/brief/history")
async def get_brief_history(
    limit: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Archive des briefs : la table DailyBrief conserve tout l'historique,
    mais seul le dernier était exposé jusqu'ici."""
    from app.models import DailyBrief

    rows = (
        await db.execute(
            select(DailyBrief).order_by(DailyBrief.generated_at.desc()).limit(limit)
        )
    ).scalars().all()
    return {
        "briefs": [
            {
                "date": b.date.isoformat(),
                "content": b.content,
                "event_count": b.event_count,
                "generated_at": b.generated_at.isoformat(),
            }
            for b in rows
        ]
    }


# ── Flux Atom RSS ─────────────────────────────────────────────────────────────

_ATOM_NS = "http://www.w3.org/2005/Atom"
ET.register_namespace("", _ATOM_NS)


def _build_atom(events: list[Event], self_url: str) -> str:
    """Construit un flux Atom 1.0 à partir d'une liste d'événements."""
    def _tag(name: str) -> str:
        return f"{{{_ATOM_NS}}}{name}"

    feed = ET.Element(_tag("feed"))
    ET.SubElement(feed, _tag("title")).text = "FAIRE Info — Actualités"
    self_link = ET.SubElement(feed, _tag("link"))
    self_link.set("rel", "self")
    self_link.set("href", self_url)
    self_link.set("type", "application/atom+xml")
    alt_link = ET.SubElement(feed, _tag("link"))
    alt_link.set("rel", "alternate")
    alt_link.set("href", self_url.split("/api/")[0] if "/api/" in self_url else self_url)

    updated = events[0].date_publication.isoformat() if events else datetime.now(timezone.utc).isoformat()
    ET.SubElement(feed, _tag("updated")).text = updated
    ET.SubElement(feed, _tag("id")).text = self_url

    for e in events:
        entry = ET.SubElement(feed, _tag("entry"))
        ET.SubElement(entry, _tag("id")).text = e.source_url
        ET.SubElement(entry, _tag("title")).text = e.titre
        ET.SubElement(entry, _tag("updated")).text = e.date_publication.isoformat()
        link = ET.SubElement(entry, _tag("link"))
        link.set("href", e.source_url)
        link.set("rel", "alternate")
        summary = ET.SubElement(entry, _tag("summary"))
        summary.text = e.resume_ia or e.titre
        cat_el = ET.SubElement(entry, _tag("category"))
        cat_el.set("term", e.categorie)
        if e.lieu_nom and e.lieu_nom != "national":
            loc_el = ET.SubElement(entry, _tag("category"))
            loc_el.set("term", e.lieu_nom)
        if e.auteur:
            author = ET.SubElement(entry, _tag("author"))
            ET.SubElement(author, _tag("name")).text = e.auteur

    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(feed, encoding="unicode")


@router.get("/feed.rss")
async def atom_feed(
    request: Request,
    categories: Optional[list[str]] = Query(None),
    gravite_min: Optional[int] = Query(None, ge=0, le=3),
    dept: Optional[str] = Query(None, max_length=3),
    depuis_heures: int = Query(default=48, ge=1, le=720),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> HTTPResponse:
    """Flux Atom 1.0 des événements récents. Filtrable par catégorie, gravité, département."""
    if categories:
        invalid = [c for c in categories if c not in VALID_CATEGORIES]
        if invalid:
            raise HTTPException(status_code=422, detail=f"Invalid categories: {invalid}")

    since_dt = datetime.now(timezone.utc) - timedelta(hours=depuis_heures)
    stmt = select(Event).where(Event.date_publication >= since_dt)
    if categories:
        stmt = stmt.where(Event.categorie.in_(categories))
    if gravite_min is not None:
        stmt = stmt.where(Event.gravite >= gravite_min)
    dept = _validate_dept(dept)
    if dept:
        stmt = stmt.where(Event.lieu_code_insee.like(f"{dept}%"))
    stmt = stmt.order_by(Event.gravite.desc(), Event.date_publication.desc()).limit(limit)

    rows = await db.execute(stmt)
    events = list(rows.scalars().all())

    xml_content = _build_atom(events, str(request.url))
    return HTTPResponse(
        content=xml_content,
        media_type="application/atom+xml; charset=utf-8",
    )


# ── Stats géographiques ───────────────────────────────────────────────────────

@router.get("/stats/geo")
async def get_geo_stats(
    since_hours: int = Query(default=24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Répartition des événements par département sur la période demandée.

    Retourne les départements actifs triés par nombre d'événements décroissant,
    avec le niveau de gravité maximal observé sur la période.
    """
    since_dt = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    # Codes DOM-TOM sur 3 chiffres (971…988), départements métropolitains sur 2
    # (dont Corse « 2A »/« 2B »). Un `left(insee, 2)` uniforme fusionnait tous les
    # outre-mer sous « 97 » — la carte utilise déjà des codes à 3 chiffres pour
    # ces territoires (cf. deptCodeFromInsee côté frontend).
    dept_col = case(
        (Event.lieu_code_insee.like("97%"), func.left(Event.lieu_code_insee, 3)),
        (Event.lieu_code_insee.like("98%"), func.left(Event.lieu_code_insee, 3)),
        else_=func.left(Event.lieu_code_insee, 2),
    ).label("dept")
    stmt = (
        select(
            dept_col,
            func.count().label("event_count"),
            func.max(Event.gravite).label("gravite_max"),
        )
        .where(
            Event.date_publication >= since_dt,
            Event.lieu_code_insee.isnot(None),
            Event.lieu_niveau.in_(["commune", "departement"]),
        )
        .group_by(dept_col)
        .order_by(func.count().desc())
        .limit(101)  # 96 depts + DOM-TOM
    )
    rows = await db.execute(stmt)
    departments = [
        {"code": row.dept, "event_count": row.event_count, "gravite_max": row.gravite_max}
        for row in rows
        if row.dept and len(row.dept) in (2, 3)
    ]
    return {
        "since_hours": since_hours,
        "departments": departments,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/stats/history")
async def get_stats_history(
    days: int = Query(default=90, ge=1, le=730),
    categorie: str | None = Query(default=None, max_length=64),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Séries quotidiennes agrégées (jour × catégorie × département).

    Contrairement aux événements bruts (purgés après 36 h – 30 j), ces agrégats
    sont conservés indéfiniment : ils permettent les tendances longues.
    Département vide = événement national/non localisé.
    """
    from app.models import DailyStat

    since = datetime.now(timezone.utc).date() - timedelta(days=days)
    stmt = (
        select(DailyStat.jour, DailyStat.categorie, DailyStat.departement, DailyStat.count)
        .where(DailyStat.jour >= since)
        .order_by(DailyStat.jour.asc(), DailyStat.categorie.asc())
    )
    if categorie:
        stmt = stmt.where(DailyStat.categorie == categorie)
    rows = await db.execute(stmt)
    return {
        "days": days,
        "stats": [
            {
                "jour": r.jour.isoformat(),
                "categorie": r.categorie,
                "departement": r.departement,
                "count": r.count,
            }
            for r in rows
        ],
    }


# ── SSE : flux temps réel ─────────────────────────────────────────────────────

def _event_to_dict(e: Event) -> dict:
    return {
        "id": e.id,
        "source": e.source,
        "source_url": e.source_url,
        "titre": e.titre,
        "auteur": e.auteur,
        "date_publication": e.date_publication.isoformat(),
        "date_evenement": e.date_evenement.isoformat() if e.date_evenement else None,
        "categorie": e.categorie,
        "gravite": e.gravite,
        "lieu_nom": e.lieu_nom,
        "lieu_code_insee": e.lieu_code_insee,
        "lieu_lat": e.lieu_lat,
        "lieu_lon": e.lieu_lon,
        "lieu_niveau": e.lieu_niveau,
        "lieu_confiance_geo": float(e.lieu_confiance_geo or 0),
        "resume_ia": e.resume_ia,
        "tags": e.tags or [],
        "cluster_id": e.cluster_id,
        "score_confiance": float(e.score_confiance or 1.0),
        "created_at": e.created_at.isoformat(),
    }
