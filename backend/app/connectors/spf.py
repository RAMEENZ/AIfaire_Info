"""Connecteur Santé Publique France — alertes sanitaires et épidémiologiques.

Sources :
- Site officiel de Santé Publique France : actualités et alertes
- BEH (Bulletin Épidémiologique Hebdomadaire)
- Signalements et points épidémiologiques
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import httpx

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_MAX_AGE = timedelta(hours=72)

_FEEDS = [
    {
        "url": "https://www.santepubliquefrance.fr/content/download/492196/document_file/",
        "name": "SPF Actualités",
        "fallback_url": "https://www.santepubliquefrance.fr/rss/actualites",
    },
    {
        "url": "https://www.santepubliquefrance.fr/rss/alertes",
        "name": "SPF Alertes",
        "fallback_url": None,
    },
]

_ALERT_KEYWORDS = [
    "épidémie", "alerte", "risque", "contamination", "outbreak",
    "cas groupés", "décès", "hospitalisations", "tension", "pénurie",
    "signalement", "vigilance", "recommandation",
]

_GRAVITE_HIGH = ["urgence sanitaire", "alerte nationale", "pandémie", "épidémie sévère"]
_GRAVITE_MED  = ["alerte", "épidémie", "cas groupés", "surveillance renforcée"]
_GRAVITE_LOW  = ["vigilance", "recommandation", "signalement", "point épidémiologique"]


def _gravite(title: str, summary: str) -> int:
    text = (title + " " + summary).lower()
    if any(k in text for k in _GRAVITE_HIGH):
        return 3
    if any(k in text for k in _GRAVITE_MED):
        return 2
    if any(k in text for k in _GRAVITE_LOW):
        return 1
    return 0


class SPFConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "spf"

    async def fetch(self) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - _MAX_AGE
        results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()

        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={
                "User-Agent": "FAIREInfo/1.0 (aggregateur-info.fr)",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        ) as client:
            urls_to_try = [
                "https://www.santepubliquefrance.fr/rss/actualites",
                "https://www.santepubliquefrance.fr/rss/alertes-sanitaires",
                "https://www.santepubliquefrance.fr/rss/maladies-et-traumatismes",
            ]
            for url in urls_to_try:
                try:
                    resp = await client.get(url)
                    if resp.status_code not in (200, 304):
                        continue
                    parsed = feedparser.parse(resp.text)
                    for entry in parsed.entries:
                        link = getattr(entry, "link", "")
                        title = getattr(entry, "title", "").strip()
                        summary = getattr(entry, "summary", "").strip()
                        if not link or link in seen_urls or not title:
                            continue
                        seen_urls.add(link)

                        published_parsed = getattr(entry, "published_parsed", None)
                        if published_parsed:
                            pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                        else:
                            pub_dt = datetime.now(timezone.utc)

                        if pub_dt < cutoff:
                            continue

                        results.append({
                            "source": "spf",
                            "source_url": link,
                            "titre": title[:300],
                            "auteur": "Santé Publique France",
                            "date_publication": pub_dt.isoformat(),
                            "categorie": "sante",
                            "gravite": _gravite(title, summary),
                            "lieu_niveau": "national",
                            "score_confiance": 0.9,
                        })
                except Exception as exc:
                    logger.debug("SPF feed %s error: %s", url, exc)

        logger.info("SPF: %d items", len(results))
        return results
