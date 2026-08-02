"""Pagination et allègement de la charge utile de GET /events.

Contexte : la réponse par défaut renvoyait 500 événements (451 Ko de JSON
mesurés en production), dont un tiers de résumés IA invisibles tant qu'une
carte n'est pas dépliée.
"""
from app.api.routes.events import _RESUME_PREVIEW_CHARS, _truncate_resume
from app.schemas import EventList


def test_resume_court_inchange():
    assert _truncate_resume("Un résumé court.") == "Un résumé court."


def test_resume_none_reste_none():
    assert _truncate_resume(None) is None


def test_resume_long_tronque_avec_ellipse():
    texte = "Mot " * 200
    out = _truncate_resume(texte)
    assert out.endswith("…")
    assert len(out) <= _RESUME_PREVIEW_CHARS + 1


def test_troncature_ne_coupe_pas_un_mot():
    # La coupe se fait sur une frontière de mot : le texte tronqué (privé de
    # son ellipse) doit être un préfixe du texte d'origine se terminant net.
    texte = "alpha bravo charlie delta echo foxtrot golf hotel india " * 10
    out = _truncate_resume(texte)[:-1].rstrip()
    assert texte.startswith(out)
    reste = texte[len(out):]
    assert reste == "" or reste[0] in " ,;:."


def test_troncature_sans_espace_exploitable():
    # Chaîne sans espace (URL, mot très long) : on tronque quand même,
    # sans planter ni dépasser le plafond.
    texte = "a" * 500
    out = _truncate_resume(texte)
    assert out.endswith("…")
    assert len(out) <= _RESUME_PREVIEW_CHARS + 1


def test_eventlist_expose_pagination_par_defaut():
    # Rétrocompatibilité : les anciens clients qui ne passent pas offset
    # reçoivent des valeurs neutres.
    el = EventList(events=[], total=0, generated_at="2026-07-30T12:00:00Z")
    assert el.offset == 0
    assert el.has_more is False


def test_has_more_se_calcule_sur_offset_et_total():
    # Réplique la règle appliquée par l'endpoint : il reste des pages tant
    # que le rang du dernier élément renvoyé n'atteint pas le total.
    def has_more(offset, renvoyes, total):
        return offset + renvoyes < total

    assert has_more(0, 100, 761) is True
    assert has_more(700, 61, 761) is False
    assert has_more(0, 0, 0) is False
