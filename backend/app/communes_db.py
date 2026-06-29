"""Base locale de geolocalisation des communes francaises (hors-ligne).

Charge `app/data/communes_geo.csv` (~35 000 communes enrichies de leurs
coordonnees GPS, code INSEE, population) dans un index en memoire et resout un
nom de commune en coordonnees SANS appel reseau. Sert de source prioritaire au
geocodeur ; l'API BAN externe ne reste qu'un repli pour les noms absents.

Le fichier CSV est genere par `backend/scripts/build_communes_db.py`.
"""
from __future__ import annotations

import csv
import logging
import os
import unicodedata
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "communes_geo.csv")

# nom normalise -> meilleur enregistrement (commune la plus peuplee en cas
# d'homonymie, p.ex. plusieurs "Sainte-Croix").
_INDEX: dict[str, dict[str, Any]] = {}
# code INSEE -> enregistrement (clé UNIQUE : une commune = un INSEE). Permet une
# résolution exacte sans ambiguïté d'homonyme (URL actu.fr « commune_INSEE »).
_BY_INSEE: dict[str, dict[str, Any]] = {}
# code postal -> liste d'enregistrements (un CP peut couvrir plusieurs communes).
_BY_POSTAL: dict[str, list[dict[str, Any]]] = {}
# (nom normalisé, département) -> enregistrement. Permet de résoudre une commune
# par son nom SANS ambiguïté d'homonyme quand on connaît le département (ex.
# extraction depuis le slug d'une URL leparisien.fr « essonne-91/morsang-… »).
_BY_NAME_DEPT: dict[tuple[str, str], dict[str, Any]] = {}
_loaded = False


def normalize(name: str) -> str:
    """Identique a la normalisation du script de build : indispensable pour que
    les cles d'index et les requetes coincident.
    UPPERCASE, sans accents/ligatures, ST/STE -> SAINT/SAINTE, separateurs -> espace."""
    s = name.replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae").replace("Æ", "AE")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    toks = ["SAINT" if t == "ST" else "SAINTE" if t == "STE" else t for t in s.split()]
    return " ".join(toks)


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True  # on ne retente pas en boucle si le fichier manque
    if not os.path.exists(_DATA_PATH):
        logger.warning("communes_geo.csv introuvable (%s) : geocodage local desactive", _DATA_PATH)
        return
    n = 0
    with open(_DATA_PATH, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rec = {
                    "lat": float(r["lat"]),
                    "lon": float(r["lon"]),
                    "code_insee": r["code_insee"],
                    "population": int(r["population"] or 0),
                    "dept": r["dept"],
                    "nom": r.get("nom") or r["nom_norm"].title(),
                }
            except (KeyError, ValueError):
                continue
            key = r["nom_norm"]
            prev = _INDEX.get(key)
            # En cas d'homonymie, on garde la commune la plus peuplee.
            if prev is None or rec["population"] > prev["population"]:
                _INDEX[key] = rec
            _BY_INSEE[rec["code_insee"]] = rec
            _BY_POSTAL.setdefault(r["code_postal"], []).append(rec)
            dk = (key, rec["dept"])
            prevd = _BY_NAME_DEPT.get(dk)
            if prevd is None or rec["population"] > prevd["population"]:
                _BY_NAME_DEPT[dk] = rec
            n += 1
    logger.info(
        "Base communes locale chargee : %d lignes, %d noms, %d INSEE, %d CP",
        n, len(_INDEX), len(_BY_INSEE), len(_BY_POSTAL),
    )


def _as_result(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "lat": rec["lat"],
        "lon": rec["lon"],
        "code_insee": rec["code_insee"],
        "nom": rec["nom"],
        "dept": rec["dept"],
        "niveau": "commune",
        "confiance_geo": 0.9,
    }


def lookup_in_dept(name: Optional[str], dept: Optional[str]) -> Optional[dict[str, Any]]:
    """Résout un nom de commune DANS un département donné (désambiguïse les
    homonymes : « Saint-Denis » en 93 ≠ à la Réunion). None si absent."""
    if not name or not dept:
        return None
    _load()
    rec = _BY_NAME_DEPT.get((normalize(name), dept))
    return _as_result(rec) if rec else None


def lookup_by_insee(code: Optional[str]) -> Optional[dict[str, Any]]:
    """Résout un code INSEE exact en commune (sans ambiguïté). None si inconnu."""
    if not code:
        return None
    _load()
    rec = _BY_INSEE.get(code.upper())
    return _as_result(rec) if rec else None


def lookup_by_postal(cp: Optional[str], name_hint: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Résout un code postal en commune. Si plusieurs communes partagent le CP,
    on privilégie celle dont le nom normalisé apparaît dans name_hint, sinon la
    plus peuplée. None si CP inconnu."""
    if not cp:
        return None
    _load()
    recs = _BY_POSTAL.get(cp)
    if not recs:
        return None
    if name_hint and len(recs) > 1:
        hint = normalize(name_hint)
        for rec in recs:
            nn = normalize(rec["nom"])
            if nn and nn in hint:
                return _as_result(rec)
    return _as_result(max(recs, key=lambda r: r["population"]))


def lookup_commune(name: Optional[str]) -> Optional[dict[str, Any]]:
    """Resout un nom de commune en GeoResult hors-ligne, ou None si absent.

    Renvoie un dict {lat, lon, code_insee, niveau:"commune", confiance_geo}.
    confiance_geo = 0.9 (centroide officiel d'une commune existante)."""
    if not name:
        return None
    _load()
    if not _INDEX:
        return None
    rec = _INDEX.get(normalize(name))
    return _as_result(rec) if rec else None
