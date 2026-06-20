import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.models import Event, ConnectorStatus
from app.connectors.meteo_france import MeteoFranceConnector
from app.connectors.vigicrues import VigicruesConnector
from app.connectors.renass import RenassConnector
from app.connectors.enedis import EnedisConnector
from app.connectors.presse_rss import PresseRSSConnector
from app.connectors.sncf import SNCFConnector
from app.connectors.bison_fute import BisonFuteConnector
from app.connectors.incendies import IncendiesConnector
from app.connectors.cert_fr import CertFrConnector
from app.connectors.irsn import IRSNConnector
from app.connectors.air_quality import AirQualityConnector
from app.pipeline.extractor import maybe_extract
from app.pipeline.geocoder import geocode

logger = logging.getLogger(__name__)

CONNECTORS = [
    MeteoFranceConnector(),
    VigicruesConnector(),
    RenassConnector(),
    EnedisConnector(),
    PresseRSSConnector(),
    SNCFConnector(),
    BisonFuteConnector(),
    IncendiesConnector(),
    CertFrConnector(),
    IRSNConnector(),
    AirQualityConnector(),
]


_GEO_COORD_MIN_CONFIDENCE = 0.55  # seuil en-dessous duquel on refuse de placer sur la carte


def _build_event(item: dict[str, Any], geo: dict[str, Any]) -> dict[str, Any]:
    # Utiliser "is not None" et non "or" : une coordonnée légitime de 0.0
    # (méridien de Greenwich, qui traverse la France) ne doit pas être écartée.
    # Les deux coordonnées sont solidaires : on les prend du connecteur si et
    # seulement si le connecteur a fourni une latitude (les deux vont ensemble).
    connector_has_coords = item.get("lieu_lat") is not None
    lat = item.get("lieu_lat") if connector_has_coords else geo.get("lat")
    lon = item.get("lieu_lon") if connector_has_coords else geo.get("lon")

    _item_conf = item.get("lieu_confiance_geo")
    confiance_geo = _item_conf if _item_conf is not None else geo.get("confiance_geo", 0.0)

    # Si les coordonnées viennent du geocoding (pas du connecteur) et que la
    # confiance est trop faible, on ne les retient pas — évite les faux positifs
    # sur la carte.
    if not connector_has_coords and confiance_geo < _GEO_COORD_MIN_CONFIDENCE:
        lat = None
        lon = None

    geom = None
    if lat is not None and lon is not None:
        geom = f"SRID=4326;POINT({lon} {lat})"

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
        "tags": item.get("tags", []),
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

    # Déduplique par source_url à l'intérieur du lot (un même article peut
    # apparaître dans plusieurs flux) — sinon ON CONFLICT échoue sur le lot.
    deduped: dict[str, dict[str, Any]] = {}
    for e in events:
        deduped[e["source_url"]] = e

    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for evt_data in deduped.values():
        row = dict(evt_data)
        # Les inserts bulk (Core) ne déclenchent pas les defaults Python de l'ORM —
        # on fournit id et created_at explicitement.
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("created_at", now)
        rows.append(row)

    async with AsyncSessionLocal() as session:
        try:
            stmt = (
                pg_insert(Event)
                .values(rows)
                .on_conflict_do_nothing(index_elements=["source_url"])
            )
            result = await session.execute(stmt)
            await session.commit()
            # rowcount = nombre de lignes réellement insérées (les conflits sont ignorés)
            return result.rowcount if result.rowcount is not None else 0
        except Exception as exc:
            logger.error("Failed to save events batch: %s", exc, exc_info=True)
            await session.rollback()
            return 0


# Plafond du nombre d'items traités simultanément. Le vrai back-pressure vient
# des sémaphores internes (geocoder=8, Anthropic=4, Ollama=1, fetch=15) ; ce
# plafond se contente d'éviter une explosion du nombre de coroutines sur de gros
# lots, sans étrangler les items qui ne font ni géocodage ni extraction.
_PROCESS_SEMAPHORE = asyncio.Semaphore(32)


async def _process_item_limited(item: dict[str, Any]) -> dict[str, Any] | None:
    async with _PROCESS_SEMAPHORE:
        return await _process_item(item)


# Taille des lots traités-puis-sauvegardés. Sur une VM CPU, l'enrichissement LLM
# d'un article de presse prend plusieurs secondes : sans sauvegarde incrémentale,
# un run de 120 articles ne commitait qu'au bout de ~12 min, et toute coupure
# (rebuild, redémarrage) perdait l'intégralité du travail. En sauvegardant par
# lots, les événements apparaissent progressivement (~1 min pour le 1er lot) et
# la progression survit à un redémarrage.
_SAVE_BATCH_SIZE = 10


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

    # On ne supprime les anciens événements QUE si le fetch a réussi (last_error
    # est remis à None par run() en cas de succès). Sinon un échec transitoire
    # (5xx amont → liste vide) viderait la carte alors que les alertes en cours
    # sont toujours valides. Une liste vide après un fetch réussi = vrai
    # « retour au calme » → suppression légitime.
    if connector.replace_on_ingest and connector.last_error is None:
        deleted = await _delete_source_events(connector.name)
        logger.info("replace_on_ingest: deleted %d old %s events", deleted, connector.name)
    elif connector.replace_on_ingest:
        logger.warning(
            "replace_on_ingest: skipping delete for %s — fetch failed (%s), keeping existing events",
            connector.name, connector.last_error,
        )

    # Traitement et sauvegarde par lots : les événements sont commités au fur et
    # à mesure (pas seulement en fin de run), pour qu'ils apparaissent vite et
    # survivent à un redémarrage en cours d'ingestion.
    total_saved = 0
    if not raw_items:
        # Aucun item (ex. connecteur replace_on_ingest revenu au calme) : la
        # boucle ne tournerait pas, on met quand même le statut à jour.
        await _upsert_connector_status(
            name=connector.name,
            last_run=connector.last_run or datetime.now(timezone.utc),
            last_error=connector.last_error,
            count=0,
        )
    for batch_start in range(0, len(raw_items), _SAVE_BATCH_SIZE):
        batch = raw_items[batch_start : batch_start + _SAVE_BATCH_SIZE]
        processed = await asyncio.gather(
            *(_process_item_limited(item) for item in batch),
            return_exceptions=True,
        )

        valid_events: list[dict[str, Any]] = []
        for r in processed:
            if isinstance(r, Exception):
                logger.warning("Processing raised exception: %s", r)
            elif r is not None:
                valid_events.append(r)

        total_saved += await _save_events(valid_events)

        # Statut mis à jour à chaque lot : la table ConnectorStatus (lue par
        # /api/health) reflète la progression au lieu de rester vide jusqu'à la
        # fin du run.
        await _upsert_connector_status(
            name=connector.name,
            last_run=connector.last_run or datetime.now(timezone.utc),
            last_error=connector.last_error,
            count=total_saved,
        )

    logger.info("Connector %s: %d raw → %d saved", connector.name, len(raw_items), total_saved)
    return connector.name, total_saved, connector.last_error


# Verrou global : empêche plusieurs ingestions de tourner en parallèle.
# Protège à la fois le job planifié et l'endpoint manuel /ingest/run contre
# l'empilement (déclenchements rapides / cross-origin) qui saturerait la base,
# le pool de connexions et le budget API Anthropic.
_INGEST_LOCK = asyncio.Lock()


def ingestion_in_progress() -> bool:
    return _INGEST_LOCK.locked()


async def ingest_all() -> dict[str, Any]:
    if _INGEST_LOCK.locked():
        logger.info("Ingestion already in progress — skipping this trigger")
        return {"status": "skipped", "reason": "already_running", "total_saved": 0}

    async with _INGEST_LOCK:
        return await _ingest_all_inner()


async def _ingest_all_inner() -> dict[str, Any]:
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
