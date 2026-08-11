"""Garde-fou contre les lieux inventés ou étrangers avant géocodage.

La BAN est un moteur de correspondance floue : elle répond toujours quelque
chose. Relevé du 11/08/2026 — Kiev → Quiévy (Nord, score 0,302),
Gaza → Gazaupouy (0,838), Milan → Millançay, Barcelone → Barcelonne. Aucun
seuil de score ne sépare ces cas des lieux légitimes : « Paris 15e » ne marque
que 0,869, MOINS que « Gaza ». Seule la vérification locale, exacte, tranche.
"""
import pytest

from app.pipeline.toponym import est_lieu_connu


@pytest.mark.parametrize("nom", [
    "Argenteuil", "Nanterre", "Gravelines", "Dax", "Locmariaquer",
    "Bourg-en-Bresse", "Saint-Étienne-du-Rouvray", "Dole", "Saint-Philibert",
    "Vitre", "Chateau-Thierry",          # sans accents : doit passer
    "Gironde", "Morbihan", "Val-d'Oise",  # départements
    "Bretagne", "Occitanie",              # régions
    "Paris 15e", "Lyon 3e arrondissement", "Marseille 8e",  # arrondissements
])
def test_lieux_francais_reconnus(nom):
    assert est_lieu_connu(nom) is True


@pytest.mark.parametrize("nom", [
    "Kiev", "Gaza", "Milan", "Bruxelles", "Barcelone", "Zagreb", "Tokyo",
    "Kharkiv", "Berlin", "Londres", "Moscou",   # étrangers
    "Locodole", "Nauxion",                       # inventés par le modèle
    "", "   ", None,                             # vides
])
def test_lieux_inconnus_rejetes(nom):
    assert est_lieu_connu(nom) is False
