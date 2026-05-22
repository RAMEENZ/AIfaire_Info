import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BAN_URL = "https://api-adresse.data.gouv.fr/search/"
GEO_DEPT_URL = "https://geo.api.gouv.fr/departements"
GEO_REGION_URL = "https://geo.api.gouv.fr/regions"

DEPT_CODE_TO_NAME: dict[str, str] = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence",
    "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes",
    "09": "Ariège", "10": "Aube", "11": "Aude", "12": "Aveyron",
    "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud",
    "2B": "Haute-Corse", "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse",
    "24": "Dordogne", "25": "Doubs", "26": "Drôme", "27": "Eure",
    "28": "Eure-et-Loir", "29": "Finistère", "30": "Gard", "31": "Haute-Garonne",
    "32": "Gers", "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine",
    "36": "Indre", "37": "Indre-et-Loire", "38": "Isère", "39": "Jura",
    "40": "Landes", "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire",
    "44": "Loire-Atlantique", "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne",
    "48": "Lozère", "49": "Maine-et-Loire", "50": "Manche", "51": "Marne",
    "52": "Haute-Marne", "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse",
    "56": "Morbihan", "57": "Moselle", "58": "Nièvre", "59": "Nord",
    "60": "Oise", "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme",
    "64": "Pyrénées-Atlantiques", "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales",
    "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône", "70": "Haute-Saône",
    "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie",
    "75": "Paris", "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines",
    "79": "Deux-Sèvres", "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne",
    "83": "Var", "84": "Vaucluse", "85": "Vendée", "86": "Vienne",
    "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne", "90": "Territoire de Belfort",
    "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis",
    "94": "Val-de-Marne", "95": "Val-d'Oise", "971": "Guadeloupe",
    "972": "Martinique", "973": "Guyane", "974": "La Réunion", "976": "Mayotte",
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

    if lieu_clean in DEPT_CODE_TO_NAME:
        return await _geocode_departement_by_code(lieu_clean)

    result = await _geocode_commune(lieu_clean)
    if result["confiance_geo"] >= 0.6:
        return result

    result_dept = await _geocode_departement(lieu_clean)
    if result_dept["confiance_geo"] >= 0.5:
        return result_dept

    result_region = await _geocode_region(lieu_clean)
    if result_region["confiance_geo"] >= 0.5:
        return result_region

    if result["confiance_geo"] >= 0.3:
        return result

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
