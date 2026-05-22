import asyncio
import feedparser
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.connectors.base import BaseConnector

RSS_FEEDS: list[dict[str, Any]] = [
    {"name": "Ouest France", "url": "https://www.ouest-france.fr/rss/france", "region": "Bretagne/Pays-de-la-Loire"},
    {"name": "La Dépêche", "url": "https://www.ladepeche.fr/rss.xml", "region": "Occitanie"},
    {"name": "Sud Ouest", "url": "https://www.sudouest.fr/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Le Progrès", "url": "https://www.leprogres.fr/rss.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "20 Minutes", "url": "https://www.20minutes.fr/feeds/rss/news", "region": None},
]


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


def _parse_feed(feed_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    feed_name: str = feed_cfg["name"]
    feed_url: str = feed_cfg["url"]
    region: str | None = feed_cfg.get("region")

    try:
        parsed = feedparser.parse(feed_url)
    except Exception:
        return []

    results: list[dict[str, Any]] = []

    for entry in parsed.entries:
        try:
            title: str = getattr(entry, "title", "").strip()
            if not title:
                continue

            link: str = getattr(entry, "link", "") or ""
            if not link:
                continue

            summary: str = ""
            for attr in ("summary", "description", "content"):
                val = getattr(entry, attr, None)
                if isinstance(val, list) and val:
                    val = val[0].get("value", "")
                if val and isinstance(val, str):
                    summary = val.strip()
                    break

            if len(summary) > 500:
                summary = summary[:500]

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
                    "feed_name": feed_name,
                    "raw": {
                        "title": title,
                        "link": link,
                        "summary": summary,
                        "feed_name": feed_name,
                        "region": region,
                    },
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
        loop = asyncio.get_event_loop()
        tasks = [
            loop.run_in_executor(None, _parse_feed, feed_cfg)
            for feed_cfg in RSS_FEEDS
        ]
        feed_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[dict[str, Any]] = []
        for i, feed_result in enumerate(feed_results):
            if isinstance(feed_result, Exception):
                self._logger.warning("Feed %s failed: %s", RSS_FEEDS[i]["name"], feed_result)
                continue
            results.extend(feed_result)

        return results
