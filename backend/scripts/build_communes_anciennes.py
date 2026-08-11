"""Construit la table des communes fusionnées (app/data/communes_anciennes_geo.csv).

Environ 2 500 communes ont fusionné depuis 2015. La presse locale continue de
les nommer — « Cran-Gevrier » pour un quartier d'Annecy, relevé le 11/08/2026 —
mais elles ont disparu de la table des communes actuelles. Le garde-fou
anti-lieu-inventé les écartait donc, et l'article sortait de la carte.

Source : @etalab/decoupage-administratif, le découpage administratif de
référence de l'État. Les entrées `commune-deleguee` et `commune-associee`
portent un `chefLieu`, c'est-à-dire le code INSEE de la commune qui les a
absorbées ; on leur attribue ses coordonnées. Les deux territoires étant
contigus, l'approximation vaut largement mieux qu'un article hors carte.

Volontairement EXCLUS : les 45 `arrondissement-municipal` (Paris, Lyon,
Marseille). Ils sont déjà reconnus par est_lieu_connu, qui retire le suffixe
d'arrondissement, et leur donner à tous le centroïde de leur ville dégraderait
une précision déjà acquise.

    python scripts/build_communes_anciennes.py

Le fichier produit est versionné : l'image Docker ne copie que app/, ce script
n'a donc pas à tourner en production.
"""
import csv
import json
import sys
import unicodedata
import urllib.request
from pathlib import Path

SOURCE = "https://unpkg.com/@etalab/decoupage-administratif/data/communes.json"
RACINE = Path(__file__).resolve().parent.parent
ACTUELLES = RACINE / "app" / "data" / "communes_geo.csv"
SORTIE = RACINE / "app" / "data" / "communes_anciennes_geo.csv"

TYPES_RETENUS = {"commune-deleguee", "commune-associee"}


def normalize(name: str) -> str:
    """Copie conforme de communes_db.normalize : les clés doivent coïncider."""
    s = name.replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae").replace("Æ", "AE")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    toks = ["SAINT" if t == "ST" else "SAINTE" if t == "STE" else t for t in s.split()]
    return " ".join(toks)


def main() -> int:
    print(f"Lecture des communes actuelles : {ACTUELLES}")
    par_insee: dict[str, dict] = {}
    noms_actuels: set[str] = set()
    with open(ACTUELLES, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            par_insee[r["code_insee"]] = r
            noms_actuels.add(r["nom_norm"])
    print(f"  {len(par_insee)} communes actuelles, {len(noms_actuels)} noms distincts")

    print(f"Téléchargement de {SOURCE}")
    with urllib.request.urlopen(SOURCE, timeout=60) as rep:
        communes = json.load(rep)
    print(f"  {len(communes)} entrées")

    lignes: list[dict] = []
    vus: set[str] = set()
    sans_chef_lieu = homonymes = 0

    for c in communes:
        if c.get("type") not in TYPES_RETENUS:
            continue
        chef = par_insee.get(c.get("chefLieu") or "")
        if chef is None:
            sans_chef_lieu += 1
            continue
        cle = normalize(c["nom"])
        # Une commune ACTUELLE ne doit jamais être masquée par une ancienne :
        # « Bourg » existe aujourd'hui, et une ancienne « Bourg » ailleurs ne
        # doit pas lui voler sa place.
        if cle in noms_actuels:
            homonymes += 1
            continue
        if cle in vus:
            continue
        vus.add(cle)
        lignes.append({
            "nom_norm": cle,
            "code_postal": chef["code_postal"],
            # INSEE de la commune de rattachement : c'est elle qui existe
            # aujourd'hui, et le filtrage par département en dépend.
            "code_insee": chef["code_insee"],
            "lat": chef["lat"],
            "lon": chef["lon"],
            # Population 0 : en cas d'homonymie, la commune actuelle l'emporte
            # toujours (communes_db départage par population).
            "population": "0",
            "dept": chef["dept"],
            # Le nom de l'ANCIENNE commune : c'est celui que la presse emploie
            # et celui que le lecteur reconnaîtra.
            "nom": c["nom"],
        })

    lignes.sort(key=lambda r: r["nom_norm"])
    with open(SORTIE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "nom_norm", "code_postal", "code_insee", "lat", "lon",
            "population", "dept", "nom",
        ])
        w.writeheader()
        w.writerows(lignes)

    print(f"\n{SORTIE} : {len(lignes)} anciennes communes")
    print(f"  {homonymes} écartées (le nom est celui d'une commune actuelle)")
    print(f"  {sans_chef_lieu} écartées (chef-lieu introuvable dans la table)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
