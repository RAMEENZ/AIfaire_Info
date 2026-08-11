"""Envoi de notifications Web Push aux navigateurs abonnés.

Déclenché après chaque ingestion : les événements graves nouvellement ingérés
sont poussés aux abonnés dont le département et le seuil de gravité
correspondent. Conçu pour ne jamais faire échouer une ingestion — toute erreur
d'envoi est journalisée, jamais propagée.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Event, PushSubscription

logger = logging.getLogger(__name__)

# Au-delà, on considère l'événement trop ancien pour mériter une notification
# (rattrapage après une panne : inutile de réveiller les gens pour de l'ancien).
_MAX_EVENT_AGE = timedelta(hours=6)
# Garde-fou anti-avalanche : une vigilance nationale peut produire des dizaines
# d'événements graves d'un coup.
_MAX_NOTIFICATIONS_PER_RUN = 3


def push_enabled() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def _vapid_claims() -> dict:
    contact = settings.VAPID_CONTACT_EMAIL or "admin@example.com"
    return {"sub": f"mailto:{contact}"}


def _send_one(subscription: dict, payload: dict) -> tuple[bool, int | None]:
    """Envoi bloquant d'une notification. Renvoie (succès, code HTTP).

    Isolé dans une fonction synchrone pour être exécuté hors de la boucle
    asyncio (pywebpush utilise `requests`).
    """
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims=_vapid_claims(),
            timeout=10,
        )
        return True, None
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return False, status
    except Exception as exc:  # réseau, clé malformée…
        logger.warning("Push: envoi impossible (%s)", exc)
        return False, None


async def notify_new_events(event_ids: list[str]) -> int:
    """Notifie les abonnés concernés par les événements donnés.

    Renvoie le nombre de notifications envoyées. Ne lève jamais.
    """
    if not push_enabled() or not event_ids:
        return 0

    try:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as session:
            events = (
                await session.execute(
                    select(Event)
                    .where(
                        Event.id.in_(event_ids),
                        # Seuls les événements notables et récents.
                        Event.gravite >= 2,
                        Event.date_publication >= now - _MAX_EVENT_AGE,
                    )
                    .order_by(Event.gravite.desc(), Event.date_publication.desc())
                    .limit(_MAX_NOTIFICATIONS_PER_RUN)
                )
            ).scalars().all()
            if not events:
                return 0

            subs = (await session.execute(select(PushSubscription))).scalars().all()
            if not subs:
                return 0

        sent = 0
        expired: list[str] = []
        notifies: set[str] = set()
        for event in events:
            for sub in subs:
                if event.gravite < sub.gravite_min:
                    continue
                # Abonnement départemental : ne notifier que si l'événement s'y
                # rattache. Abonnement national ("") : tout passe.
                if sub.departement and not (event.lieu_code_insee or "").startswith(sub.departement):
                    continue

                payload = {
                    "title": f"{'🔴' if event.gravite >= 3 else '🟠'} {event.categorie.replace('_', ' ').capitalize()}",
                    "body": event.titre[:180],
                    "url": f"/event/{event.id}",
                    "tag": event.cluster_id or event.id,
                }
                info = {
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                }
                ok, status = await asyncio.to_thread(_send_one, info, payload)
                if ok:
                    sent += 1
                    notifies.add(sub.endpoint)
                elif status in (404, 410):
                    # Abonnement révoqué côté navigateur : à supprimer.
                    expired.append(sub.endpoint)

        async with AsyncSessionLocal() as session:
            if expired:
                await session.execute(
                    delete(PushSubscription).where(PushSubscription.endpoint.in_(expired))
                )
                logger.info("Push: %d abonnements expirés supprimés", len(expired))
            # Horodatage des seuls abonnements réellement notifiés : il était
            # appliqué à TOUS, ce qui vidait le champ de son sens (impossible de
            # savoir qui avait reçu quoi, ni de repérer un abonné jamais servi).
            if notifies:
                await session.execute(
                    update(PushSubscription)
                    .where(PushSubscription.endpoint.in_(notifies))
                    .values(last_sent_at=now)
                )
            await session.commit()

        if sent:
            logger.info("Push: %d notification(s) envoyée(s) pour %d événement(s)", sent, len(events))
        return sent
    except Exception as exc:
        # Une notification ratée ne doit jamais compromettre l'ingestion.
        logger.error("Push: échec global des notifications: %s", exc, exc_info=True)
        return 0
