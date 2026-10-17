"""Disjoncteur des appels Mistral : cesser d'insister quand le quota est mort.

La reprise sur 429 (test_mistral_retry.py) suppose une fenêtre qui se rouvre.
C'est vrai d'une limitation de débit, faux d'un QUOTA ÉPUISÉ — l'API refuse
alors indéfiniment, y compris une requête isolée.

Panne du 03/09/2026 : quota de complétions épuisé pendant sept jours. Chaque
ingestion a continué d'émettre ~105 articles × 4 tentatives, trois fois par
jour — de l'ordre de 10 000 appels voués à l'échec, et plusieurs minutes
d'attente ajoutées à chaque run, pour le même résultat qu'un abandon immédiat :
le repli par règles.

Même remède que pour les flux RSS morts (FeedCircuitBreaker, presse_rss.py).
"""
import time

import pytest

from app.pipeline import mistral_client
from tests.test_mistral_retry import _client_qui_repond, _reponse  # noqa: F401


def _poser_client(monkeypatch, sequence, appels) -> None:
    """Installe un faux client HTTP.

    `mistral_client._CLIENT` est un client PARTAGÉ, mémorisé dans le module (une
    poignée de main TLS par article, sinon). Le remettre à None est
    indispensable : sans cela, remplacer la fabrique en cours de test ne change
    rien — le client déjà mémorisé, et ses réponses, survivent au remplacement.
    """
    monkeypatch.setattr(mistral_client.httpx, "AsyncClient",
                        _client_qui_repond(sequence, appels))
    mistral_client._CLIENT = None


@pytest.fixture(autouse=True)
def _contexte(monkeypatch):
    """Clé posée, temporisations et cadence neutralisées, client remis à neuf."""
    async def faux_sleep(_):
        return None

    monkeypatch.setattr(mistral_client.asyncio, "sleep", faux_sleep)
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_API_KEY", "clé-de-test")
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_MAX_RETRIES", 2)
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_MIN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_CIRCUIT_THRESHOLD", 3)
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_CIRCUIT_COOLDOWN_SECONDS", 900)
    mistral_client._CLIENT = None
    mistral_client.reinitialiser_disjoncteur()
    yield
    mistral_client._CLIENT = None
    mistral_client.reinitialiser_disjoncteur()


async def test_le_circuit_s_ouvre_et_cesse_d_appeler(monkeypatch):
    """Au seuil, plus une seule requête ne part — c'est tout l'intérêt."""
    appels: list = []
    _poser_client(monkeypatch, [_reponse(429)], appels)

    for _ in range(3):  # MISTRAL_CIRCUIT_THRESHOLD échecs définitifs
        assert await mistral_client.chat([], max_tokens=10, temperature=0.1) is None

    assert mistral_client.etat_disjoncteur()["ouvert"] is True
    appels_au_seuil = len(appels)

    # Les appels suivants doivent être refusés SANS toucher au réseau.
    for _ in range(20):
        assert await mistral_client.chat([], max_tokens=10, temperature=0.1) is None
    assert len(appels) == appels_au_seuil, (
        "circuit ouvert : aucune requête ne doit plus partir"
    )


async def test_sans_disjoncteur_la_panne_coute_chaque_appel(monkeypatch):
    """Témoin : le comportement d'avant, qui a brûlé le quota une semaine."""
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_CIRCUIT_THRESHOLD", 0)
    appels: list = []
    _poser_client(monkeypatch, [_reponse(429)], appels)

    for _ in range(10):
        await mistral_client.chat([], max_tokens=10, temperature=0.1)

    # 10 articles × MISTRAL_MAX_RETRIES : rien n'arrête l'hémorragie.
    assert len(appels) == 20
    assert mistral_client.etat_disjoncteur()["ouvert"] is False


async def test_le_circuit_se_referme_apres_le_repos(monkeypatch):
    """Un quota mensuel se réarme : la reprise doit être automatique."""
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_CIRCUIT_COOLDOWN_SECONDS", 0.05)
    appels: list = []
    _poser_client(monkeypatch, [_reponse(429)], appels)
    for _ in range(3):
        await mistral_client.chat([], max_tokens=10, temperature=0.1)
    assert mistral_client.etat_disjoncteur()["ouvert"] is True

    # Repos ramené à 50 ms en tête de test : on attend pour de vrai, ce qui
    # exerce l'arithmétique réelle du repos plutôt qu'une horloge truquée.
    # Dormir plus longtemps que le repos suffit : `time.monotonic` ne recule jamais.
    time.sleep(0.06)

    assert mistral_client.etat_disjoncteur()["ouvert"] is False
    appels_avant = len(appels)
    _poser_client(monkeypatch, [_reponse(200, "revenu")], appels)
    assert await mistral_client.chat([], max_tokens=10, temperature=0.1) == "revenu"
    assert len(appels) > appels_avant, "après le repos, on doit retenter"


async def test_un_succes_remet_le_compteur_a_zero(monkeypatch):
    """Des échecs épars ne doivent pas finir par ouvrir le circuit."""
    appels: list = []
    _poser_client(monkeypatch, [_reponse(429)], appels)
    for _ in range(2):  # sous le seuil
        await mistral_client.chat([], max_tokens=10, temperature=0.1)
    assert mistral_client.etat_disjoncteur()["echecs_consecutifs"] == 2

    _poser_client(monkeypatch, [_reponse(200, "ok")], appels)
    assert await mistral_client.chat([], max_tokens=10, temperature=0.1) == "ok"
    assert mistral_client.etat_disjoncteur()["echecs_consecutifs"] == 0

    # Deux échecs de plus : toujours sous le seuil, le circuit reste fermé.
    _poser_client(monkeypatch, [_reponse(429)], appels)
    for _ in range(2):
        await mistral_client.chat([], max_tokens=10, temperature=0.1)
    assert mistral_client.etat_disjoncteur()["ouvert"] is False


async def test_une_cle_absente_n_ouvre_pas_le_circuit(monkeypatch):
    """Sans clé, aucune requête n'est tentée : ce n'est pas une panne du modèle.

    Confondre les deux ferait ouvrir un circuit qui n'a rien à protéger, et
    brouillerait le diagnostic exposé par /api/metrics.
    """
    monkeypatch.setattr(mistral_client.settings, "MISTRAL_API_KEY", "")
    appels: list = []
    _poser_client(monkeypatch, [_reponse(200, "ok")], appels)

    for _ in range(10):
        assert await mistral_client.chat([], max_tokens=10, temperature=0.1) is None

    assert appels == []
    assert mistral_client.etat_disjoncteur()["echecs_consecutifs"] == 0
    assert mistral_client.etat_disjoncteur()["ouvert"] is False


async def test_le_brief_et_l_extraction_partagent_le_disjoncteur(monkeypatch):
    """Un seul circuit pour tous les appelants : le quota, lui, est commun.

    Le brief n'a aucun repli — il doit échouer TOUT DE SUITE quand le modèle est
    injoignable, au lieu d'attendre ses tentatives pour rien.
    """
    appels: list = []
    _poser_client(monkeypatch, [_reponse(429)], appels)
    for _ in range(3):  # échecs venus de l'extraction
        await mistral_client.chat([], max_tokens=10, temperature=0.1, etiquette="extraction")

    appels_avant = len(appels)
    assert await mistral_client.chat(
        [], max_tokens=1000, temperature=0.25, etiquette="brief"
    ) is None
    assert len(appels) == appels_avant, "le brief ne doit pas retenter à son tour"
