import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func

from app.database import AsyncSessionLocal
from app.models import Event

logger = logging.getLogger(__name__)

# TTL en heures par source
TTL_HOURS: dict[str, int] = {
    "meteo_france": 36,   # remplacé à chaque ingestion
    "vigicrues":    36,
    "renass":       720,  # 30 jours — données sismiques historiquement utiles
    "presse_rss":   72,   # 3 jours pour la presse
}
DEFAULT_TTL_HOURS = 72


async def purge_old_events() -> int:
    """Supprime les événements plus anciens que leur TTL. Retourne le nombre supprimé."""
    now = datetime.now(timezone.utc)
    total_deleted = 0

    # Collect all known sources from TTL_HOURS plus a generic pass for unknown sources
    sources_to_purge: dict[str, int] = dict(TTL_HOURS)

    async with AsyncSessionLocal() as session:
        try:
            for source, ttl_h in sources_to_purge.items():
                cutoff = now - timedelta(hours=ttl_h)
                # `greatest(date_publication, created_at)` : le TTL court à
                # partir du plus récent des deux. Sur la seule date de
                # publication, un article rétro-daté par son flux (reprise
                # d'archive, date de parsing erronée) était supprimé dès la
                # purge suivant son ingestion — visible quelques heures puis
                # disparu sans raison apparente.
                stmt = (
                    delete(Event)
                    .where(Event.source == source)
                    .where(func.greatest(Event.date_publication, Event.created_at) < cutoff)
                )
                result = await session.execute(stmt)
                deleted = result.rowcount
                if deleted:
                    logger.info(
                        "Purged %d events from source '%s' (TTL=%dh, cutoff=%s)",
                        deleted, source, ttl_h, cutoff.isoformat(),
                    )
                total_deleted += deleted

            # Purge unknown sources with the default TTL
            default_cutoff = now - timedelta(hours=DEFAULT_TTL_HOURS)
            known_sources = list(sources_to_purge.keys())
            stmt_default = (
                delete(Event)
                .where(Event.source.not_in(known_sources))
                .where(func.greatest(Event.date_publication, Event.created_at) < default_cutoff)
            )
            result_default = await session.execute(stmt_default)
            deleted_default = result_default.rowcount
            if deleted_default:
                logger.info(
                    "Purged %d events from other sources (default TTL=%dh, cutoff=%s)",
                    deleted_default, DEFAULT_TTL_HOURS, default_cutoff.isoformat(),
                )
            total_deleted += deleted_default

            await session.commit()
        except Exception:
            await session.rollback()
            raise

    logger.info("Purge complete: %d events deleted total", total_deleted)
    return total_deleted
