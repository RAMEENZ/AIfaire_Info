import asyncio
import hashlib
import html as _html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.pipeline.geocoder import geocode

logger = logging.getLogger(__name__)

_extract_cache: dict[str, dict[str, Any]] = {}
_MAX_EXTRACT_CACHE = 2048

_OLLAMA_SEMAPHORE = asyncio.Semaphore(2)
_MISTRAL_SEMAPHORE = asyncio.Semaphore(10)


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

2. **categorie** : valeur exacte parmi : "meteo", "crue", "seisme", "energie", "sante", "transport", "ordre_public", "actualite", "incendie", "nucleaire", "pollution", "cyber"

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

# Prompt allégé pour les petits modèles locaux (qwen2.5:1.5b, phi3:mini…).
# Plus direct, moins de prose — les modèles <3B suivent mieux les instructions
# courtes avec un exemple concret plutôt qu'une longue description.
SYSTEM_PROMPT_SMALL = """\
Extrait 5 champs d'un article d'actualité française. Réponds UNIQUEMENT en JSON, sans texte avant ni après.

Champs :
- lieu_nom : ville/département/région française (ex: "Lyon", "Gironde"). "national" si pas localisable en France. Jamais un pays étranger.
- categorie : UN SEUL parmi : meteo, crue, seisme, energie, sante, transport, ordre_public, actualite, incendie, nucleaire, pollution, cyber
- resume_ia : 1 phrase courte et factuelle résumant l'article.
- gravite : entier 0-3 (0=info, 1=vigilance, 2=alerte officielle, 3=urgence nationale)
- tags : liste de 3 à 5 mots-clés en minuscules

Exemple de réponse :
{"lieu_nom": "Marseille", "categorie": "ordre_public", "resume_ia": "Un incendie s'est déclaré dans le 13e arrondissement, causant l'évacuation de 50 personnes.", "gravite": 2, "tags": ["incendie", "évacuation", "bouches-du-rhône"]}
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
    "incendie":     ["incendie de forêt", "feu de forêt", "feux de forêt", "départ de feu",
                     "sapeur-pompier", "pompiers", "SDIS", "DFCI", "hectares brûlés",
                     "pyromane", "incendie criminel", "brûlis"],
    "nucleaire":    ["nucléaire", "central nucléaire", "réacteur", "IRSN", "ASN", "EDF nucléaire",
                     "radioactivité", "irradiation", "contamination radioactive", "fuite radioactive",
                     "incident nucléaire", "centrale atomique", "combustible nucléaire"],
    "pollution":    ["pollution", "qualité de l'air", "indice de qualité", "particules fines",
                     "PM2.5", "PM10", "dioxyde d'azote", "ozone", "alerte pollution",
                     "pollution atmosphérique", "nappe phréatique contaminée", "marée noire",
                     "déversement", "dégazage", "pollution des eaux", "eau potable"],
    "cyber":        ["cyberattaque", "ransomware", "piratage", "ANSSI", "CERT-FR", "vulnérabilité",
                     "faille de sécurité", "logiciel malveillant", "phishing", "hameçonnage",
                     "violation de données", "fuite de données", "intrusion informatique",
                     "rançongiciel", "attaque informatique"],
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

# Valeurs renvoyées par le modèle qui ne sont PAS des lieux français géocodables :
# on les ramène à « national » pour éviter un géocodage hasardeux (ex. « Mondial »
# matche une commune, « N/A » part en requête API inutile).
_NON_LIEU_VALUES = {
    "", "n/a", "na", "null", "none", "inconnu", "non spécifié", "non specifie",
    "monde", "international", "étranger", "etranger", "europe", "ue",
    "france", "nationale", "pays", "non localisable",
}


def _validate_extraction(raw: dict) -> dict[str, Any]:
    """Normalize and validate a raw extraction dict from any AI backend."""
    _raw_lieu = raw.get("lieu_nom")
    lieu_nom = (str(_raw_lieu).strip() if _raw_lieu and _raw_lieu != "null" else "") or "national"
    if lieu_nom.lower() in _NON_LIEU_VALUES:
        lieu_nom = "national"

    categorie = str(raw.get("categorie", "actualite")).strip()
    if categorie not in {"meteo", "crue", "seisme", "energie", "sante", "transport", "ordre_public", "actualite", "incendie", "nucleaire", "pollution", "cyber"}:
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
    # Les petits modèles (<3B) suivent mieux un prompt court et direct.
    is_small_model = any(
        tag in settings.OLLAMA_MODEL.lower()
        for tag in ("1.5b", "3b", "mini", "small", "tiny", "1b", "0.5b")
    )
    prompt = SYSTEM_PROMPT_SMALL if is_small_model else SYSTEM_PROMPT

    async with _OLLAMA_SEMAPHORE:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": settings.OLLAMA_MODEL,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": user_content},
                        ],
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.1, "num_predict": 350},
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


async def _extract_with_mistral(titre: str, description: str,
                                full_text: str | None = None) -> dict[str, Any] | None:
    """Call the Mistral AI API. Returns None on any error (caller falls back)."""
    user_content = _build_user_content(titre, description, full_text)

    async with _MISTRAL_SEMAPHORE:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.MISTRAL_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.MISTRAL_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_content},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 350,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                raw_text = resp.json()["choices"][0]["message"]["content"].strip()
                logger.info("Mistral OK [%s] '%s'", settings.MISTRAL_MODEL, titre[:50])
        except Exception as exc:
            logger.warning("Mistral extraction failed for '%s': %s", titre[:60], exc)
            return None

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        start, end = raw_text.find("{"), raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(raw_text[start:end])
            except json.JSONDecodeError:
                logger.warning("Mistral: unparseable JSON for '%s'", titre[:60])
                return None
        else:
            logger.warning("Mistral: no JSON in response for '%s'", titre[:60])
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


async def extract_with_claude(titre: str, description: str,
                              full_text: str | None = None) -> dict[str, Any]:
    """Extraction : Mistral API → Ollama local → fallback règles."""
    key = _cache_key(titre, description)
    if key in _extract_cache:
        return _extract_cache[key]

    result: dict[str, Any] | None = None

    if settings.MISTRAL_API_KEY:
        result = await _extract_with_mistral(titre, description, full_text)
        if result is None:
            logger.info("Mistral unavailable — falling back to Ollama/rules")

    if result is None and settings.OLLAMA_BASE_URL:
        result = await _extract_with_ollama(titre, description, full_text)
        if result is None:
            logger.info("Ollama unavailable — falling back to rule-based extraction")

    if result is None:
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


_FRANCE_HINTS_RE = re.compile(
    r"\b(france|français|française|paris|lyon|marseille|bordeaux|toulouse|nantes|"
    r"lille|strasbourg|rennes|montpellier|nice|grenoble|metz|nancy|caen|rouen|"
    r"bretagne|normandie|alsace|occitanie|provence|île-de-france|préfet|mairie|"
    r"sncf|ratp|edf|enedis|météo-france|insee|sénat|élysée|gouvernement français|"
    r"départem|région|commune|arrondissement)\b",
    re.IGNORECASE,
)


def _looks_french(titre: str, description: str) -> bool:
    """Heuristique rapide : l'article mentionne-t-il la France ou une entité française ?"""
    text = titre + " " + (description or "")[:300]
    return bool(_FRANCE_HINTS_RE.search(text))


# Plafond de gravité déterministe pour la presse. Le petit modèle local
# sur-évalue massivement (≈40 % des articles classés en alerte). On borne sa
# sortie par un scan de mots-clés conservateur : une gravité élevée n'est retenue
# que si des termes d'alerte EXPLICITES apparaissent. Le LLM ne peut que RÉDUIRE
# ce plafond (min), jamais inventer une alerte. Échelle de l'app : 3 = crise
# nationale (très rare), 2 = alerte officielle, 1 = vigilance/incident, 0 = info.
_GRAVITY_CEIL_3_RE = re.compile(
    r"\b(état d'urgence|catastrophe nationale|plan rouge|attentat|"
    r"attaque terroriste|pandémie|alerte enlèvement)\b",
    re.IGNORECASE,
)
_GRAVITY_CEIL_2_RE = re.compile(
    r"\b(vigilance orange|vigilance rouge|alerte rouge|alerte orange|"
    r"rappel (?:de )?(?:produit|lot|médicament)|vigicrues|arrêté préfectoral|"
    r"évacuation|confinement|couvre-feu|prise d'otage|fusillade|explosion|"
    r"séisme|magnitude|effondrement)\b",
    re.IGNORECASE,
)
_GRAVITY_CEIL_1_RE = re.compile(
    r"\b(vigilance jaune|accident|incendie|bless[ée]s?|noyades?|noyés?|"
    r"grève|manifestation|perturbation|canicule|vague de chaleur|orages?|"
    r"tempête|intempéries|coupure|inondation|crue|disparition)\b",
    re.IGNORECASE,
)


def _press_gravity_ceiling(titre: str, description: str) -> int:
    text = f"{titre} {description or ''}"
    if _GRAVITY_CEIL_3_RE.search(text):
        return 3
    if _GRAVITY_CEIL_2_RE.search(text):
        return 2
    if _GRAVITY_CEIL_1_RE.search(text):
        return 1
    return 0



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

    _has_ai = bool(settings.MISTRAL_API_KEY or settings.OLLAMA_BASE_URL)

    # Pour la presse généraliste, beaucoup d'articles concernent l'étranger.
    # Si le titre+description ne contient aucun indice français ET qu'un backend
    # IA est configuré (Mistral ou Ollama), on bascule directement sur le fallback
    # règles pour ne pas consommer de quota/CPU sur des articles hors-scope.
    if (
        _has_ai
        and item.get("source") == "presse_rss"
        and not _looks_french(titre, description)
    ):
        extraction = await _rule_based_extract(titre, description)
    else:
        # Fetch full article content when an AI backend is available — richer context
        # greatly improves location extraction and tag quality.
        full_text: str | None = None
        if settings.FETCH_FULL_ARTICLES and _has_ai:
            source_url = item.get("source_url", "")
            if source_url:
                from app.pipeline.fetcher import fetch_article_text
                full_text = await fetch_article_text(source_url)

        extraction = await extract_with_claude(titre, description, full_text)

    updated = dict(item)

    if updated.get("source") == "presse_rss":
        # Pour la presse, le verdict du modèle fait autorité, y compris
        # « national » : sinon un article international/national repris par un
        # flux régional (ex. « Guerre au Moyen-Orient » sur Actu Occitanie)
        # hériterait à tort de la région du flux et serait mal placé sur la carte.
        updated["lieu_nom"] = extraction["lieu_nom"]
    elif not updated.get("lieu_nom") and extraction["lieu_nom"] != "national":
        updated["lieu_nom"] = extraction["lieu_nom"]

    if not updated.get("resume_ia"):
        updated["resume_ia"] = extraction["resume_ia"]
    if not updated.get("categorie") or updated.get("source") == "presse_rss":
        updated["categorie"] = extraction["categorie"]

    if updated.get("source") == "presse_rss":
        # Borne la gravité du petit modèle par un plafond déterministe (cf.
        # _press_gravity_ceiling) : sans corroboration par mot-clé d'alerte, un
        # article ordinaire reste à 0 même si le modèle a halluciné un « 3 ».
        ceiling = _press_gravity_ceiling(titre, description)
        updated["gravite"] = min(int(extraction["gravite"]), ceiling)
    elif updated.get("gravite", 0) == 0 and extraction["gravite"] > 0:
        updated["gravite"] = extraction["gravite"]

    updated["tags"] = extraction.get("tags", [])

    # Override catégorie pour les sources autoritatives connues
    auteur_lower = (updated.get("auteur") or "").lower()
    for keyword, forced_cat in SOURCE_CAT_OVERRIDES.items():
        if keyword in auteur_lower:
            updated["categorie"] = forced_cat
            break

    return updated
