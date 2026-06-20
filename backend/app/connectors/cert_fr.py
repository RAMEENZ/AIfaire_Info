"""CERT-FR / ANSSI — alertes cybersécurité.

Source : flux RSS public du CERT-FR (Computer Emergency Response Team France),
opéré par l'ANSSI (Agence nationale de la sécurité des systèmes d'information).
URL officielle : https://www.cert.ssi.gouv.fr/feed/
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
    {"url": "https://www.cert.ssi.gouv.fr/feed/",            "name": "CERT-FR"},
    {"url": "https://www.cert.ssi.gouv.fr/avis/feed/",       "name": "CERT-FR Avis"},
    {"url": "https://www.cert.ssi.gouv.fr/alerte/feed/",     "name": "CERT-FR Alertes"},
    {"url": "https://www.cert.ssi.gouv.fr/actualite/feed/",  "name": "CERT-FR Actualités"},
]

_MAX_AGE = timedelta(hours=72)
_FETCH_SEM = asyncio.Semaphore(4)


def _gravite(title: str, summary: str) -> int:
    text = (title + " " + summary).lower()
    if any(k in text for k in ("critique", "urgence", "exploitation active", "0-day")):
        return 3
    if any(k in text for k in ("élevé", "important", "alerte", "vulnérabilité critique")):
        return 2
    if any(k in text for k in ("moyen", "avis", "mise à jour", "patch")):
        return 1
    return 0


class CertFrConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "cert_fr"

    async def fetch(self) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - _MAX_AGE
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            tasks = [self._fetch_feed(client, f, cutoff) for f in _FEEDS]
            feeds_results = await asyncio.gather(*tasks, return_exceptions=True)

        seen_urls: set[str] = set()
        for res in feeds_results:
            if isinstance(res, Exception):
                logger.warning("CERT-FR feed error: %s", res)
                continue
            for item in res:
                url = item.get("source_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append(item)

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

                summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""

                pub = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
                if pub:
                    date_pub = datetime(*pub[:6], tzinfo=timezone.utc)
                else:
                    date_pub = datetime.now(timezone.utc)

                if date_pub < cutoff:
                    continue

                items.append({
                    "source": "cert_fr",
                    "source_url": link,
                    "titre": title,
                    "auteur": feed_cfg["name"],
                    "date_publication": date_pub.isoformat(),
                    "categorie": "cyber",
                    "gravite": _gravite(title, summary),
                    "lieu_nom": "national",
                    "lieu_niveau": "national",
                    "description": summary[:500],
                    "skip_extraction": True,
                })
            except Exception:
                continue

        return items
