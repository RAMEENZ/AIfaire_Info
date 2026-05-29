"""Tests for the geocoder's offline paths.

Only exercises lookups served by the hardcoded tables (national terms,
DOM-TOM, regions, aliases) and the article-stripping/normalisation logic.
Paths that call the BAN / geo.api.gouv.fr APIs (commune & département
cascade) are deliberately NOT tested here to keep the suite offline.
"""
import pytest

from app.pipeline import geocoder
from app.pipeline.geocoder import (
    _LEADING_ARTICLE_RE,
    _geo_cache,
    _geo_cache_put,
    _MAX_GEO_CACHE,
    geocode,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure each test starts with an empty geocoding cache."""
    _geo_cache.clear()
    yield
    _geo_cache.clear()


# --- National terms -> empty result -------------------------------------

@pytest.mark.parametrize("term", [
    "national", "France", "france métropolitaine", "Hexagone",
    "l'hexagone", "Métropole", "territoire national",
])
async def test_national_terms_return_empty(term):
    result = await geocode(term)
    assert result["lat"] is None
    assert result["lon"] is None
    assert result["niveau"] == "national"
    assert result["confiance_geo"] == 0.0


async def test_none_and_blank_return_empty():
    assert (await geocode(None))["lat"] is None
    assert (await geocode("   "))["lat"] is None


async def test_article_stripped_national_returns_empty():
    # "la France" -> "france" must still be treated as national
    result = await geocode("la France")
    assert result["lat"] is None
    assert result["niveau"] == "national"


# --- Regions (hardcoded REGION_COORDS) ----------------------------------

async def test_region_bretagne():
    result = await geocode("Bretagne")
    assert result["niveau"] == "region"
    assert result["code_insee"] == "53"
    assert abs(result["lat"] - 48.20) < 0.01


async def test_region_with_leading_article():
    bare = await geocode("Normandie")
    with_article = await geocode("la Normandie")
    assert with_article["code_insee"] == bare["code_insee"] == "28"


async def test_region_accentless_variant():
    accented = await geocode("Auvergne-Rhône-Alpes")
    plain = await geocode("auvergne-rhone-alpes")
    assert accented["code_insee"] == plain["code_insee"] == "84"


# --- Aliases ------------------------------------------------------------

@pytest.mark.parametrize("alias,expected_insee", [
    ("PACA", "93"),
    ("idf", "11"),
    ("AURA", "84"),
    ("bfc", "27"),
    ("Alsace", "44"),          # -> Grand Est
    ("Lorraine", "44"),        # -> Grand Est
    ("Picardie", "32"),        # -> Hauts-de-France
    ("Limousin", "75"),        # -> Nouvelle-Aquitaine
    ("Midi-Pyrénées", "76"),   # -> Occitanie
    ("val de loire", "24"),    # -> Centre-Val de Loire
])
async def test_aliases_resolve_to_regions(alias, expected_insee):
    result = await geocode(alias)
    assert result["code_insee"] == expected_insee
    assert result["niveau"] == "region"


# --- DOM-TOM ------------------------------------------------------------
# Only the non-département territories are tested offline. The five DOM that
# are also départements (Guadeloupe 971, Martinique 972, Guyane 973,
# La Réunion 974, Mayotte 976) match DEPT_NAME_TO_CODE first and therefore
# resolve through the geo.api.gouv.fr département-by-code endpoint, which is
# a network path excluded from this offline suite.

@pytest.mark.parametrize("name,expected_insee", [
    ("guyane française", "973"),
    ("Réunion", "974"),               # bare form; dept key is "la réunion"
    ("Nouvelle-Calédonie", "988"),
    ("nouvelle calédonie", "988"),
    ("Polynésie", "987"),
    ("Wallis-et-Futuna", "986"),
    ("Saint-Martin", "978"),
    ("saint-barthelemy", "977"),
    ("Saint-Pierre-et-Miquelon", "975"),
])
async def test_dom_tom_lookup(name, expected_insee):
    result = await geocode(name)
    assert result["code_insee"] == expected_insee
    assert result["confiance_geo"] >= 0.9


# --- Caching ------------------------------------------------------------

async def test_result_is_cached():
    assert "bretagne" not in _geo_cache
    await geocode("Bretagne")
    assert "bretagne" in _geo_cache


async def test_cache_key_is_case_insensitive():
    await geocode("BRETAGNE")
    # cache key is lowercased
    assert "bretagne" in _geo_cache


# --- Module-level helpers ----------------------------------------------

@pytest.mark.parametrize("raw,stripped", [
    ("le Var", "var"),
    ("la Gironde", "gironde"),
    ("les Ardennes", "ardennes"),
    ("l'Hérault", "hérault"),
    ("l'Hexagone", "hexagone"),
])
def test_leading_article_regex(raw, stripped):
    m = _LEADING_ARTICLE_RE.match(raw.lower())
    assert m is not None
    assert m.group(1).strip() == stripped


def test_leading_article_regex_no_match():
    # "Lyon" has no leading article
    assert _LEADING_ARTICLE_RE.match("lyon") is None
    # "lave" starts with "la" but not "la " (no space) -> no match
    assert _LEADING_ARTICLE_RE.match("lave") is None


def test_geo_cache_put_evicts_when_full():
    _geo_cache.clear()
    sentinel = {"lat": 1.0, "lon": 1.0, "code_insee": "x", "niveau": "region", "confiance_geo": 1.0}
    for i in range(_MAX_GEO_CACHE):
        _geo_cache[f"key{i}"] = sentinel
    assert len(_geo_cache) == _MAX_GEO_CACHE
    # next put should clear then insert
    _geo_cache_put("overflow", sentinel)
    assert len(_geo_cache) == 1
    assert "overflow" in _geo_cache
