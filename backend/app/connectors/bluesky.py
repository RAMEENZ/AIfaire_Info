"""Connecteur BlueSky (AT Protocol) — signaux d'alerte francophones.

Interroge l'API publique de recherche BlueSky sans authentification pour
détecter les signaux précoces d'incidents (incendies, crues, alertes, etc.)
publiés par des comptes francophones.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_MAX_AGE = timedelta(hours=24)
_BASE_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
_TIMEOUT = 15.0

_SEARCH_QUERIES: list[tuple[str, str]] = [
    ("france alerte urgence sécurité", "ordre_public"),
    ("france incendie feux départ feu", "incendie"),
    ("france inondation crue montée eaux", "crue"),
    ("france séisme tremblement secousse", "seisme"),
    ("france météo vigilance tempête", "meteo"),
    ("france grève perturbation sncf train", "transport"),
    ("france cyberattaque piratage hack", "cyber"),
    ("france pollution qualité air", "pollution"),
    ("france nucléaire centrale asnr", "nucleaire"),
    ("france épidémie santé alerte sanitaire", "sante"),
]

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "meteo": ["vigilance", "météo", "tempête", "orage", "neige", "canicule", "cyclone", "vent"],
    "crue": ["crue", "inondation", "flood", "montée des eaux", "débordement"],
    "seisme": ["séisme", "tremblement", "magnitude", "secousse sismique"],
    "energie": ["électricité", "panne électrique", "réseau enedis", "coupure"],
    "sante": ["épidémie", "alerte sanitaire", "maladie", "cas confirmés"],
    "transport": ["grève sncf", "perturbation trains", "route barrée", "autoroute fermée"],
    "ordre_public": ["manifestation violente", "attentat", "alerte enlèvement", "police urgence"],
    "incendie": ["incendie", "feux de forêt", "pompiers", "départ feu", "flammes"],
    "nucleaire": ["nucléaire", "centrale", "irsn", "asnr", "radioactif"],
    "pollution": ["pollution", "qualité de l'air", "pic de pollution", "nappe"],
    "cyber": ["cyberattaque", "hack", "piratage", "rançongiciel", "fuite données"],
}

_GRAVITY_HIGH = ["mort", "décès", "catastrophe", "explosion", "effondrement", "blessés graves"]
_GRAVITY_MED  = ["alerte", "vigilance rouge", "danger immédiat", "grave", "évacuation"]
_GRAVITY_LOW  = ["vigilance", "attention", "risque", "incident", "perturbation"]


def _guess_category(text: str, default: str) -> str:
    lower = text.lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return cat
    return default


def _guess_gravity(text: str) -> int:
    lower = text.lower()
    if any(kw in lower for kw in _GRAVITY_HIGH):
        return 3
    if any(kw in lower for kw in _GRAVITY_MED):
        return 2
    if any(kw in lower for kw in _GRAVITY_LOW):
        return 1
    return 0


class BlueSkyConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "bluesky"

    async def fetch(self) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - _MAX_AGE
        seen_uris: set[str] = set()
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "FAIREInfo/1.0 (aggregateur-info.fr)"},
        ) as client:
            tasks = [
                self._fetch_query(client, query, default_cat, cutoff, seen_uris)
                for query, default_cat in _SEARCH_QUERIES
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in batch_results:
                if isinstance(r, list):
                    results.extend(r)

        logger.info("BlueSky: %d items collected", len(results))
        return results

    async def _fetch_query(
        self,
        client: httpx.AsyncClient,
        query: str,
        default_cat: str,
        cutoff: datetime,
        seen_uris: set[str],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            resp = await client.get(
                _BASE_URL,
                params={"q": query, "lang": "fr", "limit": 25, "sort": "latest"},
            )
            if resp.status_code != 200:
                return items
            posts = resp.json().get("posts", [])
        except Exception as exc:
            logger.debug("BlueSky query %r failed: %s", query, exc)
            return items

        for post in posts:
            uri = post.get("uri", "")
            if not uri or uri in seen_uris:
                continue
            seen_uris.add(uri)

            record = post.get("record", {})
            text = record.get("text", "").strip()
            if not text or len(text) < 30:
                continue

            created_raw = record.get("createdAt") or post.get("indexedAt", "")
            try:
                created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            if created_at < cutoff:
                continue

            author = post.get("author", {})
            handle = author.get("handle", "")
            display_name = author.get("displayName") or handle

            parts = uri.split("/")
            tid = parts[-1] if parts else ""
            source_url = f"https://bsky.app/profile/{handle}/post/{tid}"

            items.append({
                "source": "bluesky",
                "source_url": source_url,
                "titre": text[:250],
                "auteur": display_name,
                "date_publication": created_at.isoformat(),
                "categorie": _guess_category(text, default_cat),
                "gravite": _guess_gravity(text),
                "lieu_niveau": "national",
                "score_confiance": 0.4,
            })

        return items
