import asyncio
import feedparser
import httpx
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.connectors.base import BaseConnector

# Flux RSS accessibles depuis un environnement serveur.
# Les PQR (Ouest-France, La Dépêche…) bloquent les IPs de datacenter via 403.
RSS_FEEDS: list[dict[str, Any]] = [
    {
        "name": "France 24",
        "url": "https://www.france24.com/fr/rss",
        "region": None,
    },
    {
        "name": "Euronews France",
        "url": "https://fr.euronews.com/rss",
        "region": None,
    },
    {
        "name": "CNews",
        "url": "https://www.cnews.fr/rss.xml",
        "region": None,
    },
    {
        "name": "Google News France",
        "url": "https://news.google.com/rss/search?q=france+actualité&hl=fr&gl=FR&ceid=FR:fr",
        "region": None,
    },
    {
        "name": "Google News Régions",
        "url": "https://news.google.com/rss/search?q=région+commune+france&hl=fr&gl=FR&ceid=FR:fr",
        "region": None,
    },
]

UA = "Mozilla/5.0 (compatible; FaireInfo/1.0; aggregator)"


def _parse_rss_date(entry: Any) -> datetime:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return datetime.now(timezone.utc)


async def _fetch_feed(client: httpx.AsyncClient, feed_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    feed_name: str = feed_cfg["name"]
    feed_url: str = feed_cfg["url"]
    region: str | None = feed_cfg.get("region")

    try:
        resp = await client.get(feed_url, timeout=15.0)
        resp.raise_for_status()
        content = resp.content
    except Exception as exc:
        raise RuntimeError(f"{feed_name}: fetch failed: {exc}") from exc

    loop = asyncio.get_event_loop()
    parsed = await loop.run_in_executor(None, feedparser.parse, content)

    results: list[dict[str, Any]] = []
    for entry in parsed.entries:
        try:
            title: str = getattr(entry, "title", "").strip()
            if not title:
                continue
            link: str = getattr(entry, "link", "") or ""
            if not link:
                continue

            summary = ""
            for attr in ("summary", "description"):
                val = getattr(entry, attr, None)
                if isinstance(val, list) and val:
                    val = val[0].get("value", "")
                if val and isinstance(val, str):
                    summary = val.strip()[:500]
                    break

            date_pub = _parse_rss_date(entry)

            results.append(
                {
                    "source": "presse_rss",
                    "source_url": link,
                    "titre": title,
                    "auteur": feed_name,
                    "date_publication": date_pub.isoformat(),
                    "date_evenement": None,
                    "categorie": "actualite",
                    "gravite": 0,
                    "lieu_nom": region,
                    "lieu_code_insee": None,
                    "lieu_niveau": "region" if region else "national",
                    "description": summary,
                }
            )
        except Exception:
            continue

    return results


class PresseRSSConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "presse_rss"

    async def fetch(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True) as client:
            tasks = [_fetch_feed(client, cfg) for cfg in RSS_FEEDS]
            feed_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[dict[str, Any]] = []
        for i, res in enumerate(feed_results):
            if isinstance(res, Exception):
                self._logger.warning("Feed %s failed: %s", RSS_FEEDS[i]["name"], res)
            else:
                results.extend(res)

        return results
