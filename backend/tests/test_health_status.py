"""Tests for the connector health status computation (pure logic)."""
from datetime import datetime, timedelta, timezone

from app.api.routes.health import _compute_status


def test_error_when_last_error_present():
    assert _compute_status(datetime.now(timezone.utc), "boom") == "error"


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
