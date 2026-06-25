"""Tests de résilience de BaseConnector.run().

``run()`` doit avaler les exceptions de ``fetch()`` et renvoyer ``[]`` tout en
renseignant ``last_error``, pour qu'un connecteur en panne ne fasse pas tomber
l'ingestion globale. ``app.connectors.base`` n'utilise que la bibliothèque
standard, l'import via le package est donc sans dépendance lourde.
"""
import pytest

from app.connectors.base import BaseConnector


class _BoomConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "boom"

    async def fetch(self):
        raise RuntimeError("upstream 503")


class _OkConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "ok"

    async def fetch(self):
        return [{"id": 1}, {"id": 2}]


async def test_run_swallows_fetch_exception():
    connector = _BoomConnector()
    results = await connector.run()
    assert results == []
    assert connector.last_error == "upstream 503"
    assert connector.last_run is not None


async def test_run_clears_error_on_success():
    connector = _OkConnector()
    results = await connector.run()
    assert results == [{"id": 1}, {"id": 2}]
    assert connector.last_error is None
    assert connector.last_run is not None
