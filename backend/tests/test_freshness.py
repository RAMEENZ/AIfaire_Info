"""Alertes de fraîcheur : la logique de décision, hors ligne.

La panne du 03/09/2026 n'était détectable par AUCUN garde-fou existant : le
quota Mistral s'est épuisé, le brief a cessé d'être régénéré pendant sept
jours — mais l'ingestion continuait, donc les événements restaient frais,
/healthz restait vert et les 14 connecteurs restaient « ok ».

Le brief est le seul indicateur qui se fige dans ce cas : il n'a aucun repli
(brief.py n'appelle que Mistral), là où l'extraction retombe silencieusement
sur les regex.
"""
from datetime import datetime, timedelta, timezone

from app.pipeline.freshness import BRIEF_FIGE, DONNEES_PERIMEES, raisons_de_signaler

NOW = datetime(2026, 9, 10, 18, 0, tzinfo=timezone.utc)
SEUILS = {"max_data_age_hours": 26, "brief_max_age_hours": 30}


def test_tout_est_frais_aucune_alerte():
    assert raisons_de_signaler(
        NOW, NOW - timedelta(hours=1), NOW - timedelta(hours=3), **SEUILS
    ) == []


def test_la_panne_du_3_septembre_est_desormais_detectee():
    """Le cas réel : données fraîches, brief figé depuis une semaine.

    C'est exactement ce que voyait la production le 10/09 — 448 événements
    ingérés dans les 24 h, et un brief daté du 3.
    """
    raisons = raisons_de_signaler(
        NOW,
        newest_event=NOW - timedelta(minutes=30),   # l'ingestion tourne
        dernier_brief=NOW - timedelta(days=7),      # le modèle ne répond plus
        **SEUILS,
    )
    assert raisons == [BRIEF_FIGE]


def test_pipeline_mort_signale_les_donnees_perimees():
    raisons = raisons_de_signaler(
        NOW, newest_event=NOW - timedelta(hours=40), dernier_brief=NOW - timedelta(hours=2),
        **SEUILS,
    )
    assert raisons == [DONNEES_PERIMEES]


def test_les_deux_pannes_sont_signalees_separement():
    """Un motif ne doit pas en masquer un autre : ils ont des causes distinctes,
    et donc des gestes de réparation distincts."""
    raisons = raisons_de_signaler(
        NOW, newest_event=NOW - timedelta(hours=40), dernier_brief=NOW - timedelta(days=7),
        **SEUILS,
    )
    assert set(raisons) == {DONNEES_PERIMEES, BRIEF_FIGE}


def test_base_vide_ne_signale_que_les_donnees():
    """Aucun brief n'a JAMAIS été généré : rien ne s'est arrêté.

    Une base neuve, ou une instance délibérément sans clé de modèle, ne doit
    pas déclencher une alerte toutes les douze heures — on surveille une
    régénération qui cesse, pas une fonctionnalité inutilisée.
    """
    raisons = raisons_de_signaler(NOW, newest_event=None, dernier_brief=None, **SEUILS)
    assert raisons == [DONNEES_PERIMEES]


def test_le_brief_juste_sous_le_seuil_ne_declenche_pas():
    """Écart normal maximal avec BRIEF_HOURS=9,14,21 : 12 h (21h → 9h).

    Le seuil doit tolérer un créneau manqué sans crier au loup.
    """
    assert raisons_de_signaler(
        NOW, NOW - timedelta(hours=1), NOW - timedelta(hours=29), **SEUILS
    ) == []
    assert raisons_de_signaler(
        NOW, NOW - timedelta(hours=1), NOW - timedelta(hours=31), **SEUILS
    ) == [BRIEF_FIGE]


def test_horodatages_naifs_acceptes():
    """Selon le pilote, la base peut rendre un datetime sans fuseau : le
    comparer à un `now` conscient lèverait TypeError et ferait taire l'alerte
    au moment précis où elle est utile."""
    naif = (NOW - timedelta(days=7)).replace(tzinfo=None)
    assert raisons_de_signaler(NOW, NOW - timedelta(hours=1), naif, **SEUILS) == [BRIEF_FIGE]
