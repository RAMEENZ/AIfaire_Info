import asyncio
import hashlib
import html as _html
import json
import logging
import re
from typing import Any

import anthropic

from app.config import settings
from app.pipeline.geocoder import geocode

logger = logging.getLogger(__name__)

_extract_cache: dict[str, dict[str, Any]] = {}
_MAX_EXTRACT_CACHE = 2048

# Limit concurrent Anthropic API calls to avoid hitting rate limits during large ingestion runs
_CLAUDE_SEMAPHORE = asyncio.Semaphore(4)


def _cache_key(titre: str, description: str) -> str:
    return hashlib.sha256((titre + (description or "")[:200]).encode()).hexdigest()


def _cache_put(key: str, value: dict[str, Any]) -> None:
    if len(_extract_cache) >= _MAX_EXTRACT_CACHE:
        _extract_cache.clear()
    _extract_cache[key] = value

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
    "crue":         ["crue", "inondation", "débordement", "vigicrues", "montée des eaux",
                     "submersion", "zone inondable", "plan de prévention inondation"],
    "meteo":        ["météo", "météorologique", "tempête", "orage", "canicule", "verglas",
                     "neige", "vigilance météo", "vague de chaleur", "gel", "grêle",
                     "vent violent", "pluie intense", "forte chaleur", "brouillard",
                     "épisode méditerranéen", "vigilance jaune", "vigilance orange", "vigilance rouge"],
    "seisme":       ["séisme", "tremblement de terre", "magnitude", "secousse sismique", "sismique",
                     "secousse tellurique", "activité volcanique"],
    "energie":      ["coupure électricité", "réseau électrique", "enedis", "délestage",
                     "blackout", "panne de courant", "panne d'électricité", "panne edf",
                     "rupture d'approvisionnement", "réseau enedis", "tension sur le réseau"],
    "transport":    ["sncf", "grève des transports", "perturbation trafic", "retard train",
                     "ratp", "autoroute", "accident de la route", "bouchon",
                     "circulation perturbée", "axe coupé", "route barrée", "fermeture autoroute",
                     "grève sncf", "trafic ferroviaire", "train supprimé", "rer", "transilien"],
    "ordre_public": ["manifestation", "émeute", "violence urbaine", "attentat", "terrorisme",
                     "incendie criminel", "fusillade", "agression", "cambriolage", "braquage",
                     "prise d'otage", "mort suspecte", "homicide", "tir"],
    "sante":        ["épidémie", "pandémie", "virus", "contamination", "hôpital débordé",
                     "urgences saturées", "santé publique", "santépublique", "spf", "alerte sanitaire",
                     "intoxication", "rappel de lot", "listeria", "salmonelle", "grippe",
                     "gastro-entérite", "dépistage", "vaccination", "variole du singe"],
}

GRAVITY_KEYWORDS: dict[int, list[str]] = {
    3: ["catastrophe", "alerte rouge", "mort", "tués", "victimes", "bilan humain",
        "urgence absolue", "décès", "en danger", "situation dramatique",
        "blessés graves", "état d'urgence", "évacuation", "disparu", "noyé",
        "enseveli", "immeuble effondré", "explosion", "incendie mortel"],
    2: ["alerte orange", "important", "danger", "risque élevé",
        "situation critique", "blessés", "perturbation majeure",
        "fermeture", "barrage", "confinement", "déviation obligatoire"],
    1: ["vigilance", "attention", "prudence", "perturbation", "risque",
        "ralentissement", "avis de", "préconisation"],
}

TOPONYM_PATTERNS: list[str] = [
    r'\bà\s+([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,3})',
    r'\ben\s+([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,2})',
    r'\bdans\s+(?:le |la |les |l\')?([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,2})',
    r'\bprès\s+de\s+([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,2})',
    r'\bau\s+large\s+de\s+([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+)',
    r'\bsur\s+(?:le |la |les |l\')?([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,2})',
]


def _strip_html(text: str) -> str:
    """Supprime les balises HTML et décode les entités."""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = _html.unescape(text)
    return ' '.join(text.split())


async def _rule_based_extract(titre: str, description: str | None) -> dict[str, Any]:
    """Extraction par règles (sans IA) : catégorie, gravité et lieu par regex + géocodage."""
    clean_desc = _strip_html(description) if description else None
    text = (titre + " " + (clean_desc or "")).lower()

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

    # --- Lieu par regex : titre d'abord, puis description ---
    lieu_nom = "national"
    texts_to_search = [titre]
    if clean_desc:
        # Only first 300 chars of description for performance
        texts_to_search.append(clean_desc[:300])

    for search_text in texts_to_search:
        for pattern in TOPONYM_PATTERNS:
            for match in re.finditer(pattern, search_text):
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
        if lieu_nom != "national":
            break

    # --- Résumé ---
    resume_ia = (clean_desc[:280] if clean_desc else None) or titre[:200]

    return {
        "lieu_nom": lieu_nom,
        "categorie": categorie,
        "resume_ia": resume_ia,
        "gravite": gravite,
    }


async def extract_with_claude(titre: str, description: str) -> dict[str, Any]:
    key = _cache_key(titre, description)
    if key in _extract_cache:
        return _extract_cache[key]

    if not settings.ANTHROPIC_API_KEY:
        result = await _rule_based_extract(titre, description)
        _cache_put(key, result)
        return result

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    clean_description = _strip_html(description) if description else ""
    user_content = f"Titre: {titre}"
    if clean_description:
        user_content += f"\n\nDescription: {clean_description[:1000]}"

    async with _CLAUDE_SEMAPHORE:
        # Re-check cache under semaphore: another task may have populated it while we waited
        if key in _extract_cache:
            return _extract_cache[key]

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

            _raw_lieu = result.get("lieu_nom")
            lieu_nom = (str(_raw_lieu).strip() if _raw_lieu and _raw_lieu != "null" else "") or "national"
            categorie = str(result.get("categorie", "actualite")).strip()
            valid_categories = {"meteo", "crue", "seisme", "energie", "sante", "transport", "ordre_public", "actualite"}
            if categorie not in valid_categories:
                categorie = "actualite"

            _raw_resume = result.get("resume_ia")
            resume_ia = (str(_raw_resume).strip() if _raw_resume and _raw_resume != "null" else "")[:500]

            try:
                gravite = int(result.get("gravite", 0))
                gravite = max(0, min(3, gravite))
            except (TypeError, ValueError):
                gravite = 0

            extracted: dict[str, Any] = {
                "lieu_nom": lieu_nom,
                "categorie": categorie,
                "resume_ia": resume_ia,
                "gravite": gravite,
            }
            _cache_put(key, extracted)
            return extracted

        except Exception as exc:
            logger.error("Claude extraction failed for '%s': %s", titre[:80], exc)
            fallback = {
                "lieu_nom": "national",
                "categorie": "actualite",
                "resume_ia": titre[:200],
                "gravite": 0,
            }
            _cache_put(key, fallback)
            return fallback


# Sources autoritatives → catégorie forcée (indépendamment de l'extraction NLP)
SOURCE_CAT_OVERRIDES: dict[str, str] = {
    "santé publique france": "sante",
    "spf": "sante",
    "ansm": "sante",
    "vigicrues": "crue",
    "météo-france": "meteo",
    "meteo-france": "meteo",
    "ministère intérieur": "ordre_public",
    "ministere interieur": "ordre_public",
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
        extracted_lieu = extraction["lieu_nom"]
        current_lieu = updated.get("lieu_nom")
        # Preserve a regional lieu_nom provided by the feed when extraction only returns "national"
        if extracted_lieu != "national" or not current_lieu:
            updated["lieu_nom"] = extracted_lieu

    if not updated.get("resume_ia"):
        updated["resume_ia"] = extraction["resume_ia"]
    if not updated.get("categorie") or updated.get("source") == "presse_rss":
        updated["categorie"] = extraction["categorie"]
    if updated.get("gravite", 0) == 0 and extraction["gravite"] > 0:
        updated["gravite"] = extraction["gravite"]

    # Override catégorie pour les sources autoritatives connues
    auteur_lower = (updated.get("auteur") or "").lower()
    for keyword, forced_cat in SOURCE_CAT_OVERRIDES.items():
        if keyword in auteur_lower:
            updated["categorie"] = forced_cat
            break

    return updated
