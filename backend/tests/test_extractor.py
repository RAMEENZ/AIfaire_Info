"""Tests for the extractor's offline logic: HTML stripping, rule-based
categorisation and gravity scoring, and the source-category overrides.

`geocode` is monkeypatched to a no-op so the rule-based toponym pass
never touches the network.
"""
import pytest

from app.pipeline import extractor
from app.pipeline.extractor import (
    _strip_html,
    _rule_based_extract,
    maybe_extract,
    SOURCE_CAT_OVERRIDES,
)


@pytest.fixture(autouse=True)
def _no_network_geocode(monkeypatch):
    """Replace geocode with a stub that never resolves a location."""
    async def fake_geocode(lieu):
        return {"lat": None, "lon": None, "code_insee": None,
                "niveau": "national", "confiance_geo": 0.0}
    monkeypatch.setattr(extractor, "geocode", fake_geocode)
    # Also disable the Claude path so maybe_extract uses the rule-based fallback
    monkeypatch.setattr(extractor.settings, "ANTHROPIC_API_KEY", "")
    extractor._extract_cache.clear()
    yield
    extractor._extract_cache.clear()


# --- _strip_html --------------------------------------------------------

def test_strip_html_removes_tags():
    assert _strip_html("<p>Bonjour <b>monde</b></p>") == "Bonjour monde"


def test_strip_html_decodes_entities():
    assert _strip_html("Caf&eacute; &amp; th&eacute;") == "Café & thé"


def test_strip_html_collapses_whitespace():
    assert _strip_html("a\n\n  b\t c") == "a b c"


# --- rule-based categorisation -----------------------------------------

@pytest.mark.parametrize("text,expected_cat", [
    ("Vigilance crues orange sur la Loire", "crue"),
    ("Tempête et vent violent attendus demain", "meteo"),
    ("Séisme de magnitude 4 ressenti", "seisme"),
    ("Coupure d'électricité massive, panne de courant", "energie"),
    ("Grève SNCF : trafic ferroviaire perturbé", "transport"),
    ("Manifestation et violence urbaine en centre-ville", "ordre_public"),
    ("Alerte sanitaire : rappel de lot de listeria", "sante"),
    ("Le conseil municipal vote son budget", "actualite"),
])
async def test_categorisation(text, expected_cat):
    result = await _rule_based_extract(text, None)
    assert result["categorie"] == expected_cat


@pytest.mark.parametrize("text,expected_gravite", [
    ("Catastrophe : plusieurs morts dans l'incendie", 3),
    ("Situation critique, nombreux blessés", 2),
    ("Vigilance et prudence recommandées", 1),
    ("Réunion ordinaire du conseil", 0),
])
async def test_gravity_scoring(text, expected_gravite):
    result = await _rule_based_extract(text, None)
    assert result["gravite"] == expected_gravite


async def test_rule_based_defaults_to_national_without_toponym():
    result = await _rule_based_extract("Une réunion importante", None)
    assert result["lieu_nom"] == "national"


# --- maybe_extract ------------------------------------------------------

async def test_maybe_extract_skips_when_flagged():
    item = {"skip_extraction": True, "titre": "x", "source": "renass"}
    result = await maybe_extract(item)
    assert result is item


async def test_maybe_extract_fills_missing_fields_for_presse():
    item = {
        "source": "presse_rss",
        "titre": "Coupure d'électricité géante, panne de courant",
        "description": "",
        "auteur": "Le Monde",
    }
    result = await maybe_extract(item)
    assert result["categorie"] == "energie"
    assert result["resume_ia"]  # non-empty


async def test_source_override_forces_category():
    # ANSM is an authoritative health source -> category forced to "sante"
    item = {
        "source": "presse_rss",
        "titre": "Communiqué relatif à un produit",
        "description": "",
        "auteur": "ANSM",
    }
    result = await maybe_extract(item)
    assert result["categorie"] == "sante"


def test_source_overrides_table_contains_known_authorities():
    assert SOURCE_CAT_OVERRIDES["ansm"] == "sante"
    assert SOURCE_CAT_OVERRIDES["vigicrues"] == "crue"
    assert SOURCE_CAT_OVERRIDES["météo-france"] == "meteo"
