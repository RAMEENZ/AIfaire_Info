"""Tests for geocoder resilience: a transient API error must NOT poison the
cache with a negative (national) result, and the DOM-TOM/region tables must
never be exposed as shared mutable objects.
"""
import pytest

from app.pipeline import geocoder
from app.pipeline.geocoder import geocode, _geo_cache, DOM_TOM_COORDS, REGION_COORDS


@pytest.fixture(autouse=True)
def _clear_cache():
    _geo_cache.clear()
    yield
    _geo_cache.clear()


async def test_transient_error_is_not_cached(monkeypatch):
    """If both API helpers fail transiently, the place is not cached as national."""
    async def boom_commune(_):
        return None  # simulate transient network error

    async def boom_dept(_):
        return None

    # Place absente de la base communes locale : on force le miss pour exercer
    # la cascade BAN externe (sinon la résolution hors-ligne court-circuite).
    monkeypatch.setattr(geocoder, "lookup_commune", lambda _: None)
    monkeypatch.setattr(geocoder, "_geocode_commune", boom_commune)
    monkeypatch.setattr(geocoder, "_geocode_departement", boom_dept)

    result = await geocode("Lieu-dit du Pont Cassé")  # pas une commune connue
    assert result["lat"] is None              # empty result returned to caller
    assert "lieu-dit du pont cassé" not in _geo_cache  # mais NON caché (transitoire)


async def test_commune_resolved_offline_without_network(monkeypatch):
    """Une commune connue est géolocalisée par la base locale, SANS appel BAN."""
    async def boom(_):
        raise AssertionError("BAN ne doit pas être appelée pour une commune locale")

    monkeypatch.setattr(geocoder, "_geocode_commune", boom)

    result = await geocode("Belley")
    assert result["niveau"] == "commune"
    assert result["lat"] is not None and result["lon"] is not None
    assert result["confiance_geo"] >= 0.9
    assert result["code_insee"] == "01034"


async def test_definitive_no_match_is_cached(monkeypatch):
    """A clean 'no result' (empty dict, not None) IS cached to avoid re-querying."""
    empty = {"lat": None, "lon": None, "code_insee": None, "niveau": "national", "confiance_geo": 0.0}

    async def no_match(_):
        return dict(empty)

    monkeypatch.setattr(geocoder, "_geocode_commune", no_match)
    monkeypatch.setattr(geocoder, "_geocode_departement", no_match)

    result = await geocode("Zzzznowhere")
    assert result["lat"] is None
    assert "zzzznowhere" in _geo_cache  # definitive negative IS cached


async def test_region_result_is_a_copy_not_shared_object():
    result = await geocode("Bretagne")
    assert result == REGION_COORDS["bretagne"]
    assert result is not REGION_COORDS["bretagne"]  # defensive copy
    # mutating the returned dict must not corrupt the shared table
    result["confiance_geo"] = 0.0
    assert REGION_COORDS["bretagne"]["confiance_geo"] == 0.90


async def test_dom_tom_result_is_a_copy_not_shared_object():
    result = await geocode("Nouvelle-Calédonie")
    assert result is not DOM_TOM_COORDS["nouvelle-calédonie"]
    result["code_insee"] = "000"
    assert DOM_TOM_COORDS["nouvelle-calédonie"]["code_insee"] == "988"
