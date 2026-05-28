import asyncio
import logging
from typing import Any

import httpx

from app.geo_data import DEPT_CODE_TO_NAME

logger = logging.getLogger(__name__)

# In-process cache: maps lieu_nom → GeoResult
_geo_cache: dict[str, "GeoResult"] = {}
_MAX_GEO_CACHE = 1024  # evict all when full; most lieu_nom values repeat across articles


def _geo_cache_put(key: str, value: "GeoResult") -> None:
    if len(_geo_cache) >= _MAX_GEO_CACHE:
        _geo_cache.clear()
    _geo_cache[key] = value


# Limit concurrent geocoding API calls (BAN + geo.api.gouv.fr rate-limit at ~10 rps)
_GEO_SEMAPHORE = asyncio.Semaphore(8)

BAN_URL = "https://api-adresse.data.gouv.fr/search/"
GEO_DEPT_URL = "https://geo.api.gouv.fr/departements"
GEO_REGION_URL = "https://geo.api.gouv.fr/regions"

DEPT_NAME_TO_CODE: dict[str, str] = {v.lower(): k for k, v in DEPT_CODE_TO_NAME.items()}

# Common abbreviations and alternate spellings that map to geocodable names
LIEU_ALIASES: dict[str, str] = {
    "paca":                   "Provence-Alpes-Côte d'Azur",
    "idf":                    "Île-de-France",
    "idF":                    "Île-de-France",
    "ile-de-france":          "Île-de-France",
    "aura":                   "Auvergne-Rhône-Alpes",
    "ara":                    "Auvergne-Rhône-Alpes",
    "bfc":                    "Bourgogne-Franche-Comté",
    "cvdl":                   "Centre-Val de Loire",
    "hra":                    "Hauts-de-France",
    "hdf":                    "Hauts-de-France",
    "na":                     "Nouvelle-Aquitaine",
    "paca":                   "Provence-Alpes-Côte d'Azur",
    "nord-pas-de-calais":     "Hauts-de-France",
    "picardie":               "Hauts-de-France",
    "champagne-ardenne":      "Grand Est",
    "lorraine":               "Grand Est",
    "alsace":                 "Grand Est",
    "haute-normandie":        "Normandie",
    "basse-normandie":        "Normandie",
    "poitou-charentes":       "Nouvelle-Aquitaine",
    "limousin":               "Nouvelle-Aquitaine",
    "aquitaine":              "Nouvelle-Aquitaine",
    "midi-pyrénées":          "Occitanie",
    "languedoc-roussillon":   "Occitanie",
    "rhône-alpes":            "Auvergne-Rhône-Alpes",
    "auvergne":               "Auvergne-Rhône-Alpes",
    "haute-normandie":        "Normandie",
    "pays de loire":          "Pays de la Loire",
    "pays-de-la-loire":       "Pays de la Loire",
    "dom-tom":                None,
}

# Coordonnées hardcodées pour les régions métropolitaines
# (geo.api.gouv.fr/regions n'expose pas le champ "centre")
REGION_COORDS: dict[str, dict] = {
    "auvergne-rhône-alpes":          {"lat": 45.50, "lon":  4.00, "code_insee": "84", "niveau": "region", "confiance_geo": 0.90},
    "auvergne-rhone-alpes":          {"lat": 45.50, "lon":  4.00, "code_insee": "84", "niveau": "region", "confiance_geo": 0.90},
    "bourgogne-franche-comté":       {"lat": 47.10, "lon":  5.20, "code_insee": "27", "niveau": "region", "confiance_geo": 0.90},
    "bourgogne-franche-comte":       {"lat": 47.10, "lon":  5.20, "code_insee": "27", "niveau": "region", "confiance_geo": 0.90},
    "bretagne":                      {"lat": 48.20, "lon": -2.90, "code_insee": "53", "niveau": "region", "confiance_geo": 0.90},
    "centre-val de loire":           {"lat": 47.50, "lon":  1.70, "code_insee": "24", "niveau": "region", "confiance_geo": 0.90},
    "corse":                         {"lat": 42.00, "lon":  9.00, "code_insee": "94", "niveau": "region", "confiance_geo": 0.90},
    "grand est":                     {"lat": 48.70, "lon":  7.00, "code_insee": "44", "niveau": "region", "confiance_geo": 0.90},
    "hauts-de-france":               {"lat": 50.50, "lon":  2.80, "code_insee": "32", "niveau": "region", "confiance_geo": 0.90},
    "île-de-france":                 {"lat": 48.80, "lon":  2.40, "code_insee": "11", "niveau": "region", "confiance_geo": 0.90},
    "ile-de-france":                 {"lat": 48.80, "lon":  2.40, "code_insee": "11", "niveau": "region", "confiance_geo": 0.90},
    "normandie":                     {"lat": 49.20, "lon":  0.30, "code_insee": "28", "niveau": "region", "confiance_geo": 0.90},
    "nouvelle-aquitaine":            {"lat": 44.50, "lon":  0.50, "code_insee": "75", "niveau": "region", "confiance_geo": 0.90},
    "occitanie":                     {"lat": 43.80, "lon":  2.50, "code_insee": "76", "niveau": "region", "confiance_geo": 0.90},
    "pays de la loire":              {"lat": 47.50, "lon": -1.00, "code_insee": "52", "niveau": "region", "confiance_geo": 0.90},
    "provence-alpes-côte d'azur":   {"lat": 43.80, "lon":  5.80, "code_insee": "93", "niveau": "region", "confiance_geo": 0.90},
    "provence-alpes-cote d'azur":   {"lat": 43.80, "lon":  5.80, "code_insee": "93", "niveau": "region", "confiance_geo": 0.90},
}

# Alias lookup set (for KNOWN_REGION_NAMES backward compatibility)
KNOWN_REGION_NAMES: frozenset[str] = frozenset(REGION_COORDS.keys())

# Coordonnées des DOM-TOM (hors API geo.gouv.fr)
DOM_TOM_COORDS: dict[str, dict[str, Any]] = {
    "guadeloupe":             {"lat": 16.25,  "lon": -61.55, "code_insee": "971", "niveau": "region", "confiance_geo": 0.95},
    "martinique":             {"lat": 14.65,  "lon": -61.00, "code_insee": "972", "niveau": "region", "confiance_geo": 0.95},
    "guyane":                 {"lat": 3.93,   "lon": -53.13, "code_insee": "973", "niveau": "region", "confiance_geo": 0.95},
    "la réunion":             {"lat": -21.11, "lon":  55.54, "code_insee": "974", "niveau": "region", "confiance_geo": 0.95},
    "réunion":                {"lat": -21.11, "lon":  55.54, "code_insee": "974", "niveau": "region", "confiance_geo": 0.95},
    "mayotte":                {"lat": -12.83, "lon":  45.16, "code_insee": "976", "niveau": "region", "confiance_geo": 0.95},
    "nouvelle-calédonie":     {"lat": -20.90, "lon": 165.60, "code_insee": "988", "niveau": "region", "confiance_geo": 0.95},
    "nouvelle-caledonie":     {"lat": -20.90, "lon": 165.60, "code_insee": "988", "niveau": "region", "confiance_geo": 0.95},
    "polynésie française":    {"lat": -17.60, "lon":-149.40, "code_insee": "987", "niveau": "region", "confiance_geo": 0.95},
    "polynésie":              {"lat": -17.60, "lon":-149.40, "code_insee": "987", "niveau": "region", "confiance_geo": 0.95},
    "saint-pierre-et-miquelon": {"lat": 46.88,"lon": -56.32, "code_insee": "975", "niveau": "region", "confiance_geo": 0.95},
    "wallis-et-futuna":       {"lat": -13.29, "lon":-176.15, "code_insee": "986", "niveau": "region", "confiance_geo": 0.95},
    "saint-martin":           {"lat": 18.07,  "lon": -63.08, "code_insee": "978", "niveau": "region", "confiance_geo": 0.95},
    "saint-barthélemy":       {"lat": 17.90,  "lon": -62.83, "code_insee": "977", "niveau": "region", "confiance_geo": 0.95},
}


GeoResult = dict[str, Any]


async def geocode(lieu_nom: str | None) -> GeoResult:
    empty: GeoResult = {
        "lat": None,
        "lon": None,
        "code_insee": None,
        "niveau": "national",
        "confiance_geo": 0.0,
    }

    if not lieu_nom or lieu_nom.lower() in ("national", "france", ""):
        return empty

    lieu_clean = lieu_nom.strip()
    cache_key = lieu_clean.lower()

    if cache_key in _geo_cache:
        return _geo_cache[cache_key]

    lieu_lower = cache_key

    # Département par code exact
    if lieu_clean in DEPT_CODE_TO_NAME:
        async with _GEO_SEMAPHORE:
            result = await _geocode_departement_by_code(lieu_clean)
        _geo_cache_put(cache_key, result)
        return result

    # Département par nom exact (ex: "Paris", "Gironde")
    if lieu_lower in DEPT_NAME_TO_CODE:
        async with _GEO_SEMAPHORE:
            result = await _geocode_departement_by_code(DEPT_NAME_TO_CODE[lieu_lower])
        _geo_cache_put(cache_key, result)
        return result

    # DOM-TOM par nom normalisé (hardcoded — no API call needed)
    if lieu_lower in DOM_TOM_COORDS:
        return DOM_TOM_COORDS[lieu_lower]

    # Alias (PACA, IDF, anciens noms de régions, abréviations courantes)
    alias_target = LIEU_ALIASES.get(lieu_lower)
    if alias_target is not None:
        alias_result = await geocode(alias_target)
        if alias_result["confiance_geo"] >= 0.5:
            _geo_cache_put(cache_key, alias_result)
            return alias_result

    # Région métropolitaine connue → coordonnées hardcodées (geo.api.gouv.fr/regions n'a pas de "centre")
    if lieu_lower in REGION_COORDS:
        result = REGION_COORDS[lieu_lower]
        _geo_cache_put(cache_key, result)
        return result

    # Cascade : commune → département → commune (seuil bas)
    # Note: _geocode_region removed from cascade — geo.api.gouv.fr/regions has no "centre" field
    async with _GEO_SEMAPHORE:
        result = await _geocode_commune(lieu_clean)
    if result["confiance_geo"] >= 0.6:
        _geo_cache_put(cache_key, result)
        return result

    async with _GEO_SEMAPHORE:
        result_dept = await _geocode_departement(lieu_clean)
    if result_dept["confiance_geo"] >= 0.5:
        _geo_cache_put(cache_key, result_dept)
        return result_dept

    if result["confiance_geo"] >= 0.3:
        _geo_cache_put(cache_key, result)
        return result

    # Cache negative results too to avoid repeated failed API calls
    _geo_cache_put(cache_key, empty)
    return empty


async def _geocode_commune(lieu_nom: str) -> GeoResult:
    empty: GeoResult = {"lat": None, "lon": None, "code_insee": None, "niveau": "national", "confiance_geo": 0.0}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                BAN_URL,
                params={"q": lieu_nom, "limit": 1, "type": "municipality"},
            )
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        if not features:
            return empty

        feat = features[0]
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])

        if not coords or len(coords) < 2:
            return empty

        score = float(props.get("score", 0.0))
        code_insee = props.get("citycode") or props.get("id", "")

        return {
            "lat": float(coords[1]),
            "lon": float(coords[0]),
            "code_insee": code_insee,
            "niveau": "commune",
            "confiance_geo": round(score, 3),
        }
    except Exception as exc:
        logger.debug("BAN geocoding failed for '%s': %s", lieu_nom, exc)
        return empty


async def _geocode_departement(nom: str) -> GeoResult:
    empty: GeoResult = {"lat": None, "lon": None, "code_insee": None, "niveau": "national", "confiance_geo": 0.0}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                GEO_DEPT_URL,
                params={"nom": nom, "fields": "code,nom,centre", "limit": 1},
            )
            resp.raise_for_status()
            data = resp.json()

        if not data:
            return empty

        dept = data[0]
        centre = dept.get("centre", {})
        coords = centre.get("coordinates", [])

        if not coords or len(coords) < 2:
            return empty

        confiance = 0.7 if nom.lower() in dept.get("nom", "").lower() else 0.5

        return {
            "lat": float(coords[1]),
            "lon": float(coords[0]),
            "code_insee": dept.get("code", ""),
            "niveau": "departement",
            "confiance_geo": confiance,
        }
    except Exception as exc:
        logger.debug("Dept geocoding failed for '%s': %s", nom, exc)
        return empty


async def _geocode_departement_by_code(code: str) -> GeoResult:
    empty: GeoResult = {"lat": None, "lon": None, "code_insee": None, "niveau": "national", "confiance_geo": 0.0}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{GEO_DEPT_URL}/{code}",
                params={"fields": "code,nom,centre"},
            )
            resp.raise_for_status()
            dept = resp.json()

        centre = dept.get("centre", {})
        coords = centre.get("coordinates", [])
        if not coords or len(coords) < 2:
            return empty

        return {
            "lat": float(coords[1]),
            "lon": float(coords[0]),
            "code_insee": dept.get("code", code),
            "niveau": "departement",
            "confiance_geo": 0.9,
        }
    except Exception as exc:
        logger.debug("Dept-by-code geocoding failed for '%s': %s", code, exc)
        return empty


async def _geocode_region(nom: str) -> GeoResult:
    empty: GeoResult = {"lat": None, "lon": None, "code_insee": None, "niveau": "national", "confiance_geo": 0.0}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                GEO_REGION_URL,
                params={"nom": nom, "fields": "code,nom,centre", "limit": 1},
            )
            resp.raise_for_status()
            data = resp.json()

        if not data:
            return empty

        region = data[0]
        centre = region.get("centre", {})
        coords = centre.get("coordinates", [])

        if not coords or len(coords) < 2:
            return empty

        confiance = 0.7 if nom.lower() in region.get("nom", "").lower() else 0.5

        return {
            "lat": float(coords[1]),
            "lon": float(coords[0]),
            "code_insee": region.get("code", ""),
            "niveau": "region",
            "confiance_geo": confiance,
        }
    except Exception as exc:
        logger.debug("Region geocoding failed for '%s': %s", nom, exc)
        return empty
