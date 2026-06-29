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
