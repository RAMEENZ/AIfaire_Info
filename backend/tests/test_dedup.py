"""Tests de l'empreinte de titre (déduplication des reprises de dépêches).

Le module ``app.pipeline.dedup`` n'utilise que la bibliothèque standard, mais
l'importer via le package déclenche ``app/pipeline/__init__.py`` qui importe
sqlalchemy (pas toujours installé). Pour garder ces tests réellement sans
dépendance, on charge le module directement par son chemin.
"""
import importlib.util
import pathlib
import re

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "pipeline" / "dedup.py"
_spec = importlib.util.spec_from_file_location("dedup", _p)
dedup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dedup)

title_fingerprint = dedup.title_fingerprint


# --- Convergence : même jeu de mots significatifs -> même empreinte --------

def test_same_significant_words_collapse():
    # Ordre des mots permuté, ponctuation/accents/casse différents : même empreinte.
    a = title_fingerprint("Élection présidentielle : résultats officiels")
    b = title_fingerprint("ELECTION presidentielle resultats officiels")
    assert a is not None
    assert a == b


def test_word_order_swap_collapses():
    a = title_fingerprint("Le maire de Lyon démissionne soudainement")
    b = title_fingerprint("Démission soudaine du maire de la ville Lyon")
    # « démission » / « démissionne » diffèrent : on vérifie surtout que le tri
    # par jeu de mots rend l'empreinte insensible à l'ordre. On compare deux
    # formulations au même jeu de mots significatifs.
    c = title_fingerprint("officiels présidentielle élection résultats")
    d = title_fingerprint("résultats élection présidentielle officiels")
    assert c is not None
    assert c == d


def test_accents_and_case_insensitivity():
    # L'insensibilité aux accents/à la casse est le coeur du mécanisme.
    a = title_fingerprint("Tempête majeure frappe région bretonne")
    b = title_fingerprint("TEMPETE MAJEURE FRAPPE REGION BRETONNE")
    assert a is not None
    assert a == b


def test_stopwords_ignored():
    # Les mots-outils n'influencent pas l'empreinte.
    a = title_fingerprint("Grève nationale paralyse transports parisiens")
    b = title_fingerprint("La grève nationale qui paralyse les transports parisiens")
    assert a is not None
    assert a == b


# --- Discrimination : faits différents -> empreintes différentes -----------

def test_different_stories_differ():
    a = title_fingerprint("Élection présidentielle : résultats officiels")
    b = title_fingerprint("Incendie ravage une usine chimique lyonnaise")
    assert a is not None
    assert b is not None
    assert a != b


# --- Titres trop courts -> None --------------------------------------------

def test_too_short_returns_none():
    # « Alerte météo » : moins de 4 mots significatifs après nettoyage.
    assert title_fingerprint("Alerte météo") is None


def test_three_significant_words_returns_none():
    # Exactement 3 mots significatifs (seuil = 4) -> None.
    assert title_fingerprint("Grève transports Paris") is None


# --- Entrées vides / None -> None ------------------------------------------

def test_empty_string_returns_none():
    assert title_fingerprint("") is None


def test_none_returns_none():
    assert title_fingerprint(None) is None


# --- Déterminisme et format de sortie --------------------------------------

def test_deterministic_same_input():
    titre = "Inondations majeures dévastent plusieurs communes méridionales"
    assert title_fingerprint(titre) == title_fingerprint(titre)


def test_output_is_16_char_hex():
    fp = title_fingerprint("Élection présidentielle : résultats officiels")
    assert fp is not None
    assert len(fp) == 16
    assert re.fullmatch(r"[0-9a-f]{16}", fp) is not None
