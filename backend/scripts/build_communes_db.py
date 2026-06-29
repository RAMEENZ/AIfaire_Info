#!/usr/bin/env python3
"""Construit la base locale de geolocalisation des communes.

Entrees :
  - communes_source.csv (a cote de ce script) : liste canonique des communes
    fournie au format `commune,code_postal` (sans coordonnees).
  - dataset officiel geo.api.gouv.fr : coordonnees GPS (centroide), code INSEE,
    population de chaque commune francaise.

Sortie :
  - ../app/data/communes_geo.csv : la base enrichie, embarquee dans le backend
    et chargee en memoire au demarrage (geocodage 100% hors-ligne).

Usage :
    python backend/scripts/build_communes_db.py
"""
import csv
import json
import os
import sys
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_IN = os.path.join(HERE, "communes_source.csv")
API_CACHE = os.path.join(HERE, "communes_api.json")
OUT = os.path.normpath(os.path.join(HERE, "..", "app", "data", "communes_geo.csv"))

GEO_API_URL = (
    "https://geo.api.gouv.fr/communes"
    "?fields=nom,code,codesPostaux,centre,codeDepartement,population"
    "&format=json&geometry=centre"
)


def normalize(name: str) -> str:
    """UPPERCASE, sans accents, apostrophes/tirets/ligatures -> espaces, et
    expansion ST/STE -> SAINT/SAINTE. Aligne le format de geo.api sur celui du
    CSV fourni. "St-Cyr-sur-Menthon" -> "SAINT CYR SUR MENTHON"."""
    s = name.replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae").replace("Æ", "AE")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    toks = ["SAINT" if t == "ST" else "SAINTE" if t == "STE" else t for t in s.split()]
    return " ".join(toks)


# Grandes villes a arrondissements : le CSV liste un code postal par
# arrondissement (PARIS 75001..75020) la ou geo.api expose la commune entiere.
# On rabat sur le centroide de la ville (INSEE de la commune-mere).
CITY_FALLBACK = {
    "PARIS": ("75056", 48.8566, 2.3522, "75"),
    "LYON": ("69123", 45.7589, 4.8414, "69"),
    "MARSEILLE": ("13055", 43.2807, 5.4009, "13"),
}


def load_api() -> list:
    if not os.path.exists(API_CACHE):
        print(f"Telechargement geo.api.gouv.fr -> {API_CACHE} ...")
        with urllib.request.urlopen(GEO_API_URL, timeout=120) as resp:
            data = resp.read()
        with open(API_CACHE, "wb") as f:
            f.write(data)
    return json.load(open(API_CACHE, encoding="utf-8"))


def main() -> int:
    api = load_api()
    by_name_cp: dict[tuple[str, str], dict] = {}
    by_name: dict[str, list[dict]] = {}
    for c in api:
        coords = (c.get("centre") or {}).get("coordinates")
        if not coords:
            continue
        rec = {
            "insee": c["code"],
            "lat": coords[1],
            "lon": coords[0],
            "pop": c.get("population") or 0,
            "dept": c.get("codeDepartement") or c["code"][:2],
            "nom": c["nom"],  # nom propre (accents/casse) pour l'affichage
        }
        nom_norm = normalize(c["nom"])
        by_name.setdefault(nom_norm, []).append(rec)
        for cp in c.get("codesPostaux", []):
            by_name_cp[(nom_norm, cp)] = rec

    rows, seen = [], set()
    matched_cp = matched_fb = unmatched = 0
    with open(CSV_IN, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            raw = (r.get("commune") or "").strip()
            cp = (r.get("code_postal") or "").strip()
            if not raw or not cp:
                continue
            nom_norm = normalize(raw)
            if (nom_norm, cp) in seen:
                continue
            seen.add((nom_norm, cp))

            out_name = nom_norm
            rec = by_name_cp.get((nom_norm, cp))
            if rec:
                matched_cp += 1
            elif (nom_norm.split() or [""])[0] in CITY_FALLBACK and (
                nom_norm in CITY_FALLBACK or all(t.isdigit() for t in nom_norm.split()[1:])
            ):
                # "MARSEILLE 01".."PARIS 20" -> indexes sous le nom de ville de base
                # pour qu'une recherche "Paris"/"Lyon"/"Marseille" matche.
                out_name = nom_norm.split()[0]
                insee, lat, lon, dept = CITY_FALLBACK[out_name]
                rec = {"insee": insee, "lat": lat, "lon": lon, "pop": 0,
                       "dept": dept, "nom": out_name.title()}
                matched_fb += 1
            else:
                dept = cp[:3] if cp[:2] in ("97", "98") else cp[:2]
                cands = [x for x in by_name.get(nom_norm, []) if x["dept"] == dept] \
                    or by_name.get(nom_norm, [])
                if cands:
                    rec = max(cands, key=lambda x: x["pop"])
                    matched_fb += 1
                else:
                    unmatched += 1
                    continue
            rows.append((out_name, cp, rec["insee"], f"{rec['lat']:.5f}",
                         f"{rec['lon']:.5f}", rec["pop"], rec["dept"],
                         rec.get("nom") or out_name.title()))

    rows.sort(key=lambda x: (x[0], x[1]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["nom_norm", "code_postal", "code_insee", "lat", "lon", "population", "dept", "nom"])
        w.writerows(rows)

    total = matched_cp + matched_fb + unmatched
    print(f"Lignes traitees       : {total}")
    print(f"  match nom+CP        : {matched_cp}")
    print(f"  match repli         : {matched_fb}")
    print(f"  non resolues        : {unmatched}  ({100*unmatched/total:.2f}%)")
    print(f"Ecrit {len(rows)} lignes / {len({x[2] for x in rows})} communes -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
