"""Génère un brief quotidien synthétique à partir des événements des dernières 24h."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DailyBrief, Event
from app.pipeline.sanitize import sanitize_markdown as _sanitize_brief

logger = logging.getLogger(__name__)


async def generate_daily_brief(hours: int = 24) -> Optional[str]:
    """Génère et sauvegarde le brief du jour. Retourne le texte ou None si échec."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with AsyncSessionLocal() as session:
        # Alertes : événements à gravité élevée (vigilances, incidents…).
        alerts_res = await session.execute(
            select(Event)
            .where(Event.date_publication >= since, Event.gravite >= 2)
            .order_by(Event.gravite.desc(), Event.date_publication.desc())
            .limit(20)
        )
        alerts = list(alerts_res.scalars().all())

        # Actualité générale : les plus récents, EN EXCLUANT les catégories de
        # bulletins d'alerte (météo/crue/séisme). Sans cette exclusion, les
        # vigilances Météo-France — très nombreuses et horodatées en fin de
        # journée — monopolisent aussi ce volet par récence, et l'« actualité »
        # se résume encore à de la météo. On laisse ainsi remonter la presse
        # (société, politique, faits divers, transport, santé, économie…).
        recent_res = await session.execute(
            select(Event)
            .where(
                Event.date_publication >= since,
                Event.categorie.notin_(["meteo", "crue", "seisme"]),
            )
            .order_by(Event.date_publication.desc())
            .limit(60)
        )
        recent = list(recent_res.scalars().all())

        # Actualité régionale : événements localisés (hors national), pour donner
        # au brief un ancrage géographique au lieu d'un tropisme parisien/national.
        # On exclut là encore les bulletins d'alerte météo.
        regional_res = await session.execute(
            select(Event)
            .where(
                Event.date_publication >= since,
                Event.categorie.notin_(["meteo", "crue", "seisme"]),
                Event.lieu_niveau.in_(["commune", "departement", "region"]),
                Event.lieu_nom.isnot(None),
            )
            .order_by(Event.date_publication.desc())
            .limit(80)
        )
        regional_all = list(regional_res.scalars().all())

    # Actualité = récents hors alertes déjà listées.
    alert_ids = {e.id for e in alerts}
    news = [e for e in recent if e.id not in alert_ids][:25]

    # En régions = localisés, dédupliqués à un événement par lieu pour maximiser
    # la diversité géographique, en excluant ce qui est déjà cité ailleurs.
    cited_ids = alert_ids | {e.id for e in news}
    regional: list[Event] = []
    seen_lieux: set[str] = set()
    for e in regional_all:
        if e.id in cited_ids:
            continue
        lieu_key = (e.lieu_nom or "").strip().lower()
        if not lieu_key or lieu_key in seen_lieux or lieu_key == "national":
            continue
        seen_lieux.add(lieu_key)
        regional.append(e)
        if len(regional) >= 8:
            break

    events = alerts + news + regional
    if not events:
        logger.info("Brief: no events in last %dh, skipping", hours)
        return None

    def _fmt(e: Event) -> str:
        # Données fournies au modèle SANS code ni crochet, pour qu'il n'en
        # reproduise pas dans le texte final (cf. règles de forme du prompt).
        loc = f"({e.lieu_nom}) " if e.lieu_nom and e.lieu_nom != "national" else ""
        resume = e.resume_ia or e.titre
        return f"- {loc}{resume[:200]}"

    alerts_text = "\n".join(_fmt(e) for e in alerts) or "(aucune alerte majeure)"
    news_text = "\n".join(_fmt(e) for e in news) or "(rien de notable)"
    regional_text = "\n".join(_fmt(e) for e in regional) or "(rien de notable en régions)"
    event_count = len(events)

    system_prompt = (
        "Tu es un rédacteur d'information pour un service d'information géolocalisé couvrant la France. "
        f"Rédige un brief synthétique et fluide des dernières {hours}h, en trois sections.\n"
        "RÈGLES DE FORME (impératives) :\n"
        "- Texte simple uniquement. N'utilise AUCUN caractère de formatage Markdown : "
        "ni dièse (#), ni astérisque (*), ni tiret bas (_), ni crochets [ ], ni lignes de séparation (---).\n"
        "- N'emploie aucune étiquette ni code technique (pas de « [METEO g3] », pas de niveau de gravité chiffré).\n"
        "- Chaque section commence par son titre seul sur sa propre ligne, écrit exactement ainsi : "
        "Alertes & vigilances — puis Actualité générale — puis En régions. "
        "Fais suivre chaque titre d'un ou plusieurs paragraphes de prose, séparés par une ligne vide.\n"
        "CONTENU :\n"
        "1. Alertes & vigilances : les risques majeurs (météo, crues, séismes, incidents…), 2 à 4 phrases. "
        "S'il n'y a pas d'alerte majeure, dis-le en une phrase.\n"
        "2. Actualité générale : les faits marquants du jour au-delà des alertes "
        "(société, politique, faits divers, économie, culture, sport…), 3 à 5 phrases.\n"
        "3. En régions : 2 à 4 faits notables ancrés dans différents territoires, "
        "en citant explicitement le lieu. Varie les régions ; ne te limite pas à Paris. "
        "Si rien de notable en régions, dis-le en une phrase.\n"
        "Ton neutre, factuel, professionnel. Langue : français. "
        "N'invente rien qui ne figure pas dans les données fournies."
    )

    user_prompt = (
        f"ALERTES & VIGILANCES ({len(alerts)}) :\n{alerts_text}\n\n"
        f"ACTUALITÉ GÉNÉRALE ({len(news)}) :\n{news_text}\n\n"
        f"EN RÉGIONS ({len(regional)}) :\n{regional_text}\n\n"
        "Rédige le brief en trois sections (titres en clair, prose simple, aucun symbole de formatage)."
    )

    if not settings.MISTRAL_API_KEY:
        logger.warning("Brief: MISTRAL_API_KEY not set, cannot generate brief")
        return None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.MISTRAL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.MISTRAL_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1000,
                },
            )
            resp.raise_for_status()
            content = _sanitize_brief(resp.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        logger.error("Brief generation failed: %s", exc)
        return None

    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(DailyBrief).where(DailyBrief.date >= today).limit(1)
        )
        existing_brief = existing.scalar_one_or_none()

        if existing_brief:
            existing_brief.content = content
            existing_brief.event_count = event_count
            existing_brief.generated_at = now
        else:
            session.add(DailyBrief(
                date=today,
                content=content,
                event_count=event_count,
                generated_at=now,
            ))

        await session.commit()

    logger.info("Brief generated: %d events → %d chars", event_count, len(content))
    return content


async def generate_weekly_brief() -> Optional[str]:
    """Génère le brief de la semaine (lundi matin)."""
    now = datetime.now(timezone.utc)
    monday = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(DailyBrief).where(DailyBrief.date >= monday).limit(1)
        )
        # Don't regenerate if already done today
        existing_brief = existing.scalar_one_or_none()
        if existing_brief and "semaine" in existing_brief.content.lower():
            logger.info("Weekly brief already generated today")
            return existing_brief.content

    return await generate_daily_brief(hours=168)


async def get_latest_brief() -> Optional[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DailyBrief).order_by(DailyBrief.date.desc()).limit(1)
        )
        brief = result.scalar_one_or_none()
        if brief is None:
            return None
        return {
            "date": brief.date.isoformat(),
            "content": brief.content,
            "event_count": brief.event_count,
            "generated_at": brief.generated_at.isoformat(),
            "is_weekly": brief.event_count > 100,  # Weekly briefs cover more events
        }
