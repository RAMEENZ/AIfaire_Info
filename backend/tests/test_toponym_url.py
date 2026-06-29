"""Localisation : extraction du département depuis l'URL (repli quand le LLM
renvoie « national ») et rejet des fragments génériques par le géocodeur."""
import pytest

from app.pipeline.toponym import toponym_from_url
from app.pipeline.geocoder import geocode


@pytest.mark.parametrize("url,expected", [
    ("https://www.leparisien.fr/essonne-91/morsang-sur-orge-x", "Essonne"),
    ("https://www.leparisien.fr/val-de-marne-94/le-plessis-trevise", "Val-de-Marne"),
    ("https://www.leparisien.fr/val-d-oise-95/x", "Val-d'Oise"),
    ("https://www.lepetitjournal.net/32-gers/2026/06/28/x", "Gers"),
    ("https://www.lepetitjournal.net/82-tarn-et-garonne/2026/x", "Tarn-et-Garonne"),
])
def test_department_extracted_from_url(url, expected):
    assert toponym_from_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://www.lemonde.fr/politique/article/2026/x",   # aucun département
    "https://www.example.com/top-10-des-meilleurs",       # « 10 » non corroboré par « Aube »
    "",
    "pas une url",
])
def test_no_false_positive(url):
    assert toponym_from_url(url) is None


async def test_generic_fragments_not_geocoded():
    # Fragments de noms composés / mots génériques → national (pas de pastille).
    for frag in ("Seine", "Val", "Mont", "Bourg", "Roche", "Saint"):
        r = await geocode(frag)
        assert r["niveau"] == "national" and r["lat"] is None, frag


async def test_real_places_still_resolve():
    assert (await geocode("Essonne"))["niveau"] == "departement"
    assert (await geocode("Morsang-sur-Orge"))["niveau"] == "commune"


from app.pipeline.toponym import location_from_url


def test_url_insee_gives_exact_commune_homonym_safe():
    # actu.fr encode l'INSEE : Saint-Denis 93066 (et NON la Réunion 97411).
    r = location_from_url("https://actu.fr/ile-de-france/saint-denis_93066/x_1.html")
    assert r["niveau"] == "commune" and r["code_insee"] == "93066"
    assert r["lieu_nom"] == "Saint-Denis" and 48 < r["lat"] < 49


def test_url_postal_gives_commune():
    r = location_from_url("https://www.ouest-france.fr/bretagne/rennes-35000/x")
    assert r["niveau"] == "commune" and r["lieu_nom"] == "Rennes"


def test_url_commune_from_slug_dept_disambiguated():
    # Le slug après le segment département donne la commune exacte (dans CE dept).
    r = location_from_url("https://www.leparisien.fr/essonne-91/morsang-sur-orge-le-cambriolage")
    assert r["niveau"] == "commune" and r["code_insee"] == "91434"
    assert r["lieu_nom"] == "Morsang-sur-Orge"
    # Saint-Denis en 93 (et NON la Réunion) grâce à la désambiguïsation par dept.
    r2 = location_from_url("https://www.leparisien.fr/seine-saint-denis-93/saint-denis-laffaire")
    assert r2["code_insee"] == "93066" and 48 < r2["lat"] < 49


def test_url_department_when_slug_not_a_commune():
    # Slug = titre, pas une commune → on retombe sur le département.
    r = location_from_url("https://www.leparisien.fr/essonne-91/ces-particuliers-qui-cultivent")
    assert r["niveau"] == "departement" and r["lieu_nom"] == "Essonne"


def test_url_no_location():
    assert location_from_url("https://www.lemonde.fr/politique/article/2026/x") is None
    assert location_from_url("https://x.fr/article-12345-truc") is None  # 12345 = CP inexistant
