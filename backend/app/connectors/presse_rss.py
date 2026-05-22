import asyncio
import feedparser
import httpx
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.connectors.base import BaseConnector

# Flux RSS accessibles depuis un serveur.
# Les PQR peuvent bloquer les IPs de datacenter (403) mais fonctionnent
# généralement depuis une VM domestique ou un VPS résidentiel.
RSS_FEEDS: list[dict[str, Any]] = [
    # ── ACTUALITÉS NATIONALES — GÉNÉRALISTES ─────────────────────────────────
    {"name": "France Info",         "url": "https://www.francetvinfo.fr/titres.rss",               "region": None},
    {"name": "France 24",           "url": "https://www.france24.com/fr/rss",                       "region": None},
    {"name": "France Inter",        "url": "https://www.radiofrance.fr/franceinter/rss",             "region": None},
    {"name": "RFI",                 "url": "https://www.rfi.fr/fr/rss",                              "region": None},
    {"name": "Euronews France",     "url": "https://fr.euronews.com/rss",                            "region": None},
    {"name": "CNews",               "url": "https://www.cnews.fr/rss.xml",                           "region": None},
    {"name": "20 Minutes",          "url": "https://www.20minutes.fr/rss/actu-france.xml",           "region": None},
    {"name": "Le Monde",            "url": "https://www.lemonde.fr/rss/une.xml",                     "region": None},
    {"name": "Le Figaro",           "url": "https://plus.lefigaro.fr/page/flux-rss",                 "region": None},
    {"name": "Libération",          "url": "https://www.liberation.fr/arc/outboundfeeds/rss-all/",  "region": None},
    {"name": "L'Humanité",          "url": "https://www.humanite.fr/rss/toute-l-actualite",          "region": None},
    {"name": "La Croix",            "url": "https://www.la-croix.com/RSS/",                          "region": None},
    {"name": "Vie Publique",        "url": "https://www.vie-publique.fr/rss/tous",                   "region": None},
    {"name": "Google News France",  "url": "https://news.google.com/rss/search?q=france+actualit%C3%A9&hl=fr&gl=FR&ceid=FR:fr",         "region": None},
    {"name": "Google News Régions", "url": "https://news.google.com/rss/search?q=r%C3%A9gion+commune+france&hl=fr&gl=FR&ceid=FR:fr",    "region": None},

    # ── ACTUALITÉS ÉCONOMIQUES ET TECH ───────────────────────────────────────
    {"name": "La Tribune",          "url": "https://www.latribune.fr/flux-rss.html",                "region": None},
    {"name": "Les Échos",           "url": "https://www.lesechos.fr/rss",                           "region": None},
    {"name": "Boursorama",          "url": "https://www.boursorama.com/rss/actualites/",             "region": None},
    {"name": "Le Journal du Net",   "url": "https://www.journaldunet.com/rss/",                     "region": None},
    {"name": "L'Usine Nouvelle",    "url": "https://www.usinenouvelle.com/rss/",                    "region": None},

    # ── ACTUALITÉS RÉGIONALES — RÉSEAU ACTU.FR ──────────────────────────────
    {"name": "Actu Bretagne",           "url": "https://actu.fr/bretagne/rss.xml",         "region": "Bretagne"},
    {"name": "Actu Normandie",          "url": "https://actu.fr/normandie/rss.xml",        "region": "Normandie"},
    {"name": "Actu Île-de-France",      "url": "https://actu.fr/ile-de-france/rss.xml",    "region": "Île-de-France"},
    {"name": "Actu Occitanie",          "url": "https://actu.fr/occitanie/rss.xml",        "region": "Occitanie"},
    {"name": "Actu Pays de la Loire",   "url": "https://actu.fr/pays-de-la-loire/rss.xml", "region": "Pays de la Loire"},
    {"name": "Actu Hauts-de-France",    "url": "https://actu.fr/hauts-de-france/rss.xml", "region": "Hauts-de-France"},

    # ── GRANDS QUOTIDIENS RÉGIONAUX (PQR) ────────────────────────────────────
    {"name": "Ouest-France",                  "url": "https://www.ouest-france.fr/rss/une",                "region": None},
    {"name": "Sud Ouest",                     "url": "https://www.sudouest.fr/rss/toute-l-actualite",      "region": "Nouvelle-Aquitaine"},
    {"name": "La Voix du Nord",               "url": "https://www.lavoixdunord.fr/rss/toute-l-actualite",  "region": "Hauts-de-France"},
    {"name": "La Provence",                   "url": "https://www.laprovence.com/rss",                     "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin",                    "url": "https://www.nicematin.com/rss",                      "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "La Dépêche du Midi",            "url": "https://www.ladepeche.fr/rss.xml",                   "region": "Occitanie"},
    {"name": "Dernières Nouvelles d'Alsace",  "url": "https://www.dna.fr/rss",                             "region": "Grand Est"},
    {"name": "Le Progrès",                    "url": "https://www.leprogres.fr/rss",                       "region": "Auvergne-Rhône-Alpes"},
    {"name": "La Montagne",                   "url": "https://www.lamontagne.fr/rss",                      "region": "Auvergne-Rhône-Alpes"},
    {"name": "La Nouvelle République",        "url": "https://www.lanouvellerepublique.fr/rss",             "region": "Centre-Val de Loire"},
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
