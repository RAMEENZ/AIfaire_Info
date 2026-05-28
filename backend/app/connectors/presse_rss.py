import asyncio
import html as _html
import re as _re
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

    # ── ACTUALITÉS NATIONALES — AUDIOVISUEL ──────────────────────────────────
    {"name": "BFM TV",              "url": "https://www.bfmtv.com/rss/news-24-7/",                  "region": None},
    {"name": "RTL Info",            "url": "https://www.rtl.fr/feeds/rss/",                         "region": None},
    {"name": "France Bleu",         "url": "https://www.francebleu.fr/rss/l-actu-de-la-matinale",   "region": None},

    # ── ACTUALITÉS ÉCONOMIQUES ET TECH ───────────────────────────────────────
    {"name": "La Tribune",          "url": "https://www.latribune.fr/flux-rss.html",                "region": None},
    {"name": "Les Échos",           "url": "https://www.lesechos.fr/rss",                           "region": None},
    {"name": "Boursorama",          "url": "https://www.boursorama.com/rss/actualites/",             "region": None},
    {"name": "Le Journal du Net",   "url": "https://www.journaldunet.com/rss/",                     "region": None},
    {"name": "L'Usine Nouvelle",    "url": "https://www.usinenouvelle.com/rss/",                    "region": None},

    # ── SOURCES GOUVERNEMENTALES ET OFFICIELLES ───────────────────────────────
    {"name": "Gouvernement.fr",       "url": "https://www.gouvernement.fr/rss",                     "region": None},
    {"name": "Service-Public.fr",     "url": "https://www.service-public.fr/rss/actualites.rss",    "region": None},
    {"name": "Santé Publique France", "url": "https://www.santepubliquefrance.fr/rss.xml",           "region": None},

    # ── ACTUALITÉS RÉGIONALES — RÉSEAU ACTU.FR ──────────────────────────────
    {"name": "Actu Bretagne",                "url": "https://actu.fr/bretagne/rss.xml",                      "region": "Bretagne"},
    {"name": "Actu Normandie",               "url": "https://actu.fr/normandie/rss.xml",                     "region": "Normandie"},
    {"name": "Actu Île-de-France",           "url": "https://actu.fr/ile-de-france/rss.xml",                 "region": "Île-de-France"},
    {"name": "Actu Occitanie",               "url": "https://actu.fr/occitanie/rss.xml",                     "region": "Occitanie"},
    {"name": "Actu Pays de la Loire",        "url": "https://actu.fr/pays-de-la-loire/rss.xml",              "region": "Pays de la Loire"},
    {"name": "Actu Hauts-de-France",         "url": "https://actu.fr/hauts-de-france/rss.xml",               "region": "Hauts-de-France"},
    {"name": "Actu Auvergne-Rhône-Alpes",    "url": "https://actu.fr/auvergne-rhone-alpes/rss.xml",          "region": "Auvergne-Rhône-Alpes"},
    {"name": "Actu Grand Est",               "url": "https://actu.fr/grand-est/rss.xml",                     "region": "Grand Est"},
    {"name": "Actu Nouvelle-Aquitaine",      "url": "https://actu.fr/nouvelle-aquitaine/rss.xml",            "region": "Nouvelle-Aquitaine"},
    {"name": "Actu Centre-Val de Loire",     "url": "https://actu.fr/centre-val-de-loire/rss.xml",           "region": "Centre-Val de Loire"},
    {"name": "Actu Bourgogne-Franche-Comté", "url": "https://actu.fr/bourgogne-franche-comte/rss.xml",       "region": "Bourgogne-Franche-Comté"},
    {"name": "Actu PACA",                    "url": "https://actu.fr/provence-alpes-cote-d-azur/rss.xml",    "region": "Provence-Alpes-Côte d'Azur"},

    # ── DOM-TOM — LA 1ÈRE (France Télévisions) ───────────────────────────────
    {"name": "La 1ère Guadeloupe",        "url": "https://la1ere.francetvinfo.fr/guadeloupe/rss",               "region": "Guadeloupe"},
    {"name": "La 1ère Martinique",        "url": "https://la1ere.francetvinfo.fr/martinique/rss",               "region": "Martinique"},
    {"name": "La 1ère Guyane",            "url": "https://la1ere.francetvinfo.fr/guyane/rss",                   "region": "Guyane"},
    {"name": "La 1ère Réunion",           "url": "https://la1ere.francetvinfo.fr/reunion/rss",                  "region": "La Réunion"},
    {"name": "La 1ère Mayotte",           "url": "https://la1ere.francetvinfo.fr/mayotte/rss",                  "region": "Mayotte"},
    {"name": "La 1ère Nouvelle-Calédonie","url": "https://la1ere.francetvinfo.fr/nouvellecaledonie/rss",        "region": "Nouvelle-Calédonie"},
    {"name": "La 1ère Polynésie",         "url": "https://la1ere.francetvinfo.fr/polynesie/rss",                "region": "Polynésie française"},
    {"name": "La 1ère St-Pierre",         "url": "https://la1ere.francetvinfo.fr/saint-pierre-et-miquelon/rss", "region": "Saint-Pierre-et-Miquelon"},
    {"name": "La 1ère Wallis-Futuna",     "url": "https://la1ere.francetvinfo.fr/wallis-et-futuna/rss",         "region": "Wallis-et-Futuna"},
    {"name": "La 1ère St-Martin",         "url": "https://la1ere.francetvinfo.fr/saint-martin/rss",             "region": "Saint-Martin"},

    # ── GRANDS QUOTIDIENS RÉGIONAUX (PQR) ────────────────────────────────────
    {"name": "Ouest-France",                  "url": "https://www.ouest-france.fr/rss/une",                "region": None},
    {"name": "Le Parisien",                   "url": "https://www.leparisien.fr/rss.xml",                  "region": "Île-de-France"},
    {"name": "Sud Ouest",                     "url": "https://www.sudouest.fr/rss/toute-l-actualite",      "region": "Nouvelle-Aquitaine"},
    {"name": "La Voix du Nord",               "url": "https://www.lavoixdunord.fr/rss/toute-l-actualite",  "region": "Hauts-de-France"},
    {"name": "La Provence",                   "url": "https://www.laprovence.com/rss",                     "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin",                    "url": "https://www.nicematin.com/rss",                      "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "La Dépêche du Midi",            "url": "https://www.ladepeche.fr/rss.xml",                   "region": "Occitanie"},
    {"name": "Midi Libre",                    "url": "https://www.midilibre.fr/rss/",                      "region": "Occitanie"},
    {"name": "L'Indépendant",                 "url": "https://www.lindependant.fr/rss",                    "region": "Occitanie"},
    {"name": "Dernières Nouvelles d'Alsace",  "url": "https://www.dna.fr/rss",                             "region": "Grand Est"},
    {"name": "L'Alsace",                      "url": "https://www.lalsace.fr/rss",                         "region": "Grand Est"},
    {"name": "L'Est Républicain",             "url": "https://www.estrepublicain.fr/rss",                  "region": "Grand Est"},
    {"name": "Républicain Lorrain",           "url": "https://www.republicain-lorrain.fr/rss",             "region": "Grand Est"},
    {"name": "Courrier Picard",               "url": "https://www.courrier-picard.fr/rss",                 "region": "Hauts-de-France"},
    {"name": "Le Progrès",                    "url": "https://www.leprogres.fr/rss",                       "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Dauphiné Libéré",            "url": "https://www.ledauphine.com/rss",                     "region": "Auvergne-Rhône-Alpes"},
    {"name": "La Montagne",                   "url": "https://www.lamontagne.fr/rss",                      "region": "Auvergne-Rhône-Alpes"},
    {"name": "La Nouvelle République",        "url": "https://www.lanouvellerepublique.fr/rss",             "region": "Centre-Val de Loire"},
    {"name": "Paris Normandie",               "url": "https://www.paris-normandie.fr/rss",                 "region": "Normandie"},
    {"name": "Presse Océan",                  "url": "https://www.presseocean.fr/rss",                     "region": "Pays de la Loire"},
]

UA = "Mozilla/5.0 (compatible; FaireInfo/1.0; aggregator)"


def _strip_html(text: str) -> str:
    """Supprime les balises HTML et décode les entités d'une chaîne RSS."""
    text = _re.sub(r'<[^>]+>', ' ', text)
    text = _html.unescape(text)
    return ' '.join(text.split())


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
                    summary = _strip_html(val)[:500]
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
