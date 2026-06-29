"""Durcissement config : refus des mots de passe DB faibles en prod et CORS
fail-closed (le wildcard '*' est neutralisé en production)."""
import pytest

from app.config import Settings

_STRONG = "postgresql+asyncpg://faire_info:Str0ng_Pw9x@db:5432/faire_info"


def _settings(**kw):
    base = {"DATABASE_URL": _STRONG}
    base.update(kw)
    return Settings(**base)


@pytest.mark.parametrize("pwd", ["password", "postgres", "admin", "changeme", "faire_info"])
def test_weak_db_password_rejected_in_prod(pwd):
    url = f"postgresql+asyncpg://faire_info:{pwd}@db:5432/faire_info"
    with pytest.raises(Exception):
        Settings(APP_ENV="production", DATABASE_URL=url)


def test_strong_db_password_ok_in_prod():
    assert _settings(APP_ENV="production").APP_ENV == "production"


def test_weak_password_tolerated_in_dev():
    url = "postgresql+asyncpg://faire_info:password@db:5432/faire_info"
    assert Settings(APP_ENV="development", DATABASE_URL=url).APP_ENV == "development"


def test_cors_wildcard_neutralized_in_prod():
    assert _settings(APP_ENV="production", CORS_ORIGINS="*").cors_origins_list == []


def test_cors_wildcard_allowed_in_dev():
    assert _settings(APP_ENV="development", CORS_ORIGINS="*").cors_origins_list == ["*"]


def test_cors_explicit_origins_respected_in_prod():
    s = _settings(APP_ENV="production", CORS_ORIGINS="https://faire.info, https://a.fr")
    assert s.cors_origins_list == ["https://faire.info", "https://a.fr"]
