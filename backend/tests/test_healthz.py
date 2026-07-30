"""Tests for the /healthz freshness logic (pure function, offline).

Contexte : panne silencieuse de 07/2026 — scheduler mort dans un conteneur
« healthy » pendant 3 jours. compute_healthz_reasons est la logique qui doit
rendre cet état visible.
"""
from datetime import datetime, timedelta, timezone

from app.api.routes.health import compute_healthz_reasons

NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

# Valeurs par défaut de la config, passées explicitement pour des tests
# indépendants de l'environnement.
KW = dict(max_data_age_hours=26, scheduler_grace_minutes=60, boot_grace_minutes=30)


def _old_boot() -> datetime:
    return NOW - timedelta(hours=5)


def test_healthy_nominal():
    reasons = compute_healthz_reasons(
        NOW,
        _old_boot(),
        NOW + timedelta(hours=3),          # prochaine ingestion à venir
        NOW - timedelta(hours=2),          # dernier événement récent
        **KW,
    )
    assert reasons == []


def test_scheduler_stopped():
    reasons = compute_healthz_reasons(
        NOW, _old_boot(), None, NOW - timedelta(hours=2), **KW
    )
    assert reasons == ["scheduler_stopped"]


def test_ingestion_overdue_beyond_grace():
    # Heure de passage dépassée de 2 h (> 60 min de marge) : le job ne se
    # déclenche plus.
    reasons = compute_healthz_reasons(
        NOW, _old_boot(), NOW - timedelta(hours=2), NOW - timedelta(hours=2), **KW
    )
    assert reasons == ["ingestion_overdue"]


def test_ingestion_slightly_late_is_tolerated():
    # 30 min de retard < marge de 60 min (misfire en cours de rattrapage).
    reasons = compute_healthz_reasons(
        NOW, _old_boot(), NOW - timedelta(minutes=30), NOW - timedelta(hours=2), **KW
    )
    assert reasons == []


def test_stale_data_detected():
    # Scénario de la panne : scheduler qui « planifie » encore mais plus
    # aucun événement ingéré depuis 3 jours.
    reasons = compute_healthz_reasons(
        NOW, _old_boot(), NOW + timedelta(hours=3), NOW - timedelta(days=3), **KW
    )
    assert reasons == ["stale_data"]


def test_empty_database_after_grace():
    reasons = compute_healthz_reasons(
        NOW, _old_boot(), NOW + timedelta(hours=3), None, **KW
    )
    assert reasons == ["no_events_ingested"]


def test_boot_grace_tolerates_missing_or_stale_data():
    # Pendant la fenêtre de démarrage, l'ingestion initiale n'a pas fini :
    # base vide ou périmée ≠ unhealthy (sinon boucle de redémarrage au boot).
    young_boot = NOW - timedelta(minutes=5)
    assert compute_healthz_reasons(NOW, young_boot, NOW + timedelta(hours=3), None, **KW) == []
    assert (
        compute_healthz_reasons(
            NOW, young_boot, NOW + timedelta(hours=3), NOW - timedelta(days=3), **KW
        )
        == []
    )


def test_boot_grace_does_not_mask_dead_scheduler():
    # Même fraîchement démarré, un scheduler arrêté est une erreur franche.
    young_boot = NOW - timedelta(minutes=5)
    assert compute_healthz_reasons(NOW, young_boot, None, None, **KW) == ["scheduler_stopped"]


def test_multiple_reasons_cumulate():
    reasons = compute_healthz_reasons(NOW, _old_boot(), None, None, **KW)
    assert reasons == ["scheduler_stopped", "no_events_ingested"]


def test_naive_datetimes_treated_as_utc():
    reasons = compute_healthz_reasons(
        NOW,
        _old_boot().replace(tzinfo=None),
        (NOW + timedelta(hours=3)).replace(tzinfo=None),
        (NOW - timedelta(hours=2)).replace(tzinfo=None),
        **KW,
    )
    assert reasons == []


def test_future_created_at_is_healthy():
    # Horloge légèrement décalée entre hôtes : un created_at « dans le futur »
    # ne doit pas rendre unhealthy.
    reasons = compute_healthz_reasons(
        NOW, _old_boot(), NOW + timedelta(hours=3), NOW + timedelta(minutes=10), **KW
    )
    assert reasons == []
