"""IRSN — Institut de radioprotection et de sûreté nucléaire.

Sources : flux RSS des actualités et événements significatifs de l'IRSN,
et flux de l'ASN (Autorité de sûreté nucléaire).
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import feedparser
import httpx

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_FEEDS = [
    {"url": "https://www.irsn.fr/fr/actualites-agenda/actualites/pages/rss.aspx", "name": "IRSN Actualités"},
    {"url": "https://www.irsn.fr/FR/Larecherche/actualites-agenda/Actualites/Pages/RSS.aspx", "name": "IRSN Recherche"},
    {"url": "https://www.asn.fr/rss/actualites.xml",  "name": "ASN Actualités"},
    {"url": "https://www.asn.fr/rss/incidents.xml",   "name": "ASN Incidents"},
    {"url": "https://www.asn.fr/rss/avis.xml",        "name": "ASN Avis"},
]

_MAX_AGE = timedelta(hours=72)
_FETCH_SEM = asyncio.Semaphore(4)

_GRAVITY_HIGH = ("incident", "accident", "fuite", "contamination", "alerte", "urgence", "niveau 2", "niveau 3")
_GRAVITY_MED = ("événement significatif", "contrôle", "déclaration", "anomalie", "écart")


def _gravite(title: str, summary: str) -> int:
    text = (title + " " + summary).lower()
    if any(k in text for k in _GRAVITY_HIGH):
        return 2
    if any(k in text for k in _GRAVITY_MED):
        return 1
    return 0


class IRSNConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "irsn"

    async def fetch(self) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - _MAX_AGE
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            tasks = [self._fetch_feed(client, f, cutoff) for f in _FEEDS]
            feeds_results = await asyncio.gather(*tasks, return_exceptions=True)

        seen_urls: set[str] = set()
        for res in feeds_results:
            if isinstance(res, Exception):
                logger.warning("IRSN/ASN feed error: %s", res)
                continue
            for item in res:
                url = item.get("source_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append(item)

        logger.info("irsn: fetched %d items", len(results))
        return results

    async def _fetch_feed(
        self, client: httpx.AsyncClient, feed_cfg: dict, cutoff: datetime
    ) -> list[dict[str, Any]]:
        async with _FETCH_SEM:
            try:
                resp = await client.get(feed_cfg["url"])
                resp.raise_for_status()
                content = resp.content
            except Exception as exc:
                raise RuntimeError(f"{feed_cfg['name']}: {exc}") from exc

        loop = asyncio.get_running_loop()
        parsed = await loop.run_in_executor(None, feedparser.parse, content)

        items: list[dict[str, Any]] = []
        for entry in parsed.entries:
            try:
                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "") or ""
                if not title or not link:
                    continue

                summary = getattr(entry, "summary", "") or ""

                pub = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
                date_pub = datetime(*pub[:6], tzinfo=timezone.utc) if pub else datetime.now(timezone.utc)

                if date_pub < cutoff:
                    continue

                # Extraire le lieu de l'incident si mentionné (ex: "centrale de Flamanville")
                lieu_nom = "national"
                for centrale in ("flamanville", "bugey", "gravelines", "paluel", "chinon",
                                  "blayais", "golfech", "cruas", "tricastin", "fessenheim",
                                  "cattenom", "belleville", "civaux", "nogent", "penly"):
                    if centrale in (title + " " + summary).lower():
                        lieu_nom = centrale.capitalize()
                        break

                items.append({
                    "source": "irsn",
                    "source_url": link,
                    "titre": title,
                    "auteur": feed_cfg["name"],
                    "date_publication": date_pub.isoformat(),
                    "categorie": "nucleaire",
                    "gravite": _gravite(title, summary),
                    "lieu_nom": lieu_nom,
                    "lieu_niveau": "commune" if lieu_nom != "national" else "national",
                    "description": summary[:500],
                    "skip_extraction": False,
                })
            except Exception:
                continue

        return items
