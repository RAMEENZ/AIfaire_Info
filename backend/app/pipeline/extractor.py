import json
import logging
from typing import Any

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Tu es un assistant d'extraction d'information pour un agrégateur d'actualités françaises géolocalisé.

Pour chaque article, extrais :
1. **lieu_nom** : le nom du lieu principal mentionné (ville, département, région, ou "national" si non localisable en France)
2. **categorie** : une des valeurs exactes suivantes : "meteo", "crue", "seisme", "energie", "sante", "transport", "ordre_public", "actualite"
3. **resume_ia** : un teaser de 1-2 phrases maximum résumant l'essentiel
4. **gravite** : entier 0-3 (0=info, 1=mineur, 2=modéré, 3=grave/urgent)

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ni après.
Format exact :
{"lieu_nom": "...", "categorie": "...", "resume_ia": "...", "gravite": 0}
"""


async def extract_with_claude(titre: str, description: str) -> dict[str, Any]:
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set, skipping extraction")
        return {
            "lieu_nom": "national",
            "categorie": "actualite",
            "resume_ia": titre[:200],
            "gravite": 0,
        }

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    user_content = f"Titre: {titre}"
    if description:
        user_content += f"\n\nDescription: {description[:1000]}"

    try:
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        raw_text = message.content[0].text.strip()

        try:
            result = json.loads(raw_text)
        except json.JSONDecodeError:
            start = raw_text.find("{")
            end = raw_text.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(raw_text[start:end])
            else:
                raise ValueError(f"No JSON found in response: {raw_text[:200]}")

        lieu_nom = str(result.get("lieu_nom", "national")).strip() or "national"
        categorie = str(result.get("categorie", "actualite")).strip()
        valid_categories = {"meteo", "crue", "seisme", "energie", "sante", "transport", "ordre_public", "actualite"}
        if categorie not in valid_categories:
            categorie = "actualite"

        resume_ia = str(result.get("resume_ia", "")).strip()[:500]

        try:
            gravite = int(result.get("gravite", 0))
            gravite = max(0, min(3, gravite))
        except (TypeError, ValueError):
            gravite = 0

        return {
            "lieu_nom": lieu_nom,
            "categorie": categorie,
            "resume_ia": resume_ia,
            "gravite": gravite,
        }

    except Exception as exc:
        logger.error("Claude extraction failed for '%s': %s", titre[:80], exc)
        return {
            "lieu_nom": "national",
            "categorie": "actualite",
            "resume_ia": titre[:200],
            "gravite": 0,
        }


async def maybe_extract(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("skip_extraction"):
        return item

    needs_extraction = (
        item.get("source") == "presse_rss"
        or not item.get("lieu_nom")
        or not item.get("resume_ia")
    )

    if not needs_extraction:
        return item

    titre = item.get("titre", "")
    description = item.get("description", "") or item.get("raw", {}).get("summary", "")

    extraction = await extract_with_claude(titre, description)

    updated = dict(item)
    if not updated.get("lieu_nom") or updated.get("source") == "presse_rss":
        updated["lieu_nom"] = extraction["lieu_nom"]
    if not updated.get("resume_ia"):
        updated["resume_ia"] = extraction["resume_ia"]
    if not updated.get("categorie") or updated.get("source") == "presse_rss":
        updated["categorie"] = extraction["categorie"]
    if updated.get("gravite", 0) == 0 and extraction["gravite"] > 0:
        updated["gravite"] = extraction["gravite"]

    return updated
