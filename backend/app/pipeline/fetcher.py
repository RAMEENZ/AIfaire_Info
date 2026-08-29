"""Fetch and extract full article text from source URLs.

Uses trafilatura to strip boilerplate (nav, ads, footer) and keep only
the main content.  The in-memory cache avoids re-fetching the same URL
within a single ingestion run.
"""
import asyncio
import ipaddress
import logging
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from app.pipeline.robots import peut_telecharger

logger = logging.getLogger(__name__)

_article_cache: dict[str, str] = {}
_MAX_ARTICLE_CACHE = 1024

# Parallel fetches: enough to saturate a typical 100 Mbit link without
# triggering rate-limiting on the target sites.
_FETCH_SEMAPHORE = asyncio.Semaphore(15)

# Nombre maximal de redirections suivies manuellement (chacune revalidée SSRF).
_MAX_REDIRECTS = 5

# Taille maximale du corps téléchargé. Rien ne la bornait : `resp.text` chargeait
# la réponse entière en mémoire, et jusqu'à 15 téléchargements tournent en
# parallèle (_FETCH_SEMAPHORE). Une page anormalement lourde — ou un serveur
# hostile répondant un flux sans fin — suffisait à faire enfler le processus.
# 5 Mio laissent passer très largement le plus copieux des articles de presse :
# le texte utile dépasse rarement 50 Kio, le reste étant du balisage.
_MAX_BODY_BYTES = 5 * 1024 * 1024

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FaireInfo/1.0)",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# Réseaux bloqués pour prévenir les attaques SSRF : RFC-1918, loopback,
# link-local (metadata cloud AWS/GCP/Azure à 169.254.169.254).
_BLOCKED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _ip_is_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Les adresses IPv6 mappées IPv4 (::ffff:169.254.169.254) contournent les
    # blocs IPv4 purs : on les ramène à leur forme IPv4 avant comparaison.
    check = addr.ipv4_mapped if getattr(addr, "ipv4_mapped", None) is not None else addr
    return any(check in net for net in _BLOCKED_NETWORKS)


async def _is_safe_url(url: str) -> bool:
    """Retourne False pour tout schéma non-HTTP(S) ou hôte qui résout vers une
    adresse privée/loopback/link-local.

    Contrairement à une simple vérification de littéral IP, on résout le nom DNS
    et on vérifie TOUTES les adresses retournées : cela bloque les attaques SSRF
    par nom de domaine (ex. un flux RSS pointant vers un hostname qui résout en
    169.254.169.254 — endpoint de métadonnées cloud).
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname or ""
        if not host:
            return False

        # Littéral IP : vérification directe, pas de résolution nécessaire.
        try:
            return not _ip_is_blocked(ipaddress.ip_address(host))
        except ValueError:
            pass

        # Hostname DNS : on résout et on rejette si une seule adresse est bloquée.
        try:
            loop = asyncio.get_running_loop()
            infos = await loop.getaddrinfo(host, parsed.port or 80,
                                           proto=0, type=0)
        except Exception as exc:
            logger.debug("_is_safe_url: DNS resolution failed for %s: %s", host, exc)
            return False
        if not infos:
            return False
        for info in infos:
            sockaddr = info[4]
            try:
                if _ip_is_blocked(ipaddress.ip_address(sockaddr[0])):
                    return False
            except ValueError:
                return False
        return True
    except Exception:
        return False


async def _lire_borne(resp: httpx.Response, url: str) -> str | None:
    """Lit le corps de la réponse, en abandonnant au-delà de _MAX_BODY_BYTES.

    Un `Content-Length` annoncé trop grand suffit à refuser d'emblée ; sinon on
    accumule les morceaux et on s'arrête au dépassement — un serveur peut très
    bien ne pas annoncer de taille, ou en annoncer une fausse.
    """
    annonce = resp.headers.get("content-length")
    if annonce and annonce.isdigit() and int(annonce) > _MAX_BODY_BYTES:
        logger.debug("fetch_article_text: %s annonce %s octets, ignoré", url, annonce)
        return None

    morceaux: list[bytes] = []
    total = 0
    async for morceau in resp.aiter_bytes():
        total += len(morceau)
        if total > _MAX_BODY_BYTES:
            logger.debug("fetch_article_text: %s dépasse %d octets, ignoré", url, _MAX_BODY_BYTES)
            return None
        morceaux.append(morceau)

    brut = b"".join(morceaux)
    # `resp.text` n'est pas disponible sur une réponse streamée non lue en
    # entier : on décode nous-mêmes, avec l'encodage annoncé et un repli
    # tolérant — un octet invalide ne doit pas faire perdre tout l'article.
    return brut.decode(resp.encoding or "utf-8", errors="replace")


def _cache_put(url: str, text: str) -> None:
    if len(_article_cache) >= _MAX_ARTICLE_CACHE:
        keys = list(_article_cache)
        for k in keys[: len(keys) // 2]:
            del _article_cache[k]
    _article_cache[url] = text


async def fetch_article_text(url: str) -> str | None:
    """Fetch URL and return the main article text (trafilatura extraction).

    Returns None if the request fails, the page is inaccessible, or the
    extracted content is too short to be useful.
    """
    if not await _is_safe_url(url):
        logger.debug("fetch_article_text: blocked unsafe URL %s", url)
        return None

    if url in _article_cache:
        return _article_cache[url]

    # L'éditeur a-t-il consenti à ce que le corps de ses articles soit
    # récupéré ? Contrôlé AVANT la requête, et avant le sémaphore : un refus
    # ne doit pas consommer un créneau de téléchargement.
    if not await peut_telecharger(url):
        return None

    async with _FETCH_SEMAPHORE:
        try:
            # follow_redirects=False : on suit les redirections manuellement pour
            # revalider chaque saut. Sinon une 302 vers http://169.254.169.254/
            # contournerait le contrôle SSRF déjà passé sur l'URL initiale.
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=False,
                headers=_HEADERS,
            ) as client:
                current_url = url
                html = None
                for _ in range(_MAX_REDIRECTS + 1):
                    # `stream` plutôt que `get` : le corps n'est lu que par
                    # morceaux, ce qui permet d'abandonner dès le dépassement
                    # au lieu de découvrir la taille une fois tout en mémoire.
                    async with client.stream("GET", current_url) as resp:
                        if resp.is_redirect and resp.has_redirect_location:
                            # urljoin gère les Location relatives (ex. "/article/2").
                            next_url = urljoin(current_url, resp.headers["location"])
                            if not await _is_safe_url(next_url):
                                logger.debug("fetch_article_text: blocked redirect to %s", next_url)
                                return None
                            current_url = next_url
                            continue
                        resp.raise_for_status()
                        html = await _lire_borne(resp, current_url)
                    break
                else:
                    logger.debug("fetch_article_text: too many redirects for %s", url)
                    return None
                if html is None:
                    return None
        except Exception as exc:
            logger.debug("fetch_article_text: GET failed for %s: %s", url, exc)
            return None

    try:
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
            favor_precision=True,
        )
    except Exception as exc:
        logger.debug("fetch_article_text: trafilatura failed for %s: %s", url, exc)
        return None

    if text and len(text.strip()) >= 150:
        cleaned = text.strip()
        _cache_put(url, cleaned)
        return cleaned

    return None
