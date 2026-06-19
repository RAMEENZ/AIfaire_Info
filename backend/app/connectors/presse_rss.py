import asyncio
import html as _html
import re as _re
import unicodedata
import feedparser
import httpx
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.config import settings
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
    {"name": "Ministère Intérieur",   "url": "https://www.interieur.gouv.fr/rss.xml",               "region": None},
    {"name": "Sénat",                 "url": "https://www.senat.fr/rss/depots-projets-lois.rss",    "region": None},
    {"name": "ANSM",                  "url": "https://ansm.sante.fr/rss/actualites.xml",             "region": None},

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
    {"name": "Actu Corse",                   "url": "https://actu.fr/corse/rss.xml",                          "region": "Corse"},

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
# Articles older than this are skipped — matches presse_rss TTL in purge.py
_MAX_ARTICLE_AGE = timedelta(hours=72)

# Limit simultaneous HTTP requests to avoid overwhelming news sites or the local connection pool
_FETCH_SEMAPHORE = asyncio.Semaphore(20)

# Plafond d'articles conservés par flux (les plus récents). Évite qu'un flux
# volumineux (Google News renvoie ~100 entrées) ne monopolise à lui seul le
# budget de traitement IA au détriment de la diversité des sources.
_MAX_PER_FEED = 25


def _strip_html(text: str) -> str:
    """Supprime les balises HTML et décode les entités d'une chaîne RSS."""
    text = _re.sub(r'<[^>]+>', ' ', text)
    text = _html.unescape(text)
    return ' '.join(text.split())


# Balises éditoriales en tête de titre, à retirer avant déduplication : un même
# article publié par deux médias peut s'intituler "VIDÉO. X" chez l'un et "X"
# chez l'autre. On les neutralise pour que les variantes se regroupent.
_EDITORIAL_PREFIX_RE = _re.compile(
    r'^(?:'
    r'vid[ée]o|photos?|en\s+images?|en\s+direct|direct|live|replay|reportage|'
    r'interview|portrait|analyse|d[ée]cryptage|t[ée]moignage|exclusif|exclusivit[ée]|'
    r'info\s+\w+|carte|infographie|tribune|[ée]dito|chronique|podcast|enqu[êe]te|'
    r'r[ée]cit|fait\s+divers|insolite|bonne\s+nouvelle'
    r')\s*[:.\-–—]\s*',
    _re.IGNORECASE,
)


def _title_key(title: str) -> str:
    """Clé de normalisation pour déduplication par titre.

    Retire accents, balises éditoriales de tête ("VIDÉO.", "EN IMAGES :") et
    ponctuation, afin que le même sujet repris par plusieurs médias produise
    la même clé et soit dédupliqué.
    """
    t = title.lower().strip()
    # Retire une éventuelle balise éditoriale en tête (potentiellement répétée)
    prev = None
    while prev != t:
        prev = t
        t = _EDITORIAL_PREFIX_RE.sub('', t, count=1).strip()
    # Supprime les accents (é → e) pour fusionner "décès" / "deces"
    t = unicodedata.normalize('NFKD', t)
    t = ''.join(c for c in t if not unicodedata.combining(c))
    # Ne garde que les caractères alphanumériques
    return _re.sub(r'[^a-z0-9]', '', t)[:100]


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

    async with _FETCH_SEMAPHORE:
        try:
            resp = await client.get(feed_url, timeout=15.0)
            resp.raise_for_status()
            content = resp.content
        except Exception as exc:
            raise RuntimeError(f"{feed_name}: fetch failed: {exc}") from exc

    loop = asyncio.get_running_loop()
    parsed = await loop.run_in_executor(None, feedparser.parse, content)

    cutoff = datetime.now(timezone.utc) - _MAX_ARTICLE_AGE
    results: list[dict[str, Any]] = []
    for entry in parsed.entries:
        try:
            title: str = getattr(entry, "title", "").strip()
            if not title:
                continue
            link: str = getattr(entry, "link", "") or ""
            if not link:
                continue

            # Try full content first (richer), fall back to summary/description
            summary = ""
            content_list = getattr(entry, "content", None)
            if isinstance(content_list, list) and content_list:
                summary = _strip_html(content_list[0].get("value", ""))[:800]
            if not summary:
                for attr in ("summary", "description"):
                    val = getattr(entry, attr, None)
                    if isinstance(val, list) and val:
                        val = val[0].get("value", "")
                    if val and isinstance(val, str):
                        summary = _strip_html(val)[:500]
                        break

            date_pub = _parse_rss_date(entry)
            if date_pub < cutoff:
                continue

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

    # Ne garde que les plus récents de ce flux (les chaînes ISO-8601 en UTC se
    # trient lexicographiquement dans l'ordre chronologique).
    results.sort(key=lambda r: r["date_publication"], reverse=True)
    return results[:_MAX_PER_FEED]


class PresseRSSConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "presse_rss"

    async def fetch(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True) as client:
            tasks = [_fetch_feed(client, cfg) for cfg in RSS_FEEDS]
            feed_results = await asyncio.gather(*tasks, return_exceptions=True)

        raw: list[dict[str, Any]] = []
        for i, res in enumerate(feed_results):
            if isinstance(res, Exception):
                self._logger.warning("Feed %s failed: %s", RSS_FEEDS[i]["name"], res)
            else:
                raw.extend(res)

        # Déduplication par titre normalisé : préférer les articles avec une région
        seen: dict[str, dict[str, Any]] = {}
        for item in raw:
            key = _title_key(item.get("titre", ""))
            if not key:
                continue
            if key not in seen:
                seen[key] = item
            elif item.get("lieu_nom") and not seen[key].get("lieu_nom"):
                # Remplace la version nationale par la version régionale
                seen[key] = item

        # Plafond global : on ne traite que les N articles les plus récents
        # (chaque article coûte un appel LLM ~12 s sur CPU). Sans ce plafond, un
        # run de ~1000 articles sature le CPU plus d'une heure avant tout commit.
        items = list(seen.values())
        items.sort(key=lambda it: it.get("date_publication") or "", reverse=True)
        capped = items[: settings.MAX_PRESSE_ARTICLES]
        self._logger.info(
            "presse_rss: %d raw → %d after title dedup → %d after cap (max=%d)",
            len(raw), len(seen), len(capped), settings.MAX_PRESSE_ARTICLES,
        )
        return capped
