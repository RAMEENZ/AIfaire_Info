import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.models import Event, ConnectorStatus
from app.connectors.meteo_france import MeteoFranceConnector
from app.connectors.vigicrues import VigicruesConnector
from app.connectors.renass import RenassConnector
from app.connectors.enedis import EnedisConnector
from app.connectors.presse_rss import PresseRSSConnector
from app.pipeline.extractor import maybe_extract
from app.pipeline.geocoder import geocode

logger = logging.getLogger(__name__)

CONNECTORS = [
    MeteoFranceConnector(),
    VigicruesConnector(),
    RenassConnector(),
    EnedisConnector(),
    PresseRSSConnector(),
]


def _build_event(item: dict[str, Any], geo: dict[str, Any]) -> dict[str, Any]:
    lat = item.get("lieu_lat") or geo.get("lat")
    lon = item.get("lieu_lon") or geo.get("lon")

    geom = None
    if lat is not None and lon is not None:
        geom = f"SRID=4326;POINT({lon} {lat})"

    confiance_geo = item.get("lieu_confiance_geo") or geo.get("confiance_geo", 0.0)
    niveau = geo.get("niveau") or item.get("lieu_niveau", "national")
    code_insee = item.get("lieu_code_insee") or geo.get("code_insee")

    if lat is None:
        niveau = "national"
        confiance_geo = 0.0

    date_pub_raw = item.get("date_publication")
    if isinstance(date_pub_raw, str):
        try:
            date_pub = datetime.fromisoformat(date_pub_raw.replace("Z", "+00:00"))
        except ValueError:
            date_pub = datetime.now(timezone.utc)
    elif isinstance(date_pub_raw, datetime):
        date_pub = date_pub_raw
    else:
        date_pub = datetime.now(timezone.utc)

    if date_pub.tzinfo is None:
        date_pub = date_pub.replace(tzinfo=timezone.utc)

    date_evt_raw = item.get("date_evenement")
    date_evt = None
    if date_evt_raw:
        if isinstance(date_evt_raw, str):
            try:
                date_evt = datetime.fromisoformat(date_evt_raw.replace("Z", "+00:00"))
            except ValueError:
                pass
        elif isinstance(date_evt_raw, datetime):
            date_evt = date_evt_raw
        if date_evt and date_evt.tzinfo is None:
            date_evt = date_evt.replace(tzinfo=timezone.utc)

    return {
        "source": item["source"],
        "source_url": item["source_url"],
        "titre": item.get("titre", "")[:2000],
        "auteur": item.get("auteur"),
        "date_publication": date_pub,
        "date_evenement": date_evt,
        "categorie": item.get("categorie", "actualite"),
        "gravite": int(item.get("gravite", 0)),
        "lieu_nom": item.get("lieu_nom"),
        "lieu_code_insee": str(code_insee) if code_insee else None,
        "lieu_lat": lat,
        "lieu_lon": lon,
        "lieu_niveau": niveau,
        "lieu_confiance_geo": float(confiance_geo),
        "geom": geom,
        "resume_ia": item.get("resume_ia"),
        "cluster_id": None,
        "score_confiance": float(item.get("score_confiance", 1.0)),
    }


async def _process_item(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        item = await maybe_extract(item)

        if item.get("skip_geocoding"):
            geo: dict[str, Any] = {
                "lat": item.get("lieu_lat"),
                "lon": item.get("lieu_lon"),
                "code_insee": item.get("lieu_code_insee"),
                "niveau": item.get("lieu_niveau", "commune"),
                "confiance_geo": item.get("lieu_confiance_geo", 1.0),
            }
        else:
            lieu_nom = item.get("lieu_nom")
            geo = await geocode(lieu_nom)

        return _build_event(item, geo)
    except Exception as exc:
        logger.error("Failed to process item '%s': %s", item.get("source_url", "?"), exc, exc_info=True)
        return None


async def _upsert_connector_status(
    name: str,
    last_run: datetime,
    last_error: str | None,
    count: int,
) -> None:
    async with AsyncSessionLocal() as session:
        try:
            stmt = pg_insert(ConnectorStatus).values(
                name=name,
                last_run=last_run,
                last_error=last_error,
                last_count=count,
                updated_at=datetime.now(timezone.utc),
            ).on_conflict_do_update(
                index_elements=["name"],
                set_={
                    "last_run": last_run,
                    "last_error": last_error,
                    "last_count": count,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            await session.execute(stmt)
            await session.commit()
        except Exception as exc:
            logger.error("Failed to update connector status for %s: %s", name, exc)
            await session.rollback()


async def _save_events(events: list[dict[str, Any]]) -> int:
    if not events:
        return 0

    saved = 0
    async with AsyncSessionLocal() as session:
        try:
            urls = [e["source_url"] for e in events]
            existing_stmt = select(Event.source_url).where(Event.source_url.in_(urls))
            existing_result = await session.execute(existing_stmt)
            existing_urls: set[str] = {row[0] for row in existing_result}

            new_events = [e for e in events if e["source_url"] not in existing_urls]

            for evt_data in new_events:
                try:
                    event = Event(**evt_data)
                    session.add(event)
                    saved += 1
                except Exception as exc:
                    logger.warning("Failed to create event for '%s': %s", evt_data.get("source_url"), exc)
                    continue

            await session.commit()
        except Exception as exc:
            logger.error("Failed to save events batch: %s", exc, exc_info=True)
            await session.rollback()

    return saved


_GEO_SEMAPHORE = asyncio.Semaphore(8)  # max 8 items traitables en parallèle (geocoding API)


async def _process_item_limited(item: dict[str, Any]) -> dict[str, Any] | None:
    async with _GEO_SEMAPHORE:
        return await _process_item(item)


async def _delete_source_events(source: str) -> int:
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(delete(Event).where(Event.source == source))
            await session.commit()
            return result.rowcount
        except Exception as exc:
            await session.rollback()
            logger.error("Failed to delete events for source %s: %s", source, exc)
            return 0


async def ingest_connector(connector: Any) -> tuple[str, int, str | None]:
    raw_items = await connector.run()

    if connector.replace_on_ingest and raw_items:
        deleted = await _delete_source_events(connector.name)
        logger.info("replace_on_ingest: deleted %d old %s events", deleted, connector.name)

    process_tasks = [_process_item_limited(item) for item in raw_items]
    processed = await asyncio.gather(*process_tasks, return_exceptions=True)

    valid_events: list[dict[str, Any]] = []
    for r in processed:
        if isinstance(r, Exception):
            logger.warning("Processing raised exception: %s", r)
        elif r is not None:
            valid_events.append(r)

    saved = await _save_events(valid_events)

    await _upsert_connector_status(
        name=connector.name,
        last_run=connector.last_run or datetime.now(timezone.utc),
        last_error=connector.last_error,
        count=saved,
    )

    logger.info("Connector %s: %d raw → %d saved", connector.name, len(raw_items), saved)
    return connector.name, saved, connector.last_error


async def ingest_all() -> dict[str, Any]:
    logger.info("Starting full ingestion pipeline")
    start = datetime.now(timezone.utc)

    tasks = [ingest_connector(c) for c in CONNECTORS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    summary: dict[str, Any] = {
        "started_at": start.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "connectors": {},
    }

    for r in results:
        if isinstance(r, Exception):
            logger.error("Connector task raised: %s", r, exc_info=r)
        else:
            name, saved, error = r
            summary["connectors"][name] = {"saved": saved, "error": error}

    total = sum(v["saved"] for v in summary["connectors"].values())
    summary["total_saved"] = total
    logger.info("Ingestion complete: %d events saved", total)
    return summary
