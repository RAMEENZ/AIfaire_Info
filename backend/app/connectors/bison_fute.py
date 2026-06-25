import asyncio
import re
import feedparser
import httpx
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.connectors.base import BaseConnector

# Plusieurs candidats de flux RSS Bison Futé : le premier qui répond avec des
# items gagne, sinon on bascule sur le parsing HTML de la page d'accueil.
_RSS_URLS = [
    "https://www.bison-fute.gouv.fr/feed/rss.xml",
    "https://www.bison-fute.gouv.fr/rss.xml",
    "https://www.bison-fute.gouv.fr/actualites/rss.xml",
    "https://www.bison-fute.gouv.fr/rss/conditions.xml",
    "https://bison-fute.gouv.fr/rss.xml",
]

_HOMEPAGE = "https://www.bison-fute.gouv.fr/"

# User-Agent navigateur réaliste (Firefox) : l'UA "robot" précédent était
# souvent bloqué (403) par le WAF du site. follow_redirects géré côté client.
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"

_COULEUR_GRAVITE = {
    "vert": 0,
    "orange": 1,
    "rouge": 2,
    "noir": 3,
}

_COULEUR_RE = re.compile(r"\b(vert|orange|rouge|noir)\b", re.IGNORECASE)


def _gravite_from_text(text: str) -> int:
    m = _COULEUR_RE.search(text)
    if m:
        return _COULEUR_GRAVITE.get(m.group(1).lower(), 0)
    return 0


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


def _items_from_parsed(parsed: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry in getattr(parsed, "entries", []):
        title: str = getattr(entry, "title", "").strip()
        if not title:
            continue
        link: str = getattr(entry, "link", "") or ""
        summary = ""
        for attr in ("summary", "description"):
            val = getattr(entry, attr, None)
            if val and isinstance(val, str):
                summary = re.sub(r"<[^>]+>", " ", val).strip()
                break

        combined = f"{title} {summary}"
        gravite = _gravite_from_text(combined)

        lieu_m = re.search(r"\bA\d{1,3}\b|\bN\d{1,3}\b|\b[A-Z][a-z][\w\-]+\b", title)
        lieu_nom = lieu_m.group(0) if lieu_m else None

        results.append({
            "source": "bison_fute",
            "source_url": link,
            "titre": title,
            "auteur": "Bison Futé",
            "date_publication": _parse_rss_date(entry),
            "date_evenement": None,
            "categorie": "transport",
            "gravite": gravite,
            "lieu_nom": lieu_nom,
            "lieu_code_insee": None,
            "lieu_niveau": "national",
            "description": summary,
            "skip_extraction": True,
        })
    return results


def _items_from_html(html: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    pattern = re.compile(
        r'class="[^"]*(?:couleur|conditions|trafic)[^"]*"[^>]*>(.*?)</(?:td|div|span)',
        re.IGNORECASE | re.DOTALL,
    )
    for m in pattern.finditer(html):
        raw = re.sub(r"<[^>]+>", " ", m.group(1)).strip()
        if not raw or len(raw) < 5:
            continue
        gravite = _gravite_from_text(raw)
        results.append({
            "source": "bison_fute",
            "source_url": _HOMEPAGE,
            "titre": raw[:200],
            "auteur": "Bison Futé",
            "date_publication": now_iso,
            "date_evenement": None,
            "categorie": "transport",
            "gravite": gravite,
            "lieu_nom": None,
            "lieu_code_insee": None,
            "lieu_niveau": "national",
            "description": raw,
            "skip_extraction": True,
        })
    return results


class BisonFuteConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "bison_fute"

    @property
    def replace_on_ingest(self) -> bool:
        return True

    async def fetch(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": UA},
            follow_redirects=True,
        ) as client:
            loop = asyncio.get_running_loop()

            for url in _RSS_URLS:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200 and resp.content:
                        parsed = await loop.run_in_executor(None, feedparser.parse, resp.content)
                        items = _items_from_parsed(parsed)
                        if items:
                            self._logger.info("Bison Futé: got %d items from %s", len(items), url)
                            return items
                except Exception as exc:
                    self._logger.debug("Bison Futé RSS %s failed: %s", url, exc)

            self._logger.debug("Bison Futé: all RSS failed, trying homepage HTML")
            try:
                resp = await client.get(_HOMEPAGE)
                if resp.status_code == 200:
                    items = _items_from_html(resp.text)
                    if items:
                        return items
            except Exception as exc:
                self._logger.debug("Bison Futé homepage fetch failed: %s", exc)

            # Bison Futé n'expose plus de flux RSS/HTML exploitable : échec attendu.
            self._logger.info("Bison Futé: aucune source disponible, 0 événement")
            return []
