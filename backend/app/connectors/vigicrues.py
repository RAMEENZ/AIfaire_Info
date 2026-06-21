import hashlib
import httpx
from datetime import datetime, timezone
from typing import Any

from app.connectors.base import BaseConnector

VIGICRUES_GEOJSON_URL = "https://www.vigicrues.gouv.fr/services/InfoVigiCru.geojson"

NIVEAU_TO_GRAVITE: dict[int, int] = {1: 0, 2: 1, 3: 2, 4: 3}
NIVEAU_LABELS: dict[int, str] = {1: "Vert", 2: "Jaune", 3: "Orange", 4: "Rouge"}


def _multilinestring_centroid(coordinates: list) -> tuple[float, float] | None:
    """Compute centroid of a MultiLineString coordinate array."""
    all_pts: list[tuple[float, float]] = []
    for line in coordinates:
        for pt in line:
            if len(pt) >= 2:
                all_pts.append((float(pt[0]), float(pt[1])))
    if not all_pts:
        return None
    lon = sum(p[0] for p in all_pts) / len(all_pts)
    lat = sum(p[1] for p in all_pts) / len(all_pts)
    return lat, lon


class VigicruesConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "vigicrues"

    @property
    def replace_on_ingest(self) -> bool:
        return True

    async def fetch(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(
            timeout=30.0, headers={"User-Agent": "faire-info/1.0"}
        ) as client:
            resp = await client.get(VIGICRUES_GEOJSON_URL)
            resp.raise_for_status()
            data = resp.json()

        results: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for feature in data.get("features", []):
            try:
                props = feature.get("properties", {})
                niveau = int(props.get("NivInfViCr", 1))
                gravite = NIVEAU_TO_GRAVITE.get(niveau, 0)
                if gravite == 0:
                    continue

                nom = props.get("lbentcru") or props.get("acroentcru") or "Cours d'eau"
                code = props.get("CdEntCru") or props.get("id")
                if not code:
                    # Sans identifiant unique, l'URL serait identique pour tous
                    # les tronçons non codifiés → ON CONFLICT écrase tous sauf un.
                    # On génère un identifiant stable depuis le nom du tronçon.
                    code = "unknown-" + hashlib.md5(nom.encode()).hexdigest()[:8]
                label = NIVEAU_LABELS.get(niveau, "Inconnu")
                titre = f"Vigilance crues {label} – {nom}"

                geom = feature.get("geometry", {})
                centroid = None
                if geom.get("type") == "MultiLineString":
                    centroid = _multilinestring_centroid(geom.get("coordinates", []))
                elif geom.get("type") == "LineString":
                    coords = geom.get("coordinates", [])
                    if coords:
                        mid = coords[len(coords) // 2]
                        centroid = (float(mid[1]), float(mid[0]))

                item: dict[str, Any] = {
                    "source": self.name,
                    "source_url": f"https://www.vigicrues.gouv.fr/troncon.php?ent={code}",
                    "titre": titre,
                    "auteur": "Vigicrues",
                    "date_publication": now.isoformat(),
                    "date_evenement": None,
                    "categorie": "crue",
                    "gravite": gravite,
                    "lieu_nom": nom,
                    "lieu_code_insee": None,
                    "lieu_niveau": "commune",
                    "resume_ia": f"Vigilance crues {label.lower()} sur le tronçon {nom}.",
                }

                if centroid:
                    item["lieu_lat"] = centroid[0]
                    item["lieu_lon"] = centroid[1]
                    item["lieu_confiance_geo"] = 0.9
                    item["skip_geocoding"] = True

                results.append(item)
            except Exception as exc:
                self._logger.warning("Skipping vigicrues feature: %s", exc)
                continue

        return results
