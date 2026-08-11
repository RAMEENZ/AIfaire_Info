"""Filtre des contenus marchands.

Le compromis est asymétrique : écarter un vrai article coûte une information
perdue, en laisser passer un ne coûte qu'une ligne de bruit. Les cas « à
laisser passer » sont donc au moins aussi importants que les autres.
"""
import pytest

from app.pipeline.commercial import is_commercial

# Contenus d'affiliation — relevés ou calqués sur la production du 03/08/2026.
MARCHANDS = [
    "Ce ventilateur de plafond Philips est 40 € moins cher, pratique été comme hiver",
    "Bon plan : le casque Sony à 199,99 € au lieu de 349 €",
    "Amazon casse le prix du robot cuiseur : -40 % aujourd'hui",
    "French days : notre sélection de 10 produits à prix cassé",
    "Code promo Cdiscount : la TV 4K à 449 euros seulement",
]

# Vraies informations qui emploient prix ou vocabulaire d'offre : elles doivent
# passer. C'est le vrai risque du filtre.
INFORMATIONS = [
    "Le carburant 10 centimes moins cher dans les stations du département",
    "Une amende de 135 € pour les automobilistes contrevenants",
    "Les soldes d'été démarrent ce mercredi dans les commerces du centre-ville",
    "Budget municipal : 2 millions d'euros pour la rénovation du gymnase",
    "Le SYDNE obtient 2 millions d'euros de réduction de la TGAP pour La Réunion",
    "Un logement à 900 euros par mois, le nouveau seuil dans la métropole",
    "Trois individus condamnés à 2 000 € d'amende",
    "Incendie à Corte : 5 000 m² parcourus, il est désormais maîtrisé",
    "Le marché hebdomadaire change d'horaires",
]


@pytest.mark.parametrize("titre", MARCHANDS)
def test_un_article_daffiliation_est_ecarte(titre):
    assert is_commercial(titre) is True


@pytest.mark.parametrize("titre", INFORMATIONS)
def test_une_vraie_information_passe(titre):
    assert is_commercial(titre) is False, "faux positif : information perdue"


def test_un_prix_seul_ne_suffit_pas():
    """Sinon tout article citant un montant — budget, amende, loyer — serait
    écarté. Il faut la conjonction d'un prix et d'un vocabulaire d'offre."""
    assert is_commercial("La subvention s'élève à 250 000 euros") is False


def test_un_mot_doffre_seul_ne_suffit_pas():
    assert is_commercial("Les soldes démarrent lundi") is False


def test_un_titre_vide_ne_plante_pas():
    assert is_commercial("") is False
    assert is_commercial("", "promo 50 €") is False
