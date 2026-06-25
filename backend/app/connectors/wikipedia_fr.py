"""Connecteur Wikinews FR — actualités vérifiées encyclopédiques.

Source : Wikinews en français (https://fr.wikinews.org), projet Wikimedia
dédié aux actualités. Les articles sont vérifiés par la communauté.
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
        "url": "https://fr.wikinews.org/w/index.php?title=Special:NewPages&feed=rss&namespace=0&limit=50",
        "name": "Wikinews FR",
    },
]

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "meteo": ["météo", "tempête", "cyclone", "ouragan", "canicule", "neige", "verglas"],
    "crue": ["inondation", "crue", "submersion", "tsunami"],
    "seisme": ["séisme", "tremblement de terre", "magnitude", "éruption"],
    "energie": ["énergie", "électricité", "nucléaire", "pétrole", "gaz"],
    "sante": ["santé", "épidémie", "pandémie", "vaccin", "hôpital", "maladie"],
    "transport": ["accident", "crash", "naufrage", "collision", "ferroviaire", "aérien"],
    "ordre_public": ["attentat", "terrorisme", "fusillade", "manifestation", "émeute", "arrestation"],
    "incendie": ["incendie", "feu", "flammes", "brûlé"],
    "nucleaire": ["nucléaire", "radioactif", "centrale"],
    "pollution": ["pollution", "marée noire", "déversement"],
    "cyber": ["cyberattaque", "piratage", "hack", "données"],
}

_GRAVITY_TERMS = {
    3: ["mort", "décès", "victimes", "tué", "catastrophe", "attentat"],
    2: ["blessé", "évacuation", "alerte", "grave", "urgent"],
    1: ["incident", "perturbation", "accident", "manifestation"],
}


def _guess_category(title: str, summary: str) -> str:
    text = (title + " " + summary).lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return cat
    return "actualite"


def _guess_gravity(title: str, summary: str) -> int:
    text = (title + " " + summary).lower()
    for g, terms in sorted(_GRAVITY_TERMS.items(), reverse=True):
        if any(t in text for t in terms):
            return g
    return 0


class WikipediaFRConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "wikipedia_fr"

    async def fetch(self) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - _MAX_AGE
        results: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": "FAIREInfo/1.0 (aggregateur-info.fr)"},
        ) as client:
            for feed_cfg in _FEEDS:
                try:
                    resp = await client.get(feed_cfg["url"])
                    if resp.status_code != 200:
                        continue
                    parsed = feedparser.parse(resp.text)
                    for entry in parsed.entries:
                        title = getattr(entry, "title", "").strip()
                        link = getattr(entry, "link", "")
                        summary = getattr(entry, "summary", "").strip()
                        published_parsed = getattr(entry, "published_parsed", None)

                        if not title or not link:
                            continue

                        if published_parsed:
                            pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                        else:
                            pub_dt = datetime.now(timezone.utc)

                        if pub_dt < cutoff:
                            continue

                        # Filter out non-France articles (best effort)
                        text_lower = (title + " " + summary).lower()
                        fr_signals = ["france", "français", "paris", "bretagne", "lyon", "marseille",
                                      "bordeaux", "lille", "toulouse", "nice", "nantes", "strasbourg"]
                        if not any(s in text_lower for s in fr_signals):
                            continue

                        results.append({
                            "source": "wikipedia_fr",
                            "source_url": link,
                            "titre": title[:300],
                            "auteur": "Wikinews FR",
                            "date_publication": pub_dt.isoformat(),
                            "categorie": _guess_category(title, summary),
                            "gravite": _guess_gravity(title, summary),
                            "lieu_niveau": "national",
                            "score_confiance": 0.75,
                        })
                except Exception as exc:
                    logger.warning("WikipediaFR feed error: %s", exc)

        logger.info("WikipediaFR: %d items", len(results))
        return results
