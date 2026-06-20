"""Qualité de l'air — agrégation nationale via LCSQA et Atmo France.

Sources :
- LCSQA (Laboratoire Central de Surveillance de la Qualité de l'Air) : données nationales
- Flux RSS des associations Atmo régionales
- data.gouv.fr : indices de qualité de l'air
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
    {"url": "https://www.lcsqa.org/fr/rss.xml",                         "name": "LCSQA", "region": None},
    {"url": "https://www.airparif.fr/rss/actualites",                   "name": "Airparif", "region": "Île-de-France"},
    {"url": "https://www.atmo-auvergnerhonealpes.fr/rss.xml",           "name": "Atmo AuRA", "region": "Auvergne-Rhône-Alpes"},
    {"url": "https://www.atmo-occitanie.org/rss.xml",                   "name": "Atmo Occitanie", "region": "Occitanie"},
    {"url": "https://www.atmo-nouvelleaquitaine.org/rss.xml",           "name": "Atmo NA", "region": "Nouvelle-Aquitaine"},
    {"url": "https://www.atmo-paca.fr/rss.xml",                        "name": "AtmoSud", "region": "Provence-Alpes-Côte d'Azur"},
    {"url": "https://www.atmonormandie.fr/rss.xml",                     "name": "Atmo Normandie", "region": "Normandie"},
    {"url": "https://www.atmo-hdf.fr/rss.xml",                         "name": "Atmo HdF", "region": "Hauts-de-France"},
    {"url": "https://www.atmo-grandest.eu/rss.xml",                     "name": "ATMO Grand Est", "region": "Grand Est"},
    {"url": "https://www.air-breizh.asso.fr/rss.xml",                  "name": "Air Breizh", "region": "Bretagne"},
    {"url": "https://www.lig-air.fr/rss.xml",                          "name": "Lig'Air", "region": "Centre-Val de Loire"},
]

_MAX_AGE = timedelta(hours=48)
_FETCH_SEM = asyncio.Semaphore(5)

_ALERT_KEYWORDS = (
    "dépassement", "alerte", "pic de pollution", "épisode de pollution",
    "indice mauvais", "indice très mauvais", "restriction", "circulation différenciée",
    "vignette crit'air", "interdiction", "qualité dégradée",
)


def _gravite(title: str, summary: str) -> int:
    text = (title + " " + summary).lower()
    if any(k in text for k in ("alerte", "très mauvais", "très mauvaise", "interdiction", "restriction")):
        return 2
    if any(k in text for k in _ALERT_KEYWORDS):
        return 1
    return 0


def _is_alert(title: str, summary: str) -> bool:
    text = (title + " " + summary).lower()
    return any(k in text for k in _ALERT_KEYWORDS + ("qualité de l'air", "indice", "pollution"))


class AirQualityConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "air_quality"

    async def fetch(self) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - _MAX_AGE
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            tasks = [self._fetch_feed(client, f, cutoff) for f in _FEEDS]
            feeds_results = await asyncio.gather(*tasks, return_exceptions=True)

        seen_urls: set[str] = set()
        for res in feeds_results:
            if isinstance(res, Exception):
                logger.debug("Air quality feed error: %s", res)
                continue
            for item in res:
                url = item.get("source_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append(item)

        logger.info("air_quality: fetched %d items", len(results))
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

                if not _is_alert(title, summary):
                    continue

                pub = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
                date_pub = datetime(*pub[:6], tzinfo=timezone.utc) if pub else datetime.now(timezone.utc)

                if date_pub < cutoff:
                    continue

                region = feed_cfg.get("region")
                items.append({
                    "source": "air_quality",
                    "source_url": link,
                    "titre": title,
                    "auteur": feed_cfg["name"],
                    "date_publication": date_pub.isoformat(),
                    "categorie": "pollution",
                    "gravite": _gravite(title, summary),
                    "lieu_nom": region or "national",
                    "lieu_niveau": "region" if region else "national",
                    "description": summary[:500],
                    "skip_extraction": True,
                })
            except Exception:
                continue

        return items
