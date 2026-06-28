"""Repli toponymique presse : si le titre cite un lieu français clair
(département, région, grande ville), on le renvoie pour géocodage. Déterministe."""
import re
import unicodedata

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
