"""Le scheduler doit accorder une marge « misfire » généreuse : sinon un job cron
dont l'heure pile tombe pendant une micro-occupation de la boucle asyncio est
silencieusement sauté (ingestions/briefs manqués)."""
import pytest

from app.pipeline import scheduler as sch


@pytest.fixture(autouse=True)
def _reset_scheduler():
    sch._scheduler = None
    yield
    sch._scheduler = None


def test_scheduler_grants_generous_misfire_grace_time():
    s = sch.get_scheduler()
    # Marge « misfire » généreuse + coalesce, appliqués à tous les jobs via defaults.
    assert (s._job_defaults.get("misfire_grace_time") or 0) >= 300
    assert s._job_defaults.get("coalesce") is True
    # Les jobs attendus sont bien planifiés : une ingestion par heure déclarée
    # dans INGEST_HOURS, plus les briefs et la purge.
    ids = {j.id for j in s.get_jobs()}
    for heure in sch.ingest_hours():
        assert f"ingest_{heure:02d}h" in ids, heure
    for heure in sch.brief_hours():
        assert f"brief_{heure:02d}h" in ids, heure
    for jid in ("purge_daily", "stats_hourly", "freshness_check_hourly"):
        assert jid in ids, jid


def test_next_ingest_time_none_when_not_running():
    # Sans démarrage, pas de next_run_time exposé (pas de crash).
    sch.get_scheduler()
    assert sch.get_next_ingest_time() is None


# ── Rythme d'ingestion (INGEST_HOURS) ───────────────────────────────────────

def test_rythme_par_defaut_reveil_midi_fin_de_journee():
    """07h, 12h, 19h : trois passages calés sur le rythme de publication de la
    presse plutôt que sur un intervalle régulier."""
    assert sch.ingest_hours() == (7, 12, 19)


def test_l_ecart_nocturne_reste_sous_le_seuil_de_fraicheur():
    """De 19h à 07h, douze heures sans ingestion complète. Le healthcheck
    déclare le conteneur malade au-delà de HEALTHZ_MAX_DATA_AGE_HOURS : si un
    jour les heures s'écartent au point de dépasser ce seuil, le site
    passerait « unhealthy » chaque nuit sans qu'aucune panne n'ait eu lieu."""
    from app.config import settings

    heures = sch.ingest_hours()
    ecarts = [b - a for a, b in zip(heures, heures[1:])]
    ecarts.append(24 - heures[-1] + heures[0])  # le saut de nuit
    assert max(ecarts) < settings.HEALTHZ_MAX_DATA_AGE_HOURS


def test_chaque_brief_suit_une_ingestion():
    """Un brief planifié sans ingestion en amont ne ferait que reformuler le
    précédent. Chacun doit suivre une ingestion, d'assez près pour la refléter
    et d'assez loin pour la laisser finir."""
    ingestions = sch.ingest_hours()
    for brief in sch.brief_hours():
        precedentes = [h for h in ingestions if h < brief]
        assert precedentes, f"le brief de {brief}h ne suit aucune ingestion"
        ecart = brief - max(precedentes)
        assert 1 <= ecart <= 4, f"brief de {brief}h : {ecart} h après l'ingestion"


def test_les_heures_sont_lues_dans_la_configuration(monkeypatch):
    monkeypatch.setattr(sch.settings, "INGEST_HOURS", "6,11,16,21,2")
    assert sch.ingest_hours() == (2, 6, 11, 16, 21)


def test_les_heures_sont_dedoublonnees_et_triees(monkeypatch):
    """Deux fois la même heure produirait deux tâches de même identifiant,
    dont la seconde écraserait silencieusement la première."""
    monkeypatch.setattr(sch.settings, "INGEST_HOURS", "12, 7 ,12,22,17")
    assert sch.ingest_hours() == (7, 12, 17, 22)


@pytest.mark.parametrize("valeur", ["", "   ", "abc", "25,99", "-3", ",,,"])
def test_une_configuration_illisible_retombe_sur_le_defaut(monkeypatch, valeur):
    """Une faute de frappe dans le .env ne doit pas laisser l'ordonnanceur muet :
    le site se figerait sans que rien ne le signale."""
    monkeypatch.setattr(sch.settings, "INGEST_HOURS", valeur)
    assert sch.ingest_hours() == (7, 12, 19)


def test_les_valeurs_valides_survivent_aux_invalides(monkeypatch):
    monkeypatch.setattr(sch.settings, "INGEST_HOURS", "7,abc,17,42")
    assert sch.ingest_hours() == (7, 17)


def test_chaque_heure_declaree_donne_une_tache(monkeypatch):
    monkeypatch.setattr(sch.settings, "INGEST_HOURS", "8,20")
    s = sch.get_scheduler()
    ids = {j.id for j in s.get_jobs()}
    assert "ingest_08h" in ids and "ingest_20h" in ids
    assert not any(i.startswith("ingest_") and i.endswith("h") and i not in
                   {"ingest_08h", "ingest_20h"} for i in ids)


# ── Heures de brief (BRIEF_HOURS) ───────────────────────────────────────────

def test_un_brief_suit_chaque_ingestion():
    """Le passage d'ingestion de 22h n'était exploité par aucun brief : les
    briefs s'arrêtaient à 20h. Chaque heure de brief doit suivre de peu une
    heure d'ingestion, sinon le brief résume des données déjà rassises."""
    ingestions = sch.ingest_hours()
    for heure_brief in sch.brief_hours():
        ecarts = [(heure_brief - h) % 24 for h in ingestions]
        assert min(ecarts) <= 3, (
            f"le brief de {heure_brief}h ne suit aucune ingestion de moins de 3 h "
            f"(ingestions : {ingestions})"
        )


def test_les_heures_de_brief_sont_configurables(monkeypatch):
    monkeypatch.setattr(sch.settings, "BRIEF_HOURS", "8, 18")
    assert sch.brief_hours() == (8, 18)


def test_une_configuration_de_brief_illisible_retombe_sur_le_defaut(monkeypatch):
    monkeypatch.setattr(sch.settings, "BRIEF_HOURS", "nawak")
    assert sch.brief_hours() == (9, 14, 21)
