"""Tests for ingestor pure helpers: event building (incl. the lon=0.0 edge
case) and the global ingestion concurrency guard.
"""
import asyncio

import pytest

from app.pipeline import ingestor
from app.pipeline.ingestor import _build_event, ingest_all, ingestion_in_progress


def _base_item(**overrides):
    item = {
        "source": "presse_rss",
        "source_url": "https://example.com/x",
        "titre": "Titre",
        "auteur": "Source",
        "date_publication": "2026-05-29T10:00:00+00:00",
        "categorie": "actualite",
        "gravite": 0,
        "lieu_nom": "Quelque part",
    }
    item.update(overrides)
    return item


def _geo(lat=None, lon=None, conf=0.0, niveau="national", code=None):
    return {"lat": lat, "lon": lon, "code_insee": code, "niveau": niveau, "confiance_geo": conf}


def test_zero_longitude_is_preserved():
    # lon = 0.0 (Greenwich meridian crosses France) must NOT be discarded
    item = _base_item(lieu_lat=49.5, lieu_lon=0.0, lieu_confiance_geo=0.9, lieu_niveau="commune")
    event = _build_event(item, _geo())
    assert event["lieu_lon"] == 0.0
    assert event["lieu_lat"] == 49.5
    assert event["geom"] == "SRID=4326;POINT(0.0 49.5)"


def test_explicit_zero_confidence_preserved():
    item = _base_item(lieu_lat=48.0, lieu_lon=2.0, lieu_confiance_geo=0.0, lieu_niveau="commune")
    event = _build_event(item, _geo(lat=1.0, lon=1.0, conf=0.8))
    # explicit 0.0 from the item is kept, not overwritten by geo's 0.8
    assert event["lieu_confiance_geo"] == 0.0


def test_falls_back_to_geocoder_when_item_has_no_coords():
    item = _base_item()  # no lieu_lat/lon
    event = _build_event(item, _geo(lat=45.0, lon=4.0, conf=0.7, niveau="commune", code="69123"))
    assert event["lieu_lat"] == 45.0
    assert event["lieu_lon"] == 4.0
    assert event["geom"] == "SRID=4326;POINT(4.0 45.0)"


def test_no_coords_forces_national():
    item = _base_item()
    event = _build_event(item, _geo())
    assert event["geom"] is None
    assert event["lieu_niveau"] == "national"
    assert event["lieu_confiance_geo"] == 0.0


async def test_ingest_connector_times_out(monkeypatch):
    """Un connecteur dont la collecte dépasse le délai est abandonné proprement :
    0 événement, last_error renseigné, sans bloquer le reste de l'ingestion."""
    monkeypatch.setattr(ingestor.settings, "CONNECTOR_FETCH_TIMEOUT_SECONDS", 0.05)

    recorded = []

    async def fake_upsert(name, last_run, last_error, count):
        recorded.append((name, last_error, count))

    monkeypatch.setattr(ingestor, "_upsert_connector_status", fake_upsert)

    class SlowConnector:
        name = "slowpoke"
        replace_on_ingest = False
        last_run = None
        last_error = None

        async def run(self):
            await asyncio.sleep(5)  # bien au-delà du délai patché
            return [{"never": "reached"}]

    name, saved, error = await ingestor.ingest_connector(SlowConnector())

    assert name == "slowpoke"
    assert saved == 0
    assert error is not None and "timeout" in error.lower()
    # Le statut a bien été persisté avec l'erreur (→ compteur d'échecs incrémenté).
    assert recorded and recorded[-1][1] is not None


async def test_ingest_connector_succeeds_within_timeout(monkeypatch):
    """Un connecteur rapide n'est pas affecté par le garde-fou de timeout."""
    monkeypatch.setattr(ingestor.settings, "CONNECTOR_FETCH_TIMEOUT_SECONDS", 5)

    async def fake_upsert(name, last_run, last_error, count):
        pass

    async def fake_save(events):
        return len(events)

    monkeypatch.setattr(ingestor, "_upsert_connector_status", fake_upsert)
    monkeypatch.setattr(ingestor, "_save_events", fake_save)
    # Le pipeline d'enrichissement n'est pas l'objet du test : on renvoie l'item tel quel.
    monkeypatch.setattr(ingestor, "_process_item_limited", lambda item: _passthrough(item))

    class FastConnector:
        name = "speedy"
        replace_on_ingest = False
        last_run = None
        last_error = None

        async def run(self):
            return [{"source_url": "https://example.com/a"}]

    name, saved, error = await ingestor.ingest_connector(FastConnector())
    assert name == "speedy"
    assert error is None
    assert saved == 1


async def _passthrough(item):
    return item


async def test_ingest_all_skips_when_already_running(monkeypatch):
    """A second concurrent ingest_all must be a no-op (concurrency guard)."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_inner():
        started.set()
        await release.wait()
        return {"total_saved": 1}

    monkeypatch.setattr(ingestor, "_ingest_all_inner", slow_inner)

    task = asyncio.create_task(ingest_all())
    await started.wait()
    assert ingestion_in_progress() is True

    # second trigger while the first holds the lock
    second = await ingest_all()
    assert second["status"] == "skipped"
    assert second["reason"] == "already_running"

    release.set()
    await task
    assert ingestion_in_progress() is False
