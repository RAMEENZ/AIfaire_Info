"""Reprise sur limitation de débit de l'API Mistral.

Relevé du 11/08/2026 : 3 articles sur 15 perdus sur HTTP 429. Le code les
traitait comme des échecs définitifs et retombait sur l'extraction par règles —
résumé tronqué en milieu de phrase, aucun tag, lieu « national ». Or un 429 se
résout en patientant.
"""
import httpx
import pytest

from app.pipeline import mistral_client


def _reponse(code: int, contenu: str = "ok", entetes: dict | None = None) -> httpx.Response:
    req = httpx.Request("POST", mistral_client._URL)
    if code == 200:
        return httpx.Response(
            200, request=req,
            json={"choices": [{"message": {"content": contenu}}]},
        )
    return httpx.Response(code, request=req, headers=entetes or {}, text="nope")


@pytest.fixture(autouse=True)
def _sans_attente(monkeypatch):
    """Neutralise les temporisations : on teste la logique, pas l'horloge."""
    dormi: list[float] = []

    async def faux_sleep(d):
        dormi.append(d)

    monkeypatch.setattr(mistral_client.asyncio, "sleep", faux_sleep)
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_API_KEY", "clé-de-test")
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_MAX_RETRIES", 4)
    # Cadence neutralisée par défaut : ces tests mesurent le RECUL de reprise,
    # et l'espacement s'y ajouterait sans rien démontrer. Les tests de cadence
    # la réactivent explicitement (fixture _cadence).
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_MIN_INTERVAL_SECONDS", 0)
    # Le client partagé est un état de MODULE : sans remise à zéro, le faux
    # client d'un test survivrait au suivant, qui croirait poser ses propres
    # réponses tout en lisant celles du précédent.
    mistral_client._CLIENT = None
    yield dormi
    mistral_client._CLIENT = None


def _client_qui_repond(sequence: list[httpx.Response], appels: list):
    class FauxClient:
        # `is_closed` : le client réel est désormais partagé entre les appels
        # (une poignée de main TLS par article, sinon), et mistral_client
        # interroge cet attribut pour savoir s'il doit en recréer un.
        is_closed = False

        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *args, **kwargs):
            appels.append(kwargs.get("json"))
            return sequence[min(len(appels) - 1, len(sequence) - 1)]
    return lambda **kw: FauxClient()


async def test_429_puis_succes(monkeypatch, _sans_attente):
    """Le cas qui coûtait 3 articles sur 15 : on réessaie, et ça passe."""
    appels: list = []
    monkeypatch.setattr(mistral_client.httpx, "AsyncClient",
                        _client_qui_repond([_reponse(429), _reponse(200, "résultat")], appels))

    assert await mistral_client.chat([], max_tokens=10, temperature=0.1) == "résultat"
    assert len(appels) == 2
    assert len(_sans_attente) == 1  # une seule attente, avant la 2e tentative


async def test_429_persistant_abandonne_apres_le_quota(monkeypatch, _sans_attente):
    """On n'insiste pas indéfiniment : l'ingestion ne doit pas se figer."""
    appels: list = []
    monkeypatch.setattr(mistral_client.httpx, "AsyncClient",
                        _client_qui_repond([_reponse(429)], appels))

    assert await mistral_client.chat([], max_tokens=10, temperature=0.1) is None
    assert len(appels) == 4  # MISTRAL_MAX_RETRIES


@pytest.mark.parametrize("code", [400, 401, 403, 404])
async def test_erreurs_definitives_non_reessayees(monkeypatch, code, _sans_attente):
    """Une clé invalide ou une requête malformée ne se répare pas en attendant."""
    appels: list = []
    monkeypatch.setattr(mistral_client.httpx, "AsyncClient",
                        _client_qui_repond([_reponse(code)], appels))

    assert await mistral_client.chat([], max_tokens=10, temperature=0.1) is None
    assert len(appels) == 1


@pytest.mark.parametrize("code", [500, 502, 503, 504])
async def test_pannes_serveur_reessayees(monkeypatch, code, _sans_attente):
    appels: list = []
    monkeypatch.setattr(mistral_client.httpx, "AsyncClient",
                        _client_qui_repond([_reponse(code), _reponse(200, "ok")], appels))

    assert await mistral_client.chat([], max_tokens=10, temperature=0.1) == "ok"
    assert len(appels) == 2


def test_retry_after_respecte():
    """L'API sait mieux que nous quand sa fenêtre se rouvre."""
    assert mistral_client._delai_avant_reprise(_reponse(429, entetes={"Retry-After": "7"}), 0) == 7.0


def test_retry_after_borne():
    """Une annonce de 300 s ne doit pas figer l'ingestion pour autant."""
    assert mistral_client._delai_avant_reprise(_reponse(429, entetes={"Retry-After": "300"}), 0) == 30.0


def test_recul_exponentiel_sans_entete():
    """À défaut d'indication, on espace, avec du bruit contre les reprises groupées."""
    d0 = mistral_client._delai_avant_reprise(None, 0)
    d3 = mistral_client._delai_avant_reprise(None, 3)
    assert 1.0 <= d0 < 1.5
    assert 8.0 <= d3 < 8.5


async def test_sans_cle_aucun_appel(monkeypatch):
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_API_KEY", "")
    assert await mistral_client.chat([], max_tokens=10, temperature=0.1) is None


# ── Cadence : borner le débit à la source ───────────────────────────────────

@pytest.fixture
def _cadence(monkeypatch):
    """Espacement actif, chronomètre remis à zéro entre les tests."""
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_MIN_INTERVAL_SECONDS", 1.0)
    monkeypatch.setattr(mistral_client, "_dernier_depart", 0.0)


async def test_premier_appel_ne_patiente_pas(_sans_attente, _cadence):
    await mistral_client._respecter_la_cadence()
    assert _sans_attente == []


async def test_appel_suivant_espace_du_delai_demande(_sans_attente, _cadence):
    """Deux départs rapprochés : le second attend l'intervalle."""
    await mistral_client._respecter_la_cadence()
    await mistral_client._respecter_la_cadence()
    assert len(_sans_attente) == 1
    assert 0.9 < _sans_attente[0] <= 1.0


async def test_rafale_entierement_etalee(_sans_attente, _cadence):
    """Le cas réel : plusieurs articles lancés ensemble ne partent pas en rafale.

    C'est ce qui manquait le 11/08/2026 — dix appels simultanés contre une API
    limitée en débit, 5 articles sur 15 perdus malgré quatre tentatives.
    """
    import asyncio as aio
    await aio.gather(*(mistral_client._respecter_la_cadence() for _ in range(5)))
    # Quatre attentes pour cinq départs : seul le premier part sans délai.
    assert len(_sans_attente) == 4


async def test_intervalle_nul_desactive_la_cadence(_sans_attente, monkeypatch):
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_MIN_INTERVAL_SECONDS", 0)
    for _ in range(5):
        await mistral_client._respecter_la_cadence()
    assert _sans_attente == []


async def test_chat_applique_la_cadence(monkeypatch, _sans_attente, _cadence):
    """Le câblage, pas seulement la fonction.

    Les tests ci-dessus appellent _respecter_la_cadence directement : retirer
    son appel de chat() les laissait tous passer. Ce test-ci échoue si le
    câblage disparaît — c'est lui qui protège le correctif.
    """
    appels: list = []
    monkeypatch.setattr(mistral_client.httpx, "AsyncClient",
                        _client_qui_repond([_reponse(200, "ok")], appels))

    await mistral_client.chat([], max_tokens=10, temperature=0.1)
    await mistral_client.chat([], max_tokens=10, temperature=0.1)

    assert len(appels) == 2
    # Deux requêtes réussies, aucune reprise : la seule attente possible est
    # l'espacement du second départ.
    assert len(_sans_attente) == 1
    assert 0.9 < _sans_attente[0] <= 1.0
