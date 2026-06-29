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


def toponym_from_url(url: str) -> str | None:
    """Extrait un département depuis le chemin de l'URL, par corroboration
    code + nom dans un même segment (évite les faux positifs type « top-10 » où
    « 10 » serait pris pour l'Aube). Renvoie le nom du département ou None."""
    if not url:
        return None
    try:
        segments = [s for s in urlparse(url).path.split("/") if s]
    except (ValueError, TypeError):
        return None
    for seg in segments:
        seg_slug = _slug_norm(seg)
        tokens = seg_slug.split()
        # Codes candidats présents comme jeton (« 91 », « 2a », « 971 »).
        candidates = {t.upper() for t in tokens if t.upper() in _DEPT_CODES}
        for code in candidates:
            name_slug = _DEPT_NAME_SLUG[code]
            # Corroboration : le NOM du département apparaît aussi dans le segment.
            if name_slug and name_slug in seg_slug:
                return DEPT_CODE_TO_NAME[code]
    return None
