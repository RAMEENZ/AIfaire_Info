"""Tests d'intégration des routes sur un vrai PostgreSQL/PostGIS.

Le reste de la suite tourne hors-ligne, sans base : rapide, mais incapable de
vérifier le SQL réellement émis (pagination, filtres spatiaux, upserts). Ces
tests comblent ce trou.

Ils ne s'exécutent que si `TEST_DATABASE_URL` est défini — la CI fournit un
service PostGIS ; en local, rien n'est requis et ils sont ignorés :

    TEST_DATABASE_URL=postgresql+asyncpg://postgres@/faire_test?host=/tmp&port=5433 pytest tests/test_integration_api.py
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL non défini : tests d'intégration ignorés"
)


@pytest.fixture
async def client():
    """Application branchée sur la base de test, schéma recréé à neuf."""
    from app.database import Base, get_db
    import app.models  # noqa: F401 — enregistre les tables
    from app.main import app

    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.session_factory = session_factory  # type: ignore[attr-defined]
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


async def _insert_events(session_factory, count: int, **overrides):
    """Insère `count` événements localisés à Lyon, du plus récent au plus ancien."""
    from app.models import Event

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        for i in range(count):
            session.add(
                Event(
                    id=str(uuid.uuid4()),
                    source=overrides.get("source", "presse_rss"),
                    source_url=f"https://example.com/a{i}-{uuid.uuid4()}",
                    titre=overrides.get("titre", f"Événement {i}"),
                    auteur="Source",
                    date_publication=now - timedelta(minutes=i),
                    categorie=overrides.get("categorie", "actualite"),
                    gravite=overrides.get("gravite", 0),
                    lieu_nom="Lyon",
                    lieu_code_insee=overrides.get("insee", "69123"),
                    lieu_lat=45.75,
                    lieu_lon=4.85,
                    lieu_niveau="commune",
                    lieu_confiance_geo=0.9,
                    geom="SRID=4326;POINT(4.85 45.75)",
                    resume_ia=overrides.get("resume", "Résumé " * 80),
                    tags=[],
                    score_confiance=1.0,
                    created_at=now - timedelta(minutes=i),
                )
            )
        await session.commit()


async def test_pagination_offset_et_has_more(client):
    await _insert_events(client.session_factory, 25)

    r1 = await client.get("/api/events?limit=10&offset=0")
    assert r1.status_code == 200
    p1 = r1.json()
    assert len(p1["events"]) == 10
    assert p1["total"] == 25
    assert p1["offset"] == 0
    assert p1["has_more"] is True

    r2 = await client.get("/api/events?limit=10&offset=20")
    p2 = r2.json()
    assert len(p2["events"]) == 5
    assert p2["has_more"] is False

    # Aucun recouvrement entre les pages.
    ids1 = {e["id"] for e in p1["events"]}
    ids2 = {e["id"] for e in p2["events"]}
    assert ids1.isdisjoint(ids2)


async def test_resume_tronque_par_defaut_et_complet_sur_demande(client):
    await _insert_events(client.session_factory, 1)

    court = (await client.get("/api/events")).json()["events"][0]["resume_ia"]
    complet = (await client.get("/api/events?full=true")).json()["events"][0]["resume_ia"]

    assert court.endswith("…")
    assert len(court) < len(complet)
    # La fiche détaillée sert toujours le texte intégral.
    event_id = (await client.get("/api/events")).json()["events"][0]["id"]
    detail = (await client.get(f"/api/events/{event_id}")).json()
    assert detail["resume_ia"] == complet


async def test_recherche_textuelle(client):
    await _insert_events(client.session_factory, 3, titre="Incendie dans le Gard")
    await _insert_events(client.session_factory, 2, titre="Conseil municipal")

    r = await client.get("/api/events?q=incendie")
    data = r.json()
    assert data["total"] == 3
    assert all("Incendie" in e["titre"] for e in data["events"])


async def test_endpoint_carte_ne_renvoie_que_les_localises(client):
    from app.models import Event

    await _insert_events(client.session_factory, 4)
    # Un événement national, sans coordonnées : il ne doit pas apparaître.
    async with client.session_factory() as session:
        session.add(
            Event(
                id=str(uuid.uuid4()), source="presse_rss",
                source_url=f"https://example.com/national-{uuid.uuid4()}",
                titre="Événement national", date_publication=datetime.now(timezone.utc),
                categorie="actualite", gravite=0, lieu_niveau="national",
                lieu_confiance_geo=0.0, tags=[], score_confiance=1.0,
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    data = (await client.get("/api/events/map")).json()
    assert data["total"] == 4
    assert all(e["lieu_lat"] is not None for e in data["events"])
    # Charge utile allégée : pas de résumé.
    assert "resume_ia" not in data["events"][0]


async def test_filtre_bbox_spatial(client):
    await _insert_events(client.session_factory, 3)  # Lyon (4.85, 45.75)

    dedans = await client.get("/api/events?bbox=45.0,4.0,46.0,5.0")
    assert dedans.json()["total"] == 3

    dehors = await client.get("/api/events?bbox=48.0,2.0,49.0,3.0")  # Paris
    assert dehors.json()["total"] == 0


async def test_brief_local_par_departement(client):
    await _insert_events(client.session_factory, 3, insee="69123", gravite=2)
    await _insert_events(client.session_factory, 2, insee="75056")

    data = (await client.get("/api/brief/local?dept=69")).json()
    assert data["dept"] == "69"
    assert data["total"] == 3
    assert len(data["faits"]) == 3

    assert (await client.get("/api/brief/local?dept=ZZ")).status_code == 422


async def test_metrics_et_healthz(client):
    await _insert_events(client.session_factory, 5)

    metrics = (await client.get("/api/metrics")).json()
    assert metrics["total_events"] == 5
    assert metrics["localized_last_24h"] == 5
    assert metrics["localized_pct_24h"] == 100

    # /healthz doit répondre (503 attendu ici : aucun scheduler démarré).
    r = await client.get("/healthz")
    assert r.status_code in (200, 503)
    assert "reasons" in r.json()


async def test_abonnement_push_upsert(client, monkeypatch):
    """Un réabonnement met à jour la ligne existante au lieu d'en créer une
    seconde — sinon un changement de département dupliquerait les envois."""
    from app.api.routes import push as push_routes
    from app.models import PushSubscription
    from sqlalchemy import select

    monkeypatch.setattr(push_routes.settings, "VAPID_PUBLIC_KEY", "pub")
    monkeypatch.setattr(push_routes.settings, "VAPID_PRIVATE_KEY", "priv")

    body = {
        "endpoint": "https://push.example.com/abc",
        "keys": {"p256dh": "k", "auth": "a"},
        "departement": "69",
        "gravite_min": 3,
    }
    assert (await client.post("/api/push/subscribe", json=body)).status_code == 200
    body["departement"] = "75"
    assert (await client.post("/api/push/subscribe", json=body)).status_code == 200

    async with client.session_factory() as session:
        rows = (await session.execute(select(PushSubscription))).scalars().all()
    assert len(rows) == 1
    assert rows[0].departement == "75"


async def test_events_stats_history_vide_sans_agregat(client):
    r = await client.get("/api/stats/history?days=30")
    assert r.status_code == 200
    assert r.json()["stats"] == []
