import httpx
from datetime import datetime, timezone
from typing import Any

from app.connectors.base import BaseConnector

# USGS FDSNWS filtrée sur la bounding box France + DOM proches
USGS_URL = (
    "https://earthquake.usgs.gov/fdsnws/event/1/query"
    "?format=geojson"
    "&minlatitude=41&maxlatitude=52"
    "&minlongitude=-6&maxlongitude=10"
    "&minmagnitude=1.5"
    "&orderby=time"
    "&limit=50"
)


def magnitude_to_gravite(mag: float) -> int:
    if mag >= 4.0:
        return 3
    if mag >= 3.0:
        return 2
    if mag >= 2.0:
        return 1
    return 0


class RenassConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "renass"

    async def fetch(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(USGS_URL)
            response.raise_for_status()
            data = response.json()

        results: list[dict[str, Any]] = []

        for feature in data.get("features", []):
            try:
                props = feature.get("properties", {})
                geometry = feature.get("geometry", {})

                coords = geometry.get("coordinates", [])
                if not coords or len(coords) < 2:
                    continue

                lon = float(coords[0])
                lat = float(coords[1])
                depth_km = float(coords[2]) if len(coords) > 2 else None

                mag = float(props.get("mag") or 0.0)
                gravite = magnitude_to_gravite(mag)

                time_raw = props.get("time")
                if isinstance(time_raw, (int, float)):
                    date_pub = datetime.fromtimestamp(time_raw / 1000, tz=timezone.utc)
                elif time_raw:
                    date_pub = datetime.fromisoformat(str(time_raw).replace("Z", "+00:00"))
                else:
                    date_pub = datetime.now(timezone.utc)

                place = props.get("place") or "France"
                event_id = feature.get("id") or props.get("code") or ""
                mag_type = props.get("magType") or "M"

                titre = f"Séisme {mag_type}{mag:.1f} – {place}"
                if depth_km is not None:
                    titre += f" (prof. {depth_km:.0f} km)"

                source_url = props.get("url") or f"https://earthquake.usgs.gov/earthquakes/eventpage/{event_id}"

                results.append(
                    {
                        "source": self.name,
                        "source_url": source_url,
                        "titre": titre,
                        "auteur": "USGS / RéNaSS",
                        "date_publication": date_pub.isoformat(),
                        "date_evenement": date_pub.isoformat(),
                        "categorie": "seisme",
                        "gravite": gravite,
                        "lieu_nom": place,
                        "lieu_code_insee": None,
                        "lieu_lat": lat,
                        "lieu_lon": lon,
                        "lieu_niveau": "commune",
                        "lieu_confiance_geo": 1.0,
                        "resume_ia": f"Séisme de magnitude {mag:.1f} détecté à {place}.",
                        "skip_geocoding": True,
                        "skip_extraction": True,
                    }
                )
            except Exception as exc:
                self._logger.warning("Skipping seismic feature: %s", exc)
                continue

        return results
