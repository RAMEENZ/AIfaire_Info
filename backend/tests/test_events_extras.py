"""Tests hors-ligne des ajouts sur les routes events/health :
- plafond de connexions SSE (acquire/release),
- validation du paramètre de tri,
- enregistrement de l'endpoint /metrics.
Aucune base de données ni réseau requis.
"""
from app.api.routes import events as events_module
from app.api.routes.events import (
    VALID_SORTS,
    _acquire_sse_slot,
    _release_sse_slot,
)
from app.api.routes.health import router as health_router
from app.config import settings


def _reset_sse():
    events_module._sse_active_connections = 0


def test_sse_cap_blocks_beyond_limit(monkeypatch):
    _reset_sse()
    monkeypatch.setattr(settings, "MAX_SSE_CONNECTIONS", 2)
    assert _acquire_sse_slot() is True   # 1
    assert _acquire_sse_slot() is True   # 2
    assert _acquire_sse_slot() is False  # plafond atteint
    _reset_sse()


def test_sse_release_frees_a_slot(monkeypatch):
    _reset_sse()
    monkeypatch.setattr(settings, "MAX_SSE_CONNECTIONS", 1)
    assert _acquire_sse_slot() is True
    assert _acquire_sse_slot() is False
    _release_sse_slot()
    assert _acquire_sse_slot() is True   # le créneau libéré est réutilisable
    _reset_sse()


def test_sse_release_never_goes_negative():
    _reset_sse()
    _release_sse_slot()
    _release_sse_slot()
    assert events_module._sse_active_connections == 0


def test_valid_sorts():
    assert VALID_SORTS == {"gravite", "recent", "pertinence"}


def test_metrics_route_registered():
    paths = [getattr(r, "path", None) for r in health_router.routes]
    assert "/metrics" in paths
