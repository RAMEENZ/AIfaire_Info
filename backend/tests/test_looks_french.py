"""Le filtre qui décide si un article mérite un appel au modèle.

C'est un aiguillage à conséquence lourde et asymétrique : se tromper vers
« français » coûte un appel ; se tromper vers « étranger » condamne l'article à
l'extracteur par règles — catégorie approximative, résumé recopié du titre,
localisation par mots-clés. Les cas ci-dessous viennent d'un relevé de
production du 03/08/2026 où des articles manifestement français étaient écartés.
"""
import pytest

from app.pipeline.extractor import _looks_french

# Articles français qui NE contiennent aucun des indices historiques
# (« france », « paris », « préfet », les vingt métropoles…) : ils étaient tous
# jugés étrangers et privés d'extraction par le modèle.
FRANCAIS_SANS_INDICE_EVIDENT = [
    "Le chef d'état-major d'Épinal suspendu après un signalement",
    "Situation signalée à Carreau Z'ananas : la SIDR mobilisée",
    "Corte : un incendie se déclare à proximité d'habitations",
    "Le marché hebdomadaire change d'horaires",
    "Randonnée du vin",
    "Quai Sainte-Catherine à Honfleur : quels commerces rouvrent ?",
    "Le vide-grenier du quartier attend 80 exposants",
    "Un nouveau rond-point sera inauguré samedi",
]

# Dépêches internationales : les écarter épargne un appel sans rien coûter,
# elles finiraient en « national » de toute façon.
ETRANGER = [
    "Guerre en Ukraine : nouvelle frappe sur Kharkiv",
    "Élections aux États-Unis : le dépouillement se poursuit",
    "Gaza : nouveau convoi humanitaire bloqué",
    "Séisme au Japon : alerte au tsunami levée",
    "Inondations en Allemagne : des milliers d'évacués",
]


@pytest.mark.parametrize("titre", FRANCAIS_SANS_INDICE_EVIDENT)
def test_un_article_local_atteint_toujours_le_modele(titre):
    assert _looks_french(titre, "") is True


@pytest.mark.parametrize("titre", ETRANGER)
def test_une_depeche_internationale_est_ecartee(titre):
    assert _looks_french(titre, "") is False


def test_le_doute_profite_au_francais():
    """Le corpus EST de la presse française : sans indice dans un sens ni dans
    l'autre, on extrait. L'ancienne heuristique concluait l'inverse."""
    assert _looks_french("Réunion publique demain soir", "") is True
    assert _looks_french("Les travaux reprennent lundi", "") is True


def test_un_sujet_francais_touchant_letranger_reste_francais():
    """« franco-allemand », « Macron », « premier ministre » : l'article parle de
    la France même s'il nomme un pays étranger."""
    assert _looks_french("Macron en visite en Allemagne pour un sommet franco-allemand", "")
    assert _looks_french("Le premier ministre reçoit son homologue italien", "")


def test_un_pays_cite_dans_le_corps_ne_suffit_pas_a_ecarter():
    """Le marqueur étranger ne compte que dans le TITRE, qui porte le sujet.
    Dans le corps, c'est souvent une comparaison ou du contexte."""
    assert _looks_french(
        "La commune inaugure sa centrale solaire",
        "Un dispositif comparable à celui déployé en Allemagne l'an dernier.",
    )


def test_une_commune_nommee_suffit():
    """La table des 35 000 communes remplace la liste de vingt métropoles."""
    assert _looks_french("Incendie maîtrisé à Draguignan après trois heures", "")
    assert _looks_french("Le maire de Colmar inaugure la halle rénovée", "")
