"""Communes fusionnées : la presse les nomme encore, la carte doit les placer.

Environ 2 500 communes ont fusionné depuis 2015. « Cran-Gevrier », quartier
d'Annecy depuis 2017, était pris pour une invention du modèle et l'article
sortait de la carte (relevé du 11/08/2026).
"""
import pytest

from app.communes_db import lookup_by_insee, lookup_commune, lookup_by_postal
from app.pipeline.toponym import est_lieu_connu


@pytest.mark.parametrize("ancienne,rattachement", [
    ("Cran-Gevrier", "74010"),      # → Annecy (2017)
    ("Seynod", "74010"),
    ("Meythet", "74010"),
    ("Annecy-le-Vieux", "74010"),
])
def test_ancienne_commune_resolue_vers_son_chef_lieu(ancienne, rattachement):
    r = lookup_commune(ancienne)
    assert r is not None, f"{ancienne} introuvable"
    assert r["code_insee"] == rattachement
    # Le nom conservé est celui de la presse, pas celui du rattachement : c'est
    # « Cran-Gevrier » que le lecteur reconnaît dans l'article.
    assert r["nom"] == ancienne
    assert r["lat"] and r["lon"]


def test_ancienne_commune_passe_le_garde_fou():
    """Le point de départ : est_lieu_connu la rejetait, d'où l'article hors carte."""
    assert est_lieu_connu("Cran-Gevrier") is True


def test_les_inventions_restent_rejetees():
    """L'ajout ne doit pas rouvrir la porte aux lieux inventés."""
    for invente in ("Locodole", "Nauxion", "Kiev", "Gaza"):
        assert est_lieu_connu(invente) is False, invente


def test_l_index_par_insee_n_est_pas_pollue():
    """Le piège de cet ajout.

    Une ancienne commune porte le code INSEE de son chef-lieu. L'inscrire dans
    l'index par INSEE ferait répondre « Cran-Gevrier » à une recherche sur le
    code d'Annecy — et toute URL actu.fr contenant 74010 aurait été mal
    étiquetée.
    """
    assert lookup_by_insee("74010")["nom"] == "Annecy"
    assert lookup_by_insee("75056")["nom"] == "Paris"
    assert lookup_by_insee("69123")["nom"] == "Lyon"


def test_l_index_par_code_postal_n_est_pas_pollue():
    r = lookup_by_postal("74000")
    assert r is not None and r["nom"] == "Annecy"


@pytest.mark.parametrize("actuelle", ["Bourg", "Sainte-Marie", "Saint-Denis", "Colmar"])
def test_les_communes_actuelles_gardent_la_priorite(actuelle):
    """Une ancienne commune homonyme ne doit jamais voler la place d'une commune
    qui existe encore : le fichier est filtré à la construction ET au chargement.

    Le signe distinctif : une commune ACTUELLE porte son propre code INSEE, donc
    l'index par INSEE lui rend son nom. Une ancienne porte celui de son
    chef-lieu, et l'index rend un autre nom.
    """
    r = lookup_commune(actuelle)
    assert r is not None
    assert lookup_by_insee(r["code_insee"])["nom"] == r["nom"], (
        f"{actuelle} résolue vers une ancienne commune"
    )


def test_l_ancienne_commune_se_distingue_bien_de_l_actuelle():
    """Contre-épreuve du test précédent : sans elle, il pourrait passer à vide."""
    r = lookup_commune("Cran-Gevrier")
    assert lookup_by_insee(r["code_insee"])["nom"] == "Annecy" != r["nom"]
