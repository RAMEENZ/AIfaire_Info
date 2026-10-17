"""Alertes de fraîcheur : webhook quand le pipeline cesse de produire.

Complément du healthcheck /healthz : autoheal redémarre un backend malade,
mais si le redémarrage ne guérit pas (constaté lors de la panne de 07/2026 —
un restart du backend n'avait rien réglé), la boucle resterait silencieuse.

DEUX pannes sont surveillées, parce qu'il en existe deux formes :

1. **Plus rien n'est ingéré** — le pipeline est mort. Seuil :
   HEALTHZ_MAX_DATA_AGE_HOURS.
2. **Le brief ne se régénère plus** — le pipeline tourne, mais le modèle de
   langage ne répond plus. Seuil : BRIEF_MAX_AGE_HOURS.

Le second cas manquait, et c'est celui qui s'est produit : quota Mistral épuisé
le 03/09/2026, brief figé sept jours. Aucune alerte n'était possible — les
événements continuaient d'arriver, donc le contrôle n°1 voyait des données
parfaitement fraîches. Le brief est le seul indicateur qui se fige quand le
modèle tombe, puisqu'il n'a aucun repli (brief.py n'appelle que Mistral).

Anti-spam : une alerte par période de cooldown ET PAR MOTIF — sinon une panne
d'ingestion en cours masquerait un brief figé pendant douze heures. Chaque
motif se réarme dès que sa situation redevient normale.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import func, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DailyBrief, Event

logger = logging.getLogger(__name__)

_ALERT_COOLDOWN = timedelta(hours=12)

# Motifs d'alerte. Les libellés partent dans la charge utile du webhook :
# ils doivent rester stables pour qu'un filtre côté réception tienne.
DONNEES_PERIMEES = "data_staleness"
BRIEF_FIGE = "brief_staleness"

# Import du module ≈ démarrage du processus : pendant la fenêtre de grâce,
# une base vide/périmée est normale (l'ingestion de démarrage n'a pas fini).
_STARTED_AT = datetime.now(timezone.utc)
_last_alert_at: dict[str, datetime] = {}


def _tz(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def raisons_de_signaler(
    now: datetime,
    newest_event: Optional[datetime],
    dernier_brief: Optional[datetime],
    *,
    max_data_age_hours: int,
    brief_max_age_hours: int,
) -> list[str]:
    """Logique pure : quels motifs justifient une alerte, à cet instant.

    Séparée de l'envoi pour être testable hors ligne, comme
    `compute_healthz_reasons` dans api/routes/health.py.

    Un brief ABSENT n'est pas un brief figé : une base neuve, ou une instance
    sans clé de modèle, n'a rien à signaler — on alerte sur une régénération qui
    s'ARRÊTE, pas sur une fonctionnalité qu'on n'utilise pas.
    """
    raisons: list[str] = []

    if newest_event is None or now - _tz(newest_event) > timedelta(hours=max_data_age_hours):
        raisons.append(DONNEES_PERIMEES)

    if dernier_brief is not None and now - _tz(dernier_brief) > timedelta(hours=brief_max_age_hours):
        raisons.append(BRIEF_FIGE)

    return raisons


def _message(
    motif: str, now: datetime,
    newest_event: Optional[datetime], dernier_brief: Optional[datetime],
) -> tuple[str, dict]:
    """Texte lisible et charge utile structurée pour un motif donné."""
    if motif == DONNEES_PERIMEES:
        age = f"{(now - _tz(newest_event)).total_seconds() / 3600:.0f} h" if newest_event else "jamais"
        return (
            f"🚨 (ai)Faire Info : aucun événement ingéré depuis {age} "
            f"(seuil : {settings.HEALTHZ_MAX_DATA_AGE_HOURS} h). "
            f"Le pipeline ne produit plus — vérifier `docker compose ps` et les logs.",
            {
                "webhook_event": DONNEES_PERIMEES,
                "newest_event_created_at": _tz(newest_event).isoformat() if newest_event else None,
                "threshold_hours": settings.HEALTHZ_MAX_DATA_AGE_HOURS,
            },
        )

    age_h = (now - _tz(dernier_brief)).total_seconds() / 3600
    return (
        f"🚨 (ai)Faire Info : le brief n'a pas été régénéré depuis {age_h:.0f} h "
        f"(seuil : {settings.BRIEF_MAX_AGE_HOURS} h). L'ingestion, elle, tourne : "
        f"c'est le modèle de langage qui ne répond plus. Vérifier le quota Mistral "
        f"et `tagged_pct_24h` dans /api/metrics.",
        {
            "webhook_event": BRIEF_FIGE,
            "last_brief_generated_at": _tz(dernier_brief).isoformat(),
            "threshold_hours": settings.BRIEF_MAX_AGE_HOURS,
        },
    )


async def _envoyer(text: str, payload: dict) -> bool:
    url = settings.WEBHOOK_URL
    charge = dict(payload)
    if "discord.com" in url or "discordapp.com" in url:
        charge["content"] = text
    elif "hooks.slack.com" in url:
        charge["text"] = text
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=charge)
    except Exception as exc:
        logger.warning("Webhook de fraîcheur échoué (%s) : %s", payload["webhook_event"], exc)
        return False
    return True


async def check_data_freshness() -> bool:
    """Vérifie la fraîcheur ; envoie un webhook par motif si nécessaire.

    Renvoie True si au moins une alerte a été envoyée (pour les logs/tests).
    """
    if not settings.WEBHOOK_URL:
        return False

    now = datetime.now(timezone.utc)
    if now - _STARTED_AT < timedelta(minutes=settings.HEALTHZ_BOOT_GRACE_MINUTES):
        return False

    async with AsyncSessionLocal() as session:
        newest = (await session.execute(select(func.max(Event.created_at)))).scalar_one()
        dernier_brief = (
            await session.execute(select(func.max(DailyBrief.generated_at)))
        ).scalar_one()

    raisons = raisons_de_signaler(
        now, newest, dernier_brief,
        max_data_age_hours=settings.HEALTHZ_MAX_DATA_AGE_HOURS,
        brief_max_age_hours=settings.BRIEF_MAX_AGE_HOURS,
    )

    # Réarmement : un motif redevenu normal doit pouvoir alerter immédiatement
    # la prochaine fois, sans attendre la fin de son cooldown.
    for motif in (DONNEES_PERIMEES, BRIEF_FIGE):
        if motif not in raisons:
            _last_alert_at.pop(motif, None)

    envoyee = False
    for motif in raisons:
        precedente = _last_alert_at.get(motif)
        if precedente is not None and now - precedente < _ALERT_COOLDOWN:
            continue
        text, payload = _message(motif, now, newest, dernier_brief)
        if await _envoyer(text, payload):
            logger.warning("Alerte de fraîcheur envoyée : %s", motif)
            _last_alert_at[motif] = now
            envoyee = True

    return envoyee
