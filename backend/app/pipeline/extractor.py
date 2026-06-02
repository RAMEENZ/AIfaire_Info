import asyncio
import hashlib
import html as _html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import anthropic
import httpx

from app.config import settings
from app.pipeline.geocoder import geocode

logger = logging.getLogger(__name__)

_extract_cache: dict[str, dict[str, Any]] = {}
_MAX_EXTRACT_CACHE = 2048

# Anthropic: 4 parallel calls (API rate-limit friendly)
_CLAUDE_SEMAPHORE = asyncio.Semaphore(4)
# Ollama (local CPU): one inference at a time to avoid OOM
_OLLAMA_SEMAPHORE = asyncio.Semaphore(1)

# Client Anthropic réutilisé entre tous les appels : recréer le client (et donc
# son pool de connexions HTTP) à chaque article gaspille des handshakes TCP/TLS
# et peut épuiser les ports éphémères sous charge.
_anthropic_client: "anthropic.AsyncAnthropic | None" = None


def _get_anthropic_client() -> "anthropic.AsyncAnthropic":
    global _anthropic_client
    if _anthropic_client is None:
        # Timeout explicite : le SDK Anthropic défaut à 600 s, ce qui bloquerait
        # les 4 slots semaphore pendant 10 min en cas de lenteur API.
        _anthropic_client = anthropic.AsyncAnthropic(
            api_key=settings.ANTHROPIC_API_KEY, timeout=45.0
        )
    return _anthropic_client


def _cache_key(titre: str, description: str) -> str:
    return hashlib.sha256((titre + (description or "")[:200]).encode()).hexdigest()


def _cache_put(key: str, value: dict[str, Any]) -> None:
    # Demi-éviction (comme geocoder) plutôt que clear() total : évite que tout
    # le cache devienne froid d'un coup, ce qui provoquerait un afflux d'appels
    # LLM payants juste après le franchissement de la capacité.
    if len(_extract_cache) >= _MAX_EXTRACT_CACHE:
        keys = list(_extract_cache)
        for k in keys[: len(keys) // 2]:
            del _extract_cache[k]
    _extract_cache[key] = value

SYSTEM_PROMPT = """\
Tu es un assistant d'extraction d'information pour un agrégateur d'actualités françaises géolocalisé.

Pour chaque article, extrais EXACTEMENT ces 5 champs :

1. **lieu_nom** : commune, département ou région française précise (ex: "Lyon", "Gironde", "Bretagne"). Retourne "national" si l'événement n'est pas localisable en France. Ne retourne JAMAIS un pays étranger.

2. **categorie** : valeur exacte parmi : "meteo", "crue", "seisme", "energie", "sante", "transport", "ordre_public", "actualite"

3. **resume_ia** : 1-2 phrases factuelles résumant l'essentiel de l'article.

4. **gravite** — critères stricts :
   - 3 = URGENCE : crise d'ampleur nationale touchant toute la population (attentat majeur, catastrophe nationale, pandémie déclarée). TRÈS RARE.
   - 2 = ALERTE : alerte officielle d'une autorité (Météo-France orange/rouge, ANSM, Vigicrues 3-4, arrêté préfectoral). Incident grave avec victimes confirmées.
   - 1 = VIGILANCE : vigilance météo jaune, risque sans victime, perturbation transport notable.
   - 0 = INFORMATION : actualité courante. La grande majorité des articles = 0.

5. **tags** : liste JSON de 3 à 5 mots-clés thématiques en français, en minuscules (ex: ["grève", "sncf", "île-de-france"]). Concis et pertinents, sans répéter lieu_nom ou categorie.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ni après.
{"lieu_nom": "...", "categorie": "...", "resume_ia": "...", "gravite": 0, "tags": ["...", "..."]}
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
                     "rupture d'approvisionnement", "réseau enedis", "tension sur le réseau",
                     "panne de gaz", "réseau gazier", "grdf", "gestionnaire réseau",
                     "réseau de transport", "rte électricité"],
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
                     "gastro-entérite", "dépistage", "vaccination", "variole du singe",
                     "ansm", "médicament", "dispositif médical", "alerte sanitaire",
                     "crise sanitaire", "canicule sanitaire", "surveillance épidémique"],
}

GRAVITY_KEYWORDS: dict[int, list[str]] = {
    3: [
        # Crises nationales uniquement
        "état d'urgence", "catastrophe nationale", "plan rouge",
        "attentat", "attaque terroriste", "alerte attentat",
        "mort", "tués", "victimes", "décès", "bilan humain",
        "blessés graves", "en danger de mort", "urgence absolue",
        "immeuble effondré", "explosion meurtrière", "incendie mortel",
        "évacuation massive", "noyé", "enseveli", "disparu en mer",
    ],
    2: [
        # Alertes officielles et incidents graves localisés
        "alerte orange", "vigilance orange", "alerte rouge météo", "vigilance rouge",
        "alerte officielle", "alerte sanitaire", "rappel de médicament", "rappel de lot",
        "alerte vigicrues", "crue importante", "inondation grave",
        "arrêté préfectoral d'urgence", "fermeture préfectorale",
        "confinement", "évacuation préventive", "zone de danger",
        "couvre-feu", "blessés légers", "blessés", "blessé", "perturbation majeure confirmée",
    ],
    1: [
        # Vigilances météo et risques signalés sans victime
        "vigilance jaune", "vigilance météo", "avis de vigilance",
        "risque de", "prudence recommandée", "attention particulière",
        "perturbation prévue", "trafic perturbé", "grève prévue",
        "ralentissement important", "fermeture temporaire de route",
    ],
}

def _validate_extraction(raw: dict) -> dict[str, Any]:
    """Normalize and validate a raw extraction dict from any AI backend."""
    _raw_lieu = raw.get("lieu_nom")
    lieu_nom = (str(_raw_lieu).strip() if _raw_lieu and _raw_lieu != "null" else "") or "national"

    categorie = str(raw.get("categorie", "actualite")).strip()
    if categorie not in {"meteo", "crue", "seisme", "energie", "sante", "transport", "ordre_public", "actualite"}:
        categorie = "actualite"

    _raw_resume = raw.get("resume_ia")
    resume_ia = (str(_raw_resume).strip() if _raw_resume and _raw_resume != "null" else "")[:500]

    try:
        gravite = max(0, min(3, int(raw.get("gravite", 0))))
    except (TypeError, ValueError):
        gravite = 0

    raw_tags = raw.get("tags", [])
    if isinstance(raw_tags, list):
        tags = [str(t).strip().lower() for t in raw_tags if t and str(t).strip()][:5]
    else:
        tags = []

    return {
        "lieu_nom": lieu_nom,
        "categorie": categorie,
        "resume_ia": resume_ia,
        "gravite": gravite,
        "tags": tags,
    }


def _build_user_content(titre: str, description: str, full_text: str | None = None) -> str:
    """Build the user message sent to any AI backend."""
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    parts = [f"Date: {today}", f"Titre: {titre}"]
    if full_text:
        # Full article text gives much better location and tag extraction
        parts.append(f"\nContenu de l'article:\n{full_text[:3000]}")
    else:
        clean_desc = _strip_html(description) if description else ""
        if clean_desc:
            parts.append(f"\nDescription: {clean_desc[:1000]}")
    return "\n".join(parts)


async def _extract_with_ollama(titre: str, description: str,
                                full_text: str | None = None) -> dict[str, Any] | None:
    """Call the local Ollama model. Returns None on any error (caller falls back)."""
    user_content = _build_user_content(titre, description, full_text)

    async with _OLLAMA_SEMAPHORE:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": settings.OLLAMA_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_content},
                        ],
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.1, "num_predict": 300},
                    },
                )
                resp.raise_for_status()
                raw_text = resp.json()["message"]["content"].strip()
        except Exception as exc:
            logger.warning("Ollama extraction failed for '%s': %s", titre[:60], exc)
            return None

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        start, end = raw_text.find("{"), raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(raw_text[start:end])
            except json.JSONDecodeError:
                logger.warning("Ollama: unparseable JSON for '%s'", titre[:60])
                return None
        else:
            logger.warning("Ollama: no JSON in response for '%s'", titre[:60])
            return None

    return _validate_extraction(result)


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
                    if geo.get("confiance_geo", 0.0) >= 0.65:
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
        "tags": [],
    }


async def _extract_with_anthropic(titre: str, description: str, cache_key: str,
                                   full_text: str | None = None) -> dict[str, Any]:
    """Call Anthropic Claude Haiku. Falls back to rule-based on error."""
    client = _get_anthropic_client()
    user_content = _build_user_content(titre, description, full_text)

    async with _CLAUDE_SEMAPHORE:
        if cache_key in _extract_cache:
            return _extract_cache[cache_key]
        try:
            message = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=350,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            raw_text = message.content[0].text.strip()
            try:
                result = json.loads(raw_text)
            except json.JSONDecodeError:
                start, end = raw_text.find("{"), raw_text.rfind("}") + 1
                if start >= 0 and end > start:
                    try:
                        result = json.loads(raw_text[start:end])
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"Malformed JSON slice: {raw_text[:200]}") from exc
                else:
                    raise ValueError(f"No JSON in response: {raw_text[:200]}")
            extracted = _validate_extraction(result)
            _cache_put(cache_key, extracted)
            return extracted
        except Exception as exc:
            # Échec transitoire (429, 529, réseau, JSON tronqué) : on renvoie un
            # fallback dégradé pour CE run mais SANS le mettre en cache, afin que
            # l'ingestion suivante retente l'extraction. Mettre le fallback en
            # cache « empoisonnerait » la clé pour toute la durée du process.
            logger.error("Anthropic extraction failed for '%s': %s", titre[:80], exc)
            return {"lieu_nom": "national", "categorie": "actualite",
                    "resume_ia": titre[:200], "gravite": 0, "tags": []}


async def extract_with_claude(titre: str, description: str,
                              full_text: str | None = None) -> dict[str, Any]:
    """Route extraction: Ollama (local) → Anthropic → rule-based fallback."""
    key = _cache_key(titre, description)
    if key in _extract_cache:
        return _extract_cache[key]

    if settings.OLLAMA_BASE_URL:
        result = await _extract_with_ollama(titre, description, full_text)
        if result is None:
            if settings.ANTHROPIC_API_KEY:
                logger.info("Ollama unavailable — falling back to Anthropic")
                return await _extract_with_anthropic(titre, description, key, full_text)
            logger.info("Ollama unavailable — falling back to rule-based extraction")
            result = await _rule_based_extract(titre, description)
    elif settings.ANTHROPIC_API_KEY:
        return await _extract_with_anthropic(titre, description, key, full_text)
    else:
        result = await _rule_based_extract(titre, description)

    _cache_put(key, result)
    return result


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

    # Fetch full article content when an AI backend is available — richer context
    # greatly improves location extraction and tag quality.
    full_text: str | None = None
    if settings.FETCH_FULL_ARTICLES and (settings.OLLAMA_BASE_URL or settings.ANTHROPIC_API_KEY):
        source_url = item.get("source_url", "")
        if source_url:
            from app.pipeline.fetcher import fetch_article_text
            full_text = await fetch_article_text(source_url)

    extraction = await extract_with_claude(titre, description, full_text)

    updated = dict(item)

    if not updated.get("lieu_nom") or updated.get("source") == "presse_rss":
        extracted_lieu = extraction["lieu_nom"]
        current_lieu = updated.get("lieu_nom")
        if extracted_lieu != "national" or not current_lieu:
            updated["lieu_nom"] = extracted_lieu

    if not updated.get("resume_ia"):
        updated["resume_ia"] = extraction["resume_ia"]
    if not updated.get("categorie") or updated.get("source") == "presse_rss":
        updated["categorie"] = extraction["categorie"]
    if updated.get("gravite", 0) == 0 and extraction["gravite"] > 0:
        updated["gravite"] = extraction["gravite"]

    updated["tags"] = extraction.get("tags", [])

    # Override catégorie pour les sources autoritatives connues
    auteur_lower = (updated.get("auteur") or "").lower()
    for keyword, forced_cat in SOURCE_CAT_OVERRIDES.items():
        if keyword in auteur_lower:
            updated["categorie"] = forced_cat
            break

    return updated
