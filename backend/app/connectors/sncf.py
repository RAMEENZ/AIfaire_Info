import logging
import httpx
from datetime import datetime, timezone
from typing import Any

from app.connectors.base import BaseConnector

# Migration 2026 : le portail open data SNCF (ressources.data.sncf.com,
# plateforme Opendatasoft) a renommé les datasets de perturbations. Les anciens
# slugs renvoient des 404. On garde plusieurs slugs plausibles pour couvrir les
# variantes courantes (disruptions / infotrafic temps réel).
_ENDPOINTS = [
    "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/incidents-securite/records?limit=100&order_by=date%20desc",
    "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/regularite-mensuelle-tgv-aqst/records?limit=100",
    "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/disruptions/records?limit=100&order_by=updated%20desc",
    "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/disruptions-sncf-voyageurs/records?limit=100&order_by=updated%20desc",
    "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/infotrafic-temps-reel/records?limit=100",
    "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/infotrafic/records?limit=100",
]

UA = "faire-info/1.0"


def _parse_iso(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value[:19], fmt[:len(fmt)])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def _first_nonempty(record: dict, *keys: str) -> str:
    for k in keys:
        v = record.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return ""


class SNCFConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "sncf"

    @property
    def replace_on_ingest(self) -> bool:
        return True

    async def fetch(self) -> list[dict[str, Any]]:
        data: dict | None = None
        # follow_redirects=True : cohérence avec les portails Opendatasoft qui
        # peuvent renvoyer des 301 vers le domaine/dataset migré.
        async with httpx.AsyncClient(
            timeout=20.0, headers={"User-Agent": UA}, follow_redirects=True
        ) as client:
            for url in _ENDPOINTS:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        break
                    self._logger.warning("SNCF endpoint %s returned %d", url, resp.status_code)
                except Exception as exc:
                    self._logger.warning("SNCF endpoint %s failed: %s", url, exc)

        if data is None:
            self._logger.warning("All SNCF endpoints failed, returning []")
            return []

        results: list[dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for record in data.get("results", []):
            try:
                disruption_id = _first_nonempty(record, "disruption_id", "id")
                source_url = (
                    record.get("links", [{}])[0].get("href", "")
                    if isinstance(record.get("links"), list) and record.get("links")
                    else f"https://ressources.data.sncf.com/disruption/{disruption_id}" if disruption_id else ""
                )

                titre = _first_nonempty(record, "cause", "severity", "status", "disruption_id", "title")
                if not titre:
                    titre = f"Perturbation SNCF {disruption_id or 'inconnue'}"

                date_pub = _parse_iso(record.get("updated") or record.get("start_date")) or now_iso

                severity = (record.get("severity") or "").lower()
                gravite = 2 if "major" in severity else 1 if severity else 0

                lieu_nom = _first_nonempty(record, "stop_area_name", "network", "line_name")

                desc_parts = []
                for field in ("severity", "cause", "status", "effect", "message"):
                    val = record.get(field)
                    if val and str(val).strip():
                        desc_parts.append(f"{field}: {val}")
                description = " | ".join(desc_parts)

                results.append({
                    "source": self.name,
                    "source_url": source_url,
                    "titre": titre,
                    "auteur": "SNCF",
                    "date_publication": date_pub,
                    "date_evenement": None,
                    "categorie": "transport",
                    "gravite": gravite,
                    "lieu_nom": lieu_nom or None,
                    "lieu_code_insee": None,
                    "lieu_niveau": "national",
                    "description": description,
                    "skip_extraction": True,
                })
            except Exception as exc:
                self._logger.warning("Skipping SNCF record: %s", exc)
                continue

        return results
