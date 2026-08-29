"""Tests for settings parsing (CORS origins) and .env.example integrity."""
from pathlib import Path

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


# ── .env.example : il doit rester chargeable ─────────────────────────────────
# `Settings` est en `extra='forbid'` : une clé inconnue dans un fichier .env
# n'est pas ignorée, elle empêche le backend de démarrer. Le fichier d'exemple
# a porté pendant des semaines quatre SCHEDULER_HOUR_* supprimés lors du passage
# à INGEST_HOURS / BRIEF_HOURS — si bien que le `cp .env.example .env` du README
# rendait le backend impossible à lancer. Rien ne le signalait : Docker passe
# ces mêmes clés comme variables d'environnement, que pydantic ignore, donc la
# production allait bien.

_ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def _cles_actives_du_fichier_exemple() -> list[str]:
    """Clés NON commentées de .env.example, dans l'ordre du fichier."""
    cles = []
    for ligne in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cles.append(ligne.split("=", 1)[0].strip())
    return cles


def test_env_example_ne_declare_que_des_reglages_connus():
    inconnues = [c for c in _cles_actives_du_fichier_exemple() if c not in Settings.model_fields]
    assert not inconnues, (
        f"{_ENV_EXAMPLE.name} déclare des clés absentes de config.py : {inconnues}. "
        "Un réglage supprimé doit l'être ici aussi, ou être commenté."
    )


def test_env_example_se_charge_sans_erreur():
    """La procédure du README (`cp .env.example .env`) doit démarrer."""
    assert Settings(_env_file=str(_ENV_EXAMPLE)).APP_ENV == "development"
