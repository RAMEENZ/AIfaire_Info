"""Tests for the connector health status computation (pure logic)."""
from datetime import datetime, timedelta, timezone

from app.api.routes.health import (
    _compute_status,
    CHRONIC_FAILURE_THRESHOLD,
    WARNING_THRESHOLD_HOURS,
    ERROR_THRESHOLD_HOURS,
    KNOWN_CONNECTORS,
)


def test_error_when_chronic_failures():
    # last_error présent ET échecs consécutifs >= seuil chronique -> erreur franche.
    assert (
        _compute_status(
            datetime.now(timezone.utc), "boom", CHRONIC_FAILURE_THRESHOLD
        )
        == "error"
    )


def test_warning_when_never_run():
    assert _compute_status(None, None) == "warning"


def test_ok_when_recent():
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    assert _compute_status(recent, None) == "ok"


def test_warning_when_stale():
    stale = datetime.now(timezone.utc) - timedelta(hours=30)
    assert _compute_status(stale, None) == "warning"


def test_error_when_very_stale():
    very_stale = datetime.now(timezone.utc) - timedelta(hours=60)
    assert _compute_status(very_stale, None) == "error"


def test_naive_datetime_is_treated_as_utc():
    # last_run without tzinfo should not raise and should be treated as UTC
    naive_recent = datetime.utcnow() - timedelta(hours=1)
    assert _compute_status(naive_recent, None) == "ok"


# --- Nouveau comportement : échec transitoire vs chronique -----------------

def test_warning_when_transient_error():
    # Échec isolé (moins de 3 runs d'affilée) : dégradé, PAS erreur — c'est le
    # changement de comportement clé (pas d'alarme rouge sur un 5xx transitoire).
    now = datetime.now(timezone.utc)
    assert _compute_status(now, "boom", 0) == "warning"
    assert _compute_status(now, "boom", CHRONIC_FAILURE_THRESHOLD - 1) == "warning"


def test_error_when_consecutive_failures_at_threshold():
    # À partir du seuil chronique, l'échec devient erreur quel que soit le délai.
    now = datetime.now(timezone.utc)
    assert _compute_status(now, "boom", CHRONIC_FAILURE_THRESHOLD) == "error"
    assert _compute_status(now, "boom", CHRONIC_FAILURE_THRESHOLD + 5) == "error"


# --- Seuils temporels (sans erreur) ----------------------------------------

def test_ok_when_run_recent_no_error():
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    assert _compute_status(recent, None) == "ok"


def test_warning_when_older_than_warning_within_error():
    stale = datetime.now(timezone.utc) - timedelta(hours=WARNING_THRESHOLD_HOURS + 1)
    assert _compute_status(stale, None) == "warning"


def test_error_when_older_than_error_threshold():
    very_stale = datetime.now(timezone.utc) - timedelta(hours=ERROR_THRESHOLD_HOURS + 1)
    assert _compute_status(very_stale, None) == "error"


def test_warning_when_never_run_no_error():
    assert _compute_status(None, None) == "warning"


# --- Garde-fou : connecteurs auparavant manquants --------------------------

def test_known_connectors_include_previously_missing():
    # Régression : la liste figée ne contenait que 8 des 12 connecteurs ;
    # cert_fr, irsn, air_quality, opensky n'apparaissaient jamais.
    for name in ("cert_fr", "irsn", "air_quality", "opensky"):
        assert name in KNOWN_CONNECTORS
