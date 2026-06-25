import asyncio
import re
import feedparser
import httpx
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.connectors.base import BaseConnector

# France Bleu a été rebaptisé « ici » (ici.fr) ; l'ancien flux
# francebleu.fr/emissions/nuits/rss est mort (404). On garde plusieurs
# candidats : les flux régionaux PACA / Provence couvrent les zones les plus
# touchées par les feux de forêt, complétés par Sud Ouest. Le filtrage par
# mots-clés (_FIRE_KEYWORDS) ne retient ensuite que les sujets incendies.
_RSS_FEEDS = [
    {"name": "ici Provence",     "url": "https://www.ici.fr/provence/rss"},
    {"name": "ici Azur",         "url": "https://www.ici.fr/azur/rss"},
    {"name": "ici (général)",    "url": "https://www.ici.fr/rss"},
    {"name": "France Bleu Provence (legacy)", "url": "https://www.francebleu.fr/rss/provence/rss.xml"},
    {"name": "Sud Ouest",        "url": "https://www.sudouest.fr/rss"},
]

# User-Agent navigateur réaliste (Firefox) : évite les blocages 403 que
# renvoient certains sites de presse aux UA "robots".
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

_FIRE_KEYWORDS = re.compile(
    r"incendie|feu de for[eê]t|d[eé]part de feu|incendie criminel|feux de for[eê]t"
    r"|br[uû]lis|pyromane|sapeur[- ]pompier|pompiers|SDIS|DFCI",
    re.IGNORECASE,
)

_HIGH_GRAVITY_RE = re.compile(r"hectares?|maison|[eé]vacuation", re.IGNORECASE)


def _parse_rss_date(entry: Any) -> str:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()


async def _fetch_feed(
    client: httpx.AsyncClient,
    feed: dict[str, str],
    loop: asyncio.AbstractEventLoop,
) -> list[dict[str, Any]]:
    name = feed["name"]
    url = feed["url"]
    try:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        content = resp.content
    except Exception as exc:
        raise RuntimeError(f"{name}: fetch failed: {exc}") from exc

    parsed = await loop.run_in_executor(None, feedparser.parse, content)

    results: list[dict[str, Any]] = []
    for entry in getattr(parsed, "entries", []):
        try:
            title: str = getattr(entry, "title", "").strip()
            link: str = getattr(entry, "link", "") or ""
            summary = ""
            for attr in ("summary", "description"):
                val = getattr(entry, attr, None)
                if val and isinstance(val, str):
                    summary = re.sub(r"<[^>]+>", " ", val).strip()
                    break

            combined = f"{title} {summary}"
            if not _FIRE_KEYWORDS.search(combined):
                continue

            gravite = 2 if _HIGH_GRAVITY_RE.search(title) else 1

            results.append({
                "source": "incendies",
                "source_url": link,
                "titre": title,
                "auteur": name,
                "date_publication": _parse_rss_date(entry),
                "date_evenement": None,
                "categorie": "incendie",
                "gravite": gravite,
                "lieu_nom": None,
                "lieu_code_insee": None,
                "lieu_niveau": "national",
                "description": summary,
                "skip_extraction": False,
            })
        except Exception:
            continue

    return results


class IncendiesConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "incendies"

    @property
    def replace_on_ingest(self) -> bool:
        return False

    async def fetch(self) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"User-Agent": UA},
            follow_redirects=True,
        ) as client:
            tasks = [_fetch_feed(client, feed, loop) for feed in _RSS_FEEDS]
            feed_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[dict[str, Any]] = []
        for feed, res in zip(_RSS_FEEDS, feed_results):
            if isinstance(res, Exception):
                self._logger.warning("Incendies feed %s failed: %s", feed["name"], res)
            else:
                results.extend(res)

        if not results:
            self._logger.warning("Incendies: no items found across all feeds")

        return results
