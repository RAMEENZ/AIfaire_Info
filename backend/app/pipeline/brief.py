"""Génère un brief quotidien synthétique à partir des événements des dernières 24h."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DailyBrief, Event

logger = logging.getLogger(__name__)


async def generate_daily_brief() -> Optional[str]:
    """Génère et sauvegarde le brief du jour. Retourne le texte ou None si échec."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Event)
            .where(Event.date_publication >= since)
            .order_by(Event.gravite.desc(), Event.date_publication.desc())
            .limit(50)
        )
        events = result.scalars().all()

    if not events:
        logger.info("Brief: no events in last 24h, skipping")
        return None

    lines = []
    for e in events[:30]:
        loc = f" ({e.lieu_nom})" if e.lieu_nom else ""
        resume = e.resume_ia or e.titre
        lines.append(f"- [{e.categorie.upper()} g{e.gravite}]{loc} {resume[:150]}")

    events_text = "\n".join(lines)
    event_count = len(events)

    system_prompt = (
        "Tu es un rédacteur d'information pour un service d'alerte géolocalisé couvrant la France. "
        "Rédige un brief matinal concis (8-12 phrases) résumant les événements significatifs des dernières 24h. "
        "Structure : 1 phrase d'accroche globale, puis les points saillants par ordre d'importance, puis une phrase de conclusion. "
        "Ton : neutre, factuel, professionnel. Langue : français."
    )

    user_prompt = (
        f"Voici les {event_count} événements des dernières 24h "
        f"(format: [CATÉGORIE gravitéN] (lieu) résumé) :\n\n{events_text}\n\nRédige le brief matinal synthétique."
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
                    "max_tokens": 600,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
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
        }
