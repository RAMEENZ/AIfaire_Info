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

def test_rythme_par_defaut_toutes_les_cinq_heures_des_7h():
    """07h, 12h, 17h, 22h : un passage toutes les 5 heures à partir de 7 h.
    Le cycle ne se poursuit pas la nuit — 24 n'étant pas divisible par 5, la
    série dériverait de jour en jour et perdrait son ancrage matinal."""
    assert sch.ingest_hours() == (7, 12, 17, 22)
    ecarts = [b - a for a, b in zip((7, 12, 17, 22), (12, 17, 22))]
    assert set(ecarts) == {5}


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
    assert sch.ingest_hours() == (7, 12, 17, 22)


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
    assert sch.brief_hours() == (9, 13, 20, 23)
