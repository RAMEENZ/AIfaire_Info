import json
import logging
import re
from typing import Any

import anthropic

from app.config import settings
from app.pipeline.geocoder import geocode

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

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "crue":         ["crue", "inondation", "débordement", "vigicrues", "montée des eaux"],
    "meteo":        ["météo", "météorologique", "tempête", "orage", "canicule", "verglas",
                     "neige", "vigilance météo", "vague de chaleur", "gel", "grêle"],
    "seisme":       ["séisme", "tremblement de terre", "magnitude", "secousse sismique", "sismique"],
    "energie":      ["coupure électricité", "réseau électrique", "enedis", "délestage",
                     "blackout", "panne de courant"],
    "transport":    ["sncf", "grève des transports", "perturbation trafic", "retard train",
                     "ratp", "autoroute", "accident de la route", "bouchon"],
    "ordre_public": ["manifestation", "émeute", "violence urbaine", "attentat", "terrorisme",
                     "incendie criminel", "fusillades", "agression"],
    "sante":        ["épidémie", "pandémie", "virus", "contamination", "hôpital débordé",
                     "urgences saturées", "santé publique"],
}

GRAVITY_KEYWORDS: dict[int, list[str]] = {
    3: ["catastrophe", "alerte rouge", "mort", "tués", "victimes", "bilan humain",
        "urgence absolue", "décès", "en danger", "situation dramatique"],
    2: ["alerte orange", "important", "danger", "risque élevé", "blessés graves",
        "situation critique", "état d'urgence"],
    1: ["vigilance", "attention", "prudence", "perturbation", "risque"],
}

TOPONYM_PATTERNS: list[str] = [
    r'\bà\s+([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,3})',
    r'\ben\s+([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,2})',
    r'\bdans\s+(?:le |la |les |l\')?([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,2})',
    r'\bprès\s+de\s+([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,2})',
    r'\bau\s+large\s+de\s+([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+)',
    r'\bsur\s+(?:le |la |les |l\')?([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,2})',
]


async def _rule_based_extract(titre: str, description: str | None) -> dict[str, Any]:
    """Extraction par règles (sans IA) : catégorie, gravité et lieu par regex + géocodage."""
    text = (titre + " " + (description or "")).lower()

    # --- Catégorie ---
    categorie = "actualite"
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw.lower() in text for kw in keywords):
            categorie = cat
            break

    # --- Gravité ---
    gravite = 0
    for level in (3, 2, 1):
        if any(kw.lower() in text for kw in GRAVITY_KEYWORDS[level]):
            gravite = level
            break

    # --- Lieu par regex sur le titre ---
    lieu_nom = "national"
    full_titre = titre  # patterns operate on original case
    for pattern in TOPONYM_PATTERNS:
        for match in re.finditer(pattern, full_titre):
            candidate = match.group(1).strip()
            try:
                geo = await geocode(candidate)
                if geo.get("confiance_geo", 0.0) >= 0.5:
                    lieu_nom = candidate
                    break
            except Exception as exc:
                logger.debug("Geocoding candidate '%s' failed: %s", candidate, exc)
        if lieu_nom != "national":
            break

    # --- Résumé ---
    resume_ia = (description[:280] if description else None) or titre[:200]

    return {
        "lieu_nom": lieu_nom,
        "categorie": categorie,
        "resume_ia": resume_ia,
        "gravite": gravite,
    }


async def extract_with_claude(titre: str, description: str) -> dict[str, Any]:
    if not settings.ANTHROPIC_API_KEY:
        logger.info("ANTHROPIC_API_KEY not set, using rule-based extraction")
        return await _rule_based_extract(titre, description)

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
