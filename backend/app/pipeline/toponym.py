"""Repli toponymique presse : si le titre cite un lieu français clair
(département, région, grande ville), on le renvoie pour géocodage. Déterministe.

Inclut aussi un repli depuis l'URL : beaucoup d'URL de presse régionale encodent
le département dans le chemin (leparisien.fr/essonne-91/…,
lepetitjournal.net/82-tarn-et-garonne/…). Quand le LLM renvoie « national », on
récupère ce département — déterministe et sans ambiguïté d'homonyme."""
import re
import unicodedata
from urllib.parse import urlparse

from app.geo_data import DEPT_CODE_TO_NAME


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("ʼ", "'").replace("´", "'").replace("`", "'")
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


# Villes ambiguës (Tours, Cannes, Vannes, Valence = aussi mots courants) exclues.
_MAJOR_CITIES = [
    "Paris", "Marseille", "Lyon", "Toulouse", "Nice", "Nantes", "Montpellier",
    "Strasbourg", "Bordeaux", "Lille", "Rennes", "Reims", "Le Havre", "Saint-Étienne",
    "Toulon", "Grenoble", "Dijon", "Angers", "Nîmes", "Clermont-Ferrand", "Le Mans",
    "Aix-en-Provence", "Brest", "Amiens", "Limoges", "Annecy", "Perpignan", "Metz",
    "Besançon", "Orléans", "Rouen", "Mulhouse", "Caen", "Nancy", "Avignon", "Poitiers",
    "Versailles", "La Rochelle", "Calais", "Colmar", "Bourges", "Quimper", "Troyes",
    "Chambéry", "Lorient", "Bayonne", "Albi", "Tarbes", "Ajaccio", "Bastia", "Biarritz",
    "Saint-Nazaire", "Angoulême", "Dunkerque", "Valenciennes", "Arras", "Montauban",
    "Agen", "Périgueux", "Béziers", "Narbonne", "Carcassonne", "Arles", "Cherbourg",
    "Nevers", "Mâcon", "Évreux", "Châteauroux", "Belfort", "Cahors", "Rodez",
]
_REGIONS = [
    "Bretagne", "Normandie", "Occitanie", "Nouvelle-Aquitaine", "Grand Est",
    "Hauts-de-France", "Centre-Val de Loire", "Bourgogne-Franche-Comté",
    "Pays de la Loire", "Provence-Alpes-Côte d'Azur", "Auvergne-Rhône-Alpes",
    "Île-de-France", "Corse",
]

_TOPONYMS: dict[str, str] = {}
for _name in list(DEPT_CODE_TO_NAME.values()) + _REGIONS + _MAJOR_CITIES:
    _TOPONYMS.setdefault(_norm(_name), _name)
_KEYS = sorted(_TOPONYMS, key=len, reverse=True)


def toponym_from_title(titre: str) -> str | None:
    if not titre:
        return None
    text = " " + _norm(titre) + " "
    for key in _KEYS:
        if re.search(r"(?<![\w'-])" + re.escape(key) + r"(?![\w'-])", text):
            return _TOPONYMS[key]
    return None


def _slug_norm(s: str) -> str:
    """Normalise un slug d'URL : minuscules, sans accents, tout séparateur
    (-, ', _) ramené à un espace. « val-d-oise » → « val d oise »."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _norm(s)).split())


# Codes département valides (01–95, 2A/2B, DOM 971–976) et leur nom slugifié.
_DEPT_CODES: frozenset[str] = frozenset(DEPT_CODE_TO_NAME)
_DEPT_NAME_SLUG: dict[str, str] = {code: _slug_norm(name) for code, name in DEPT_CODE_TO_NAME.items()}


def _dept_match(segments: list[str]) -> tuple[str, str, int] | None:
    """Département via corroboration code + nom dans un même segment
    (évite « top-10 » → Aube). Renvoie (nom, code, index_du_segment) ou None."""
    for i, seg in enumerate(segments):
        seg_slug = _slug_norm(seg)
        candidates = {t.upper() for t in seg_slug.split() if t.upper() in _DEPT_CODES}
        for code in candidates:
            name_slug = _DEPT_NAME_SLUG[code]
            if name_slug and name_slug in seg_slug:
                return DEPT_CODE_TO_NAME[code], code, i
    return None


def toponym_from_url(url: str) -> str | None:
    """Compat : renvoie seulement le nom du département trouvé dans l'URL."""
    if not url:
        return None
    try:
        segments = [s for s in urlparse(url).path.split("/") if s]
    except (ValueError, TypeError):
        return None
    m = _dept_match(segments)
    return m[0] if m else None


# INSEE : 5 caractères (DD + 3 chiffres, ou 2A/2B + 3 chiffres). Code postal : 5 chiffres.
_INSEE_RE = re.compile(r"^(?:\d{2}|2[ab])\d{3}$")
_POSTAL_RE = re.compile(r"^\d{5}$")


def location_from_url(url: str) -> dict | None:
    """Localisation déterministe depuis l'URL, indépendante de la source.
    Priorité : code INSEE (actu.fr « commune_93066 ») > code postal
    (Ouest-France « rennes-35000 ») > département (leparisien.fr « essonne-91 »).
    Renvoie {lieu_nom, lat, lon, code_insee, niveau, dept} ou None.
    INSEE/CP donnent la COMMUNE exacte (sans ambiguïté d'homonyme)."""
    if not url:
        return None
    try:
        segments = [s for s in urlparse(url).path.split("/") if s]
    except (ValueError, TypeError):
        return None

    from app.communes_db import lookup_by_insee, lookup_by_postal, lookup_in_dept

    for seg in segments:
        seg_slug = _slug_norm(seg)
        tokens = seg_slug.split()
        for tok in tokens:
            if _INSEE_RE.match(tok):
                rec = lookup_by_insee(tok)
                if rec:
                    return {**rec, "lieu_nom": rec["nom"]}
        for tok in tokens:
            if _POSTAL_RE.match(tok):
                rec = lookup_by_postal(tok, name_hint=seg_slug)
                if rec:
                    return {**rec, "lieu_nom": rec["nom"]}

    m = _dept_match(segments)
    if not m:
        return None
    dept_name, dept_code, idx = m

    # Commune depuis le slug qui suit le segment département (cas leparisien.fr
    # « essonne-91/morsang-sur-orge-… ») : on prend le plus long préfixe de tokens
    # qui est une commune DE CE département (désambiguïse les homonymes). Place
    # ainsi l'article sur la bonne commune au lieu du centroïde départemental.
    if idx + 1 < len(segments):
        toks = _slug_norm(segments[idx + 1]).split()
        for length in range(min(7, len(toks)), 0, -1):
            rec = lookup_in_dept(" ".join(toks[:length]), dept_code)
            if rec:
                return {**rec, "lieu_nom": rec["nom"]}

    return {"lieu_nom": dept_name, "lat": None, "lon": None, "code_insee": None,
            "niveau": "departement", "dept": dept_code}
