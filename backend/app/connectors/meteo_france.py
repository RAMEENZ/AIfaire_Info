import httpx
from datetime import datetime, timezone
from typing import Any

from app.connectors.base import BaseConnector

VIGILANCE_URL = (
    "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets"
    "/vigilancemeteo/records?limit=100"
)

COULEUR_TO_GRAVITE: dict[str, int] = {
    "Vert": 0,
    "Jaune": 1,
    "Orange": 2,
    "Rouge": 3,
    "vert": 0,
    "jaune": 1,
    "orange": 2,
    "rouge": 3,
}

RISQUE_TO_CATEGORIE: dict[str, str] = {
    "Vent violent": "meteo",
    "Pluie-Inondation": "crue",
    "Orages": "meteo",
    "Inondation": "crue",
    "Neige-verglas": "meteo",
    "Canicule": "meteo",
    "Grand Froid": "meteo",
    "Avalanches": "meteo",
    "Vagues-Submersion": "meteo",
}


class MeteoFranceConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "meteo_france"

    async def fetch(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(VIGILANCE_URL)
            response.raise_for_status()
            data = response.json()

        results: list[dict[str, Any]] = []
        records = data.get("results", [])

        for record in records:
            fields = record if isinstance(record, dict) else {}

            couleur_raw = (
                fields.get("couleur")
                or fields.get("color")
                or fields.get("niveau_couleur_id", "")
            )
            couleur = str(couleur_raw).strip()
            gravite = COULEUR_TO_GRAVITE.get(couleur, 0)

            if gravite == 0:
                continue

            dep = (
                fields.get("dep")
                or fields.get("num_dep")
                or fields.get("numero_departement")
                or fields.get("department_number")
                or ""
            )
            risque = (
                fields.get("risque")
                or fields.get("type_risque")
                or fields.get("phenomene")
                or "Vigilance météo"
            )
            titre = f"Vigilance {couleur} – {risque} – Département {dep}"
            dept_name = fields.get("nom_dep") or fields.get("department_name") or f"Département {dep}"

            date_debut_raw = fields.get("date_debut") or fields.get("debut_validite")
            date_fin_raw = fields.get("date_fin") or fields.get("fin_validite")

            date_pub = self._parse_date(date_debut_raw) or datetime.now(timezone.utc)

            source_url = f"https://vigilance.meteofrance.fr/#{dep}"

            results.append(
                {
                    "source": self.name,
                    "source_url": source_url,
                    "titre": titre,
                    "auteur": "Météo-France",
                    "date_publication": date_pub.isoformat(),
                    "date_evenement": self._parse_date(date_fin_raw).isoformat() if self._parse_date(date_fin_raw) else None,
                    "categorie": RISQUE_TO_CATEGORIE.get(str(risque), "meteo"),
                    "gravite": gravite,
                    "lieu_nom": dept_name,
                    "lieu_code_insee": str(dep) if dep else None,
                    "lieu_niveau": "departement",
                    "raw": fields,
                }
            )

        return results

    def _parse_date(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            s = str(value).strip()
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(s[:len(fmt)], fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except ValueError:
                    continue
        except Exception:
            pass
        return None
