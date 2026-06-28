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
                }
            except (KeyError, ValueError):
                continue
            key = r["nom_norm"]
            prev = _INDEX.get(key)
            # En cas d'homonymie, on garde la commune la plus peuplee.
            if prev is None or rec["population"] > prev["population"]:
                _INDEX[key] = rec
            n += 1
    logger.info("Base communes locale chargee : %d lignes, %d noms distincts", n, len(_INDEX))


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
    if rec is None:
        return None
    return {
        "lat": rec["lat"],
        "lon": rec["lon"],
        "code_insee": rec["code_insee"],
        "niveau": "commune",
        "confiance_geo": 0.9,
    }
