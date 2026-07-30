"""Alerte de fraîcheur des données : webhook quand plus rien n'est ingéré.

Complément du healthcheck /healthz : autoheal redémarre un backend malade,
mais si le redémarrage ne guérit pas (constaté lors de la panne de 07/2026 —
un restart du backend n'avait rien réglé), la boucle resterait silencieuse.
Ce module notifie le WEBHOOK_URL dès qu'aucun événement n'a été ingéré depuis
HEALTHZ_MAX_DATA_AGE_HOURS, avec un anti-spam (une alerte par période de
cooldown, réarmée dès que les données redeviennent fraîches).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import func, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Event

logger = logging.getLogger(__name__)

_ALERT_COOLDOWN = timedelta(hours=12)

# Import du module ≈ démarrage du processus : pendant la fenêtre de grâce,
# une base vide/périmée est normale (l'ingestion de démarrage n'a pas fini).
_STARTED_AT = datetime.now(timezone.utc)
_last_alert_at: Optional[datetime] = None


def _tz(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def check_data_freshness() -> bool:
    """Vérifie la fraîcheur des données ; envoie le webhook si nécessaire.

    Renvoie True si une alerte a été envoyée (pour les logs/tests).
    """
    global _last_alert_at

    if not settings.WEBHOOK_URL:
        return False

    now = datetime.now(timezone.utc)
    if now - _STARTED_AT < timedelta(minutes=settings.HEALTHZ_BOOT_GRACE_MINUTES):
        return False

    async with AsyncSessionLocal() as session:
        newest = (
            await session.execute(select(func.max(Event.created_at)))
        ).scalar_one()

    threshold = timedelta(hours=settings.HEALTHZ_MAX_DATA_AGE_HOURS)
    stale = newest is None or now - _tz(newest) > threshold
    if not stale:
        # Données fraîches : on réarme, un futur incident alertera immédiatement.
        _last_alert_at = None
        return False

    if _last_alert_at is not None and now - _last_alert_at < _ALERT_COOLDOWN:
        return False

    age = f"{(now - _tz(newest)).total_seconds() / 3600:.0f} h" if newest else "jamais"
    text = (
        f"🚨 FAIRE INFO : aucun événement ingéré depuis {age} "
        f"(seuil : {settings.HEALTHZ_MAX_DATA_AGE_HOURS} h). "
        f"Le pipeline ne produit plus — vérifier `docker compose ps` et les logs."
    )
    payload: dict = {
        "webhook_event": "data_staleness",
        "newest_event_created_at": _tz(newest).isoformat() if newest else None,
        "threshold_hours": settings.HEALTHZ_MAX_DATA_AGE_HOURS,
    }
    url = settings.WEBHOOK_URL
    if "discord.com" in url or "discordapp.com" in url:
        payload["content"] = text
    elif "hooks.slack.com" in url:
        payload["text"] = text
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=payload)
    except Exception as exc:
        logger.warning("Staleness webhook failed: %s", exc)
        return False

    logger.warning("Staleness alert sent (newest event: %s)", newest)
    _last_alert_at = now
    return True
