"""Tests for settings parsing (CORS origins)."""
from app.config import Settings


def test_cors_wildcard():
    assert Settings(CORS_ORIGINS="*").cors_origins_list == ["*"]


def test_cors_single_origin():
    assert Settings(CORS_ORIGINS="https://faire.info").cors_origins_list == ["https://faire.info"]


def test_cors_multiple_origins_trimmed():
    s = Settings(CORS_ORIGINS="https://a.com, https://b.com ,https://c.com")
    assert s.cors_origins_list == ["https://a.com", "https://b.com", "https://c.com"]


def test_cors_ignores_empty_entries():
    assert Settings(CORS_ORIGINS="https://a.com,,").cors_origins_list == ["https://a.com"]


def test_default_limits_are_coherent():
    s = Settings()
    assert s.DEFAULT_EVENTS_LIMIT <= s.MAX_EVENTS_LIMIT
