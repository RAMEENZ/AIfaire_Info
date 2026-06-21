"""
OpenSky Network – incidents aériens au-dessus de la France.
Seuls les squawks d'urgence (7700/7600/7500) au-dessus de la France métropolitaine
sont remontés.
"""
import logging
import httpx
from datetime import datetime, timezone
from typing import Any

from app.connectors.base import BaseConnector

_FRANCE_BBOX = {"lamin": 41.0, "lomin": -5.5, "lamax": 51.5, "lomax": 10.0}
_OPENSKY_URL = "https://opensky-network.org/api/states/all"
UA = "faire-info/1.0"

# squawk → (libellé, gravité, catégorie)
_EMERGENCY_SQUAWKS = {
    "7700": ("urgence aérienne (Mayday)", 3, "transport"),
    "7600": ("panne radio", 2, "transport"),
    "7500": ("détournement présumé", 3, "ordre_public"),
}

# Indices des colonnes dans la réponse OpenSky
_IDX_CALLSIGN = 1
_IDX_ORIGIN = 2
_IDX_LON = 5
_IDX_LAT = 6
_IDX_ALTITUDE = 7
_IDX_ON_GROUND = 8
_IDX_SQUAWK = 14
_IDX_ICAO24 = 0


class OpenSkyConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "opensky"

    @property
    def replace_on_ingest(self) -> bool:
        return True

    async def fetch(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": UA}) as client:
                resp = await client.get(_OPENSKY_URL, params=_FRANCE_BBOX)
        except Exception as exc:
            self._logger.warning("OpenSky fetch failed: %s", exc)
            return []

        if resp.status_code == 429:
            self._logger.warning("OpenSky: rate limited (429)")
            return []
        if resp.status_code != 200:
            self._logger.warning("OpenSky: HTTP %d", resp.status_code)
            return []

        states = (resp.json().get("states") or [])
        results: list[dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for state in states:
            if len(state) <= _IDX_SQUAWK:
                continue
            squawk = state[_IDX_SQUAWK]
            if squawk not in _EMERGENCY_SQUAWKS:
                continue
            if state[_IDX_ON_GROUND]:
                continue

            label, gravite, categorie = _EMERGENCY_SQUAWKS[squawk]
            callsign = (state[_IDX_CALLSIGN] or "").strip() or "Inconnu"
            icao24 = state[_IDX_ICAO24] or ""
            lat = state[_IDX_LAT]
            lon = state[_IDX_LON]
            country = state[_IDX_ORIGIN] or ""
            altitude = state[_IDX_ALTITUDE]

            desc = f"Squawk {squawk} ({label})"
            if country:
                desc += f" | Origine : {country}"
            if altitude:
                desc += f" | Altitude : {int(altitude)} m"

            results.append({
                "source": self.name,
                "source_url": f"https://opensky-network.org/aircraft-profile?icao24={icao24}",
                "titre": f"Avion en {label} : {callsign}",
                "auteur": "OpenSky Network",
                "date_publication": now_iso,
                "date_evenement": None,
                "categorie": categorie,
                "gravite": gravite,
                "lieu_nom": None,
                "lieu_lat": lat,
                "lieu_lon": lon,
                "lieu_niveau": "commune",
                "lieu_code_insee": None,
                "lieu_confiance_geo": 1.0,
                "description": desc,
                "skip_extraction": True,
                "skip_geocoding": True,
            })

        if results:
            self._logger.info("OpenSky: %d emergency aircraft", len(results))
        return results
