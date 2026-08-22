"""Bornes du téléchargement d'article : taille du corps et revalidation SSRF.

Le fetcher lisait `resp.text`, donc la réponse entière en mémoire, sans aucune
limite — et jusqu'à 15 téléchargements tournent en parallèle. Une page
anormalement lourde, ou un serveur hostile répondant un flux sans fin,
suffisait à faire enfler le processus.

Le passage en lecture par morceaux a réécrit la boucle de redirection : ces
tests vérifient donc AUSSI que la revalidation SSRF de chaque saut a survécu à
la réécriture. C'est la protection qui coûterait le plus cher à perdre en
silence.
"""
import httpx
import pytest

from app.pipeline import fetcher


class _ReponseStream:
    """Réponse minimale imitant l'interface `client.stream(...)` d'httpx."""

    def __init__(self, corps: bytes, *, entetes: dict | None = None, code: int = 200,
                 location: str | None = None):
        self._corps = corps
        self.status_code = code
        self.headers = entetes or {}
        if location:
            self.headers = {**self.headers, "location": location}
        self.encoding = "utf-8"
        self._location = location

    @property
    def is_redirect(self) -> bool:
        return self._location is not None

    @property
    def has_redirect_location(self) -> bool:
        return self._location is not None

    def raise_for_status(self):
        return None

    async def aiter_bytes(self):
        # Par tranches de 64 Kio, comme le ferait httpx.
        for i in range(0, len(self._corps), 65536):
            yield self._corps[i : i + 65536]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _client_qui_sert(reponses: list[_ReponseStream], visitees: list[str]):
    class FauxClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        def stream(self, methode, url, **kw):
            visitees.append(url)
            return reponses[min(len(visitees) - 1, len(reponses) - 1)]

    return lambda **kw: FauxClient()


@pytest.fixture(autouse=True)
def _sans_reseau_ni_robots(monkeypatch):
    """Neutralise DNS, robots.txt et le cache : on teste la boucle de lecture."""
    async def toujours_sur(url):
        return True

    async def toujours_permis(url):
        return True

    monkeypatch.setattr(fetcher, "_is_safe_url", toujours_sur)
    monkeypatch.setattr(fetcher, "peut_telecharger", toujours_permis)
    monkeypatch.setattr(fetcher, "trafilatura", _TrafiTexte())
    fetcher._article_cache.clear()


class _TrafiTexte:
    """trafilatura de substitution : renvoie le HTML reçu, sans extraction."""

    @staticmethod
    def extract(html, **kw):
        return html


async def test_corps_trop_gros_refuse(monkeypatch):
    # Plafond abaissé et corps de taille FIXE. Dimensionner le corps à partir
    # de `_MAX_BODY_BYTES` — première version de ce test — le rendait
    # increvable : relever la constante agrandissait le corps d'autant, et le
    # test passait toujours. Il ne prouvait donc rien.
    monkeypatch.setattr(fetcher, "_MAX_BODY_BYTES", 1_000)
    visitees: list[str] = []
    monkeypatch.setattr(fetcher.httpx, "AsyncClient",
                        _client_qui_sert([_ReponseStream(b"x" * 5_000)], visitees))

    assert await fetcher.fetch_article_text("https://exemple.fr/a") is None


async def test_content_length_excessif_refuse_avant_lecture(monkeypatch):
    """Une taille annoncée trop grande évite même de commencer la lecture."""
    monkeypatch.setattr(fetcher, "_MAX_BODY_BYTES", 1_000)
    visitees: list[str] = []
    # Corps volontairement VALIDE et assez long pour franchir le seuil des
    # 150 caractères : avec un corps court, le test passerait même sans
    # contrôle du content-length, l'article étant rejeté pour brièveté. Il ne
    # démontrerait alors rien.
    corps = ("Un article parfaitement lisible. " * 20).encode()
    assert len(corps) > 150
    reponse = _ReponseStream(corps, entetes={"content-length": "5000"})
    monkeypatch.setattr(fetcher.httpx, "AsyncClient",
                        _client_qui_sert([reponse], visitees))

    assert await fetcher.fetch_article_text("https://exemple.fr/a") is None


async def test_corps_juste_sous_le_plafond_accepte(monkeypatch):
    """Le plafond ne doit pas rejeter ce qui tient dedans."""
    monkeypatch.setattr(fetcher, "_MAX_BODY_BYTES", 5_000)
    visitees: list[str] = []
    corps = ("Un article de presse. " * 40).encode()
    assert len(corps) < 5_000
    monkeypatch.setattr(fetcher.httpx, "AsyncClient",
                        _client_qui_sert([_ReponseStream(corps)], visitees))

    assert await fetcher.fetch_article_text("https://exemple.fr/a") is not None


async def test_corps_normal_accepte(monkeypatch):
    corps = ("Un article de presse. " * 40).encode()
    visitees: list[str] = []
    monkeypatch.setattr(fetcher.httpx, "AsyncClient",
                        _client_qui_sert([_ReponseStream(corps)], visitees))

    texte = await fetcher.fetch_article_text("https://exemple.fr/a")
    assert texte is not None and "article de presse" in texte


async def test_octets_invalides_ne_perdent_pas_l_article(monkeypatch):
    """Un octet mal encodé ne doit pas faire jeter tout le texte."""
    corps = "Article à Lyon. ".encode() * 20 + b"\xff\xfe"
    visitees: list[str] = []
    monkeypatch.setattr(fetcher.httpx, "AsyncClient",
                        _client_qui_sert([_ReponseStream(corps)], visitees))

    texte = await fetcher.fetch_article_text("https://exemple.fr/a")
    assert texte is not None and "Article à Lyon" in texte


async def test_redirection_vers_adresse_privee_toujours_bloquee(monkeypatch):
    """La revalidation SSRF de chaque saut doit survivre à la réécriture.

    Une 302 vers le service de métadonnées cloud (169.254.169.254) est le cas
    d'école : l'URL de départ est publique et passe le contrôle initial.
    """
    visitees: list[str] = []
    reponses = [
        _ReponseStream(b"", code=302, location="http://169.254.169.254/latest/meta-data/"),
        _ReponseStream(b"secret" * 100),
    ]
    monkeypatch.setattr(fetcher.httpx, "AsyncClient", _client_qui_sert(reponses, visitees))

    async def sur_sauf_metadata(url):
        return "169.254." not in url

    monkeypatch.setattr(fetcher, "_is_safe_url", sur_sauf_metadata)

    assert await fetcher.fetch_article_text("https://exemple.fr/a") is None
    # Le saut interdit ne doit même pas avoir été demandé.
    assert not any("169.254" in u for u in visitees)


async def test_boucle_de_redirections_abandonnee(monkeypatch):
    visitees: list[str] = []
    boucle = [_ReponseStream(b"", code=302, location="https://exemple.fr/suivant")] * 10
    monkeypatch.setattr(fetcher.httpx, "AsyncClient", _client_qui_sert(boucle, visitees))

    assert await fetcher.fetch_article_text("https://exemple.fr/a") is None
    assert len(visitees) <= fetcher._MAX_REDIRECTS + 1
