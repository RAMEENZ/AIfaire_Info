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
    # Les 7 jobs attendus sont bien planifiés.
    ids = {j.id for j in s.get_jobs()}
    for jid in ("ingest_morning", "ingest_midday", "ingest_evening",
                "brief_morning", "brief_midday", "brief_evening", "purge_daily"):
        assert jid in ids, jid


def test_next_ingest_time_none_when_not_running():
    # Sans démarrage, pas de next_run_time exposé (pas de crash).
    sch.get_scheduler()
    assert sch.get_next_ingest_time() is None
