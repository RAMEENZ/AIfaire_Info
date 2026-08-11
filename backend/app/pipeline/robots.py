"""Respect de robots.txt avant tout téléchargement de texte intégral.

Un flux RSS est publié POUR être repris : titres et chapôs sont faits pour la
syndication. Aspirer le corps de l'article pour le passer à un modèle de
langage est autre chose, et beaucoup d'éditeurs l'ont explicitement refusé.

Mesuré le 11/08/2026 sur les sources de Faire.info : 85 des 180 hôtes (47 %)
refusent, mais surtout 678 des 867 FLUX (78 %) — le refus se concentre sur les
plus gros pourvoyeurs : actu.fr (114 flux), ici.fr (89), France 3 Régions (60),
franceinfo (32), Le Monde (29). Le Télégramme va plus loin : liste blanche
d'une vingtaine de robots, aucune règle générique, et 403 sur ses flux.

Le coût est donc réel : pour ces 78 %, l'extraction retombe sur titre + chapô
RSS. C'est exactement ce qui se produit déjà quand un téléchargement échoue,
donc une dégradation connue — mais elle porte sur la majorité du corpus.
RESPECT_ROBOTS_TXT=false rétablit l'ancien comportement en une ligne.

Chaque URL est confrontée à plusieurs identités : la nôtre, et celles des
robots dont l'unique raison d'être est d'alimenter un modèle de langage. Le
détail et la raison de ce choix sont dans le commentaire de _AGENTS.
"""
import asyncio
import logging
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Agents évalués. Le premier est le nôtre. Les suivants sont les robots dont
# l'unique raison d'être est d'alimenter un modèle de langage.
#
# Pourquoi toute cette liste plutôt que le seul « MistralAI-User », qui traite
# effectivement nos textes : parce que ces fichiers sont écrits à la main, et
# qu'aucun éditeur ne les tient à jour de tous les agents du marché. Mediapart
# refuse ClaudeBot, GPTBot, CCBot et Google-Extended, mais n'a jamais écrit
# MistralAI-User (relevé du 11/08/2026) — ce n'est pas une permission, c'est un
# oubli. Chercher le nom manquant dans une liste faite à la main, ce serait
# respecter la lettre en trahissant l'intention.
#
# Un refus de l'un quelconque vaut donc refus de cet usage.
_AGENTS = (
    "FaireInfo",
    "MistralAI-User", "ClaudeBot", "anthropic-ai", "GPTBot", "OAI-SearchBot",
    "Google-Extended", "Applebot-Extended", "PerplexityBot", "CCBot",
    "cohere-ai", "Meta-ExternalAgent", "Bytespider",
)

_UA_ROBOTS = "Mozilla/5.0 (compatible; FaireInfo/1.0)"

# hôte -> (parseur ou None si tout est permis, instant de péremption).
# None signifie « aucune restriction connue » : robots.txt absent, illisible,
# ou vide. En mémoire comme le cache ETag : un redémarrage le reconstruit.
_cache: dict[str, tuple[RobotFileParser | None, float]] = {}
_verrous: dict[str, asyncio.Lock] = {}

_TTL_SECONDES = 6 * 3600


def _lignes_rfc9309(texte: str) -> list[str]:
    """Retire lignes vides et commentaires avant l'analyse.

    RobotFileParser applique la convention de 1996, où une ligne vide TERMINE
    un groupe. La RFC 9309, norme actuelle, dit l'inverse : un groupe court
    jusqu'à la prochaine ligne « User-agent ».

    L'écart n'est pas théorique. Le Télégramme écrit (relevé du 11/08/2026) :

        User-agent: MistralAI-User
        User-agent: xAI-Grok
                                    ← ligne vide
        Allow: /guide-conso/
        Disallow: /

    Le parseur d'origine referme le groupe sur la ligne vide, avant d'avoir lu
    la moindre règle : l'interdiction s'évapore et l'agent se croit autorisé.
    Autrement dit, la lecture naïve était permissive envers exactement les
    éditeurs qui refusent le plus clairement. Supprimer les lignes vides rend
    au parseur le comportement de la RFC : il ouvre un nouveau groupe à la
    prochaine ligne « User-agent », et pas avant.
    """
    lignes = []
    for brute in texte.splitlines():
        ligne = brute.split("#", 1)[0].strip()
        if ligne:
            lignes.append(ligne)
    return lignes


async def _parseur_pour(hote: str, schema: str) -> RobotFileParser | None:
    maintenant = time.monotonic()
    entree = _cache.get(hote)
    if entree is not None and entree[1] > maintenant:
        return entree[0]

    # Un verrou par hôte : sans lui, les 15 téléchargements concurrents d'un
    # même site demanderaient tous robots.txt en même temps.
    verrou = _verrous.setdefault(hote, asyncio.Lock())
    async with verrou:
        entree = _cache.get(hote)
        if entree is not None and entree[1] > time.monotonic():
            return entree[0]

        parseur: RobotFileParser | None = None
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                r = await client.get(
                    f"{schema}://{hote}/robots.txt",
                    headers={"User-Agent": _UA_ROBOTS},
                )
            if r.status_code == 200 and r.text.strip():
                parseur = RobotFileParser()
                parseur.parse(_lignes_rfc9309(r.text))
            elif 500 <= r.status_code < 600:
                # RFC 9309 : une erreur serveur vaut interdiction complète. On
                # ne profite pas d'une panne pour passer outre.
                parseur = RobotFileParser()
                parseur.parse(["User-agent: *", "Disallow: /"])
            # 4xx (dont 404) : aucune restriction publiée, donc tout est permis.
        except Exception as exc:
            # Réseau indisponible : on n'invente pas une permission, mais on ne
            # bloque pas non plus l'ingestion sur un incident passager. Le
            # téléchargement suivra son cours et échouera de lui-même si le
            # site est injoignable.
            logger.debug("robots.txt illisible pour %s : %s", hote, exc)

        _cache[hote] = (parseur, time.monotonic() + _TTL_SECONDES)
        return parseur


async def peut_telecharger(url: str) -> bool:
    """L'éditeur autorise-t-il la récupération du corps de cette page ?"""
    if not settings.RESPECT_ROBOTS_TXT:
        return True
    decoupe = urlparse(url)
    if not decoupe.hostname or decoupe.scheme not in ("http", "https"):
        return True

    parseur = await _parseur_pour(decoupe.hostname, decoupe.scheme)
    if parseur is None:
        return True

    for agent in _AGENTS:
        if not parseur.can_fetch(agent, url):
            logger.info(
                "robots.txt de %s refuse « %s » : texte intégral non récupéré",
                decoupe.hostname, agent,
            )
            return False
    return True


def vider_cache() -> None:
    """Réservé aux tests."""
    _cache.clear()
    _verrous.clear()
