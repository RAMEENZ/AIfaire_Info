"""Respect de robots.txt avant tout téléchargement de texte intégral.

Un flux RSS est publié pour être repris ; aspirer le corps de l'article pour le
passer à un modèle de langage est autre chose. 71 des 120 hôtes sondés le
11/08/2026 le refusent explicitement.
"""
import pytest

from app.pipeline import robots

TELEGRAMME = """
User-agent: Googlebot
User-agent: Bingbot
Disallow: /api/

User-agent: MistralAI-User
User-agent: ClaudeBot
User-agent: GPTBot
Disallow: /

User-agent: BadBot
Disallow: /
"""

OUVERT = """
User-agent: *
Disallow: /admin/
"""


def _serveur(reponses: dict[str, tuple[int, str]], appels: list[str]):
    """Faux client HTTP : rend le robots.txt prévu pour chaque hôte."""
    class FauxReponse:
        def __init__(self, code, texte): self.status_code, self.text = code, texte

    class FauxClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **kw):
            appels.append(url)
            for hote, (code, texte) in reponses.items():
                if hote in url:
                    return FauxReponse(code, texte)
            return FauxReponse(404, "")
    return lambda **kw: FauxClient()


@pytest.fixture(autouse=True)
def _neuf(monkeypatch):
    robots.vider_cache()
    monkeypatch.setattr(robots.settings, "RESPECT_ROBOTS_TXT", True)
    yield
    robots.vider_cache()


async def test_editeur_refusant_les_agents_ia(monkeypatch):
    """Le cas Le Télégramme : notre nom n'est pas cité, l'usage l'est.

    S'abriter derrière un nom que l'éditeur n'a pas pensé à écrire, ce serait
    respecter la lettre en trahissant l'intention.
    """
    appels: list[str] = []
    monkeypatch.setattr(robots.httpx, "AsyncClient",
                        _serveur({"letelegramme.fr": (200, TELEGRAMME)}, appels))
    assert await robots.peut_telecharger("https://www.letelegramme.fr/finistere/brest/a.html") is False


async def test_editeur_ouvert(monkeypatch):
    appels: list[str] = []
    monkeypatch.setattr(robots.httpx, "AsyncClient",
                        _serveur({"exemple.fr": (200, OUVERT)}, appels))
    assert await robots.peut_telecharger("https://exemple.fr/article/1") is True


async def test_chemin_interdit_pour_tous(monkeypatch):
    appels: list[str] = []
    monkeypatch.setattr(robots.httpx, "AsyncClient",
                        _serveur({"exemple.fr": (200, OUVERT)}, appels))
    assert await robots.peut_telecharger("https://exemple.fr/admin/secret") is False


async def test_robots_absent_vaut_permission(monkeypatch):
    """404 : l'éditeur n'a rien publié, donc rien n'est restreint."""
    appels: list[str] = []
    monkeypatch.setattr(robots.httpx, "AsyncClient", _serveur({}, appels))
    assert await robots.peut_telecharger("https://sansrobots.fr/a") is True


async def test_erreur_serveur_vaut_interdiction(monkeypatch):
    """RFC 9309 : on ne profite pas d'une panne pour passer outre."""
    appels: list[str] = []
    monkeypatch.setattr(robots.httpx, "AsyncClient",
                        _serveur({"casse.fr": (503, "")}, appels))
    assert await robots.peut_telecharger("https://casse.fr/a") is False


async def test_un_seul_appel_par_hote(monkeypatch):
    """Le cache évite que 15 téléchargements concurrents ne demandent 15 fois
    le même robots.txt."""
    appels: list[str] = []
    monkeypatch.setattr(robots.httpx, "AsyncClient",
                        _serveur({"exemple.fr": (200, OUVERT)}, appels))
    import asyncio
    await asyncio.gather(*(
        robots.peut_telecharger(f"https://exemple.fr/article/{i}") for i in range(10)
    ))
    assert len(appels) == 1


async def test_reglage_desactive(monkeypatch):
    appels: list[str] = []
    monkeypatch.setattr(robots.settings, "RESPECT_ROBOTS_TXT", False)
    monkeypatch.setattr(robots.httpx, "AsyncClient",
                        _serveur({"letelegramme.fr": (200, TELEGRAMME)}, appels))
    assert await robots.peut_telecharger("https://www.letelegramme.fr/a") is True
    assert appels == []  # aucune requête inutile


async def test_le_telechargeur_renonce_sans_requete(monkeypatch):
    """Le branchement, pas seulement la décision."""
    from app.pipeline import fetcher

    async def refuse(url): return False
    monkeypatch.setattr(fetcher, "peut_telecharger", refuse)

    appels: list[str] = []

    class ClientInterdit:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **kw):
            appels.append(url)
            raise AssertionError("aucune requête ne doit partir")

    monkeypatch.setattr(fetcher.httpx, "AsyncClient", lambda **kw: ClientInterdit())
    assert await fetcher.fetch_article_text("https://www.letelegramme.fr/a.html") is None
    assert appels == []


# ── Lecture conforme à la RFC 9309 ──────────────────────────────────────────

# Écriture réelle du Télégramme : une ligne VIDE sépare les user-agents de
# leurs règles. RobotFileParser, resté sur la convention de 1996, referme le
# groupe sur cette ligne et laisse l'interdiction sans effet.
TELEGRAMME_REEL = """User-agent: Googlebot
Disallow: /api/

# ---------------------------------- #
# IA bots                            #
# ---------------------------------- #

User-agent: anthropic-ai
User-agent: MistralAI-User
User-agent: xAI-Grok

Allow: /guide-conso/
Disallow: /
"""


async def test_ligne_vide_ne_termine_pas_un_groupe(monkeypatch):
    """Sans la lecture RFC 9309, cette interdiction s'évaporait.

    C'est le défaut le plus vicieux de ce module : la lecture naïve était
    permissive envers EXACTEMENT les éditeurs qui refusent le plus clairement.
    """
    appels: list[str] = []
    monkeypatch.setattr(robots.httpx, "AsyncClient",
                        _serveur({"letelegramme.fr": (200, TELEGRAMME_REEL)}, appels))
    assert await robots.peut_telecharger("https://www.letelegramme.fr/finistere/a.html") is False


async def test_le_chemin_autorise_du_meme_groupe_reste_permis(monkeypatch):
    """« Allow: /guide-conso/ » doit continuer de primer sur « Disallow: / »."""
    appels: list[str] = []
    monkeypatch.setattr(robots.httpx, "AsyncClient",
                        _serveur({"letelegramme.fr": (200, TELEGRAMME_REEL)}, appels))
    assert await robots.peut_telecharger("https://www.letelegramme.fr/guide-conso/x") is True


MEDIAPART_REEL = """User-agent: CCBot
Disallow: /

User-Agent: ClaudeBot
Disallow: /

User-agent: GPTBot
Disallow: /
"""


async def test_refus_d_un_autre_agent_ia_vaut_refus(monkeypatch):
    """Mediapart refuse ClaudeBot, GPTBot et CCBot mais n'a jamais écrit
    MistralAI-User. Ce n'est pas une permission, c'est un oubli — et chercher
    le nom manquant dans une liste faite à la main serait respecter la lettre
    en trahissant l'intention."""
    appels: list[str] = []
    monkeypatch.setattr(robots.httpx, "AsyncClient",
                        _serveur({"mediapart.fr": (200, MEDIAPART_REEL)}, appels))
    assert await robots.peut_telecharger("https://www.mediapart.fr/journal/a") is False


async def test_les_commentaires_n_influencent_pas_la_lecture(monkeypatch):
    appels: list[str] = []
    avec_commentaires = "# tout est permis ici\nUser-agent: *\nDisallow: /prive/ # note\n"
    monkeypatch.setattr(robots.httpx, "AsyncClient",
                        _serveur({"exemple.fr": (200, avec_commentaires)}, appels))
    assert await robots.peut_telecharger("https://exemple.fr/public/a") is True
    assert await robots.peut_telecharger("https://exemple.fr/prive/a") is False
