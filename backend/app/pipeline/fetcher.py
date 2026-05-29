"""Fetch and extract full article text from source URLs.

Uses trafilatura to strip boilerplate (nav, ads, footer) and keep only
the main content.  The in-memory cache avoids re-fetching the same URL
within a single ingestion run.
"""
import asyncio
import logging

import httpx
import trafilatura

logger = logging.getLogger(__name__)

_article_cache: dict[str, str] = {}
_MAX_ARTICLE_CACHE = 1024

# Parallel fetches: enough to saturate a typical 100 Mbit link without
# triggering rate-limiting on the target sites.
_FETCH_SEMAPHORE = asyncio.Semaphore(15)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; FaireInfo/1.0; "
        "+https://github.com/RAMEENZ/AIfaire_Info)"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


def _cache_put(url: str, text: str) -> None:
    if len(_article_cache) >= _MAX_ARTICLE_CACHE:
        # Evict oldest half to prevent unbounded growth
        keys = list(_article_cache)
        for k in keys[: len(keys) // 2]:
            del _article_cache[k]
    _article_cache[url] = text


async def fetch_article_text(url: str) -> str | None:
    """Fetch URL and return the main article text (trafilatura extraction).

    Returns None if the request fails, the page is inaccessible, or the
    extracted content is too short to be useful.
    """
    if url in _article_cache:
        return _article_cache[url]

    async with _FETCH_SEMAPHORE:
        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers=_HEADERS,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
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
        _cache_put(url, text.strip())
        return _article_cache[url]

    return None
