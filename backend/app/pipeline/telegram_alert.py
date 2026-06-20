"""Envoi d'alertes Telegram pour les événements de gravité >= 2.

Active seulement si TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID sont définis.
Chaque événement est envoyé une seule fois grâce à un set en mémoire des IDs
déjà notifiés (reset au redémarrage — les événements existants ne sont pas
re-notifiés au démarrage, uniquement les nouveaux insérés pendant la session).
"""
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_GRAVITE_EMOJI = {0: "ℹ️", 1: "⚠️", 2: "🔶", 3: "🆘"}
_CAT_EMOJI = {
    "meteo": "⛈", "crue": "🌊", "seisme": "🌍", "energie": "⚡",
    "sante": "🏥", "transport": "🚆", "ordre_public": "🚨",
    "actualite": "📰", "incendie": "🔥",
}

_notified_ids: set[str] = set()


def _is_enabled() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def _format_message(event: dict[str, Any]) -> str:
    g = int(event.get("gravite", 0))
    cat = event.get("categorie", "actualite")
    emoji_g = _GRAVITE_EMOJI.get(g, "ℹ️")
    emoji_c = _CAT_EMOJI.get(cat, "📰")
    titre = event.get("titre", "")[:200]
    lieu = event.get("lieu_nom") or "France"
    resume = event.get("resume_ia") or ""
    url = event.get("source_url", "")

    lines = [
        f"{emoji_g} {emoji_c} *{titre}*",
        f"📍 {lieu}",
    ]
    if resume and resume != titre:
        lines.append(f"_{resume[:300]}_")
    if url:
        lines.append(f"[Lire la suite]({url})")
    return "\n".join(lines)


async def send_alerts(new_events: list[dict[str, Any]]) -> None:
    """Envoie sur Telegram les nouveaux événements gravité >= 2 non encore notifiés."""
    if not _is_enabled():
        return

    to_notify = [
        e for e in new_events
        if int(e.get("gravite", 0)) >= 2 and e.get("id") not in _notified_ids
    ]
    if not to_notify:
        return

    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        for event in to_notify:
            try:
                resp = await client.post(url, json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": _format_message(event),
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                })
                resp.raise_for_status()
                if event.get("id"):
                    _notified_ids.add(event["id"])
                logger.info("Telegram alert sent for event '%s'", event.get("titre", "")[:60])
            except Exception as exc:
                logger.warning("Telegram alert failed for '%s': %s", event.get("titre", "")[:60], exc)
