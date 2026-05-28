import httpx
from datetime import datetime, timezone
from typing import Any

from app.connectors.base import BaseConnector
from app.geo_data import DEPT_CODE_TO_NAME

VIGILANCE_BASE_URL = (
    "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets"
    "/weatherref-france-vigilance-meteo-departement/records"
)
# Filtre côté serveur : uniquement les alertes non-vertes
VIGILANCE_PARAMS = {"where": "color_id>1", "limit": 100}
PAGE_SIZE = 100

COLOR_ID_TO_GRAVITE: dict[int, int] = {1: 0, 2: 1, 3: 2, 4: 3}
COLOR_TO_GRAVITE: dict[str, int] = {
    "vert": 0, "jaune": 1, "orange": 2, "rouge": 3,
}

PHENOMENON_TO_CATEGORIE: dict[str, str] = {
    "vent": "meteo",
    "pluie": "meteo",
    "orages": "meteo",
    "neige / verglas": "meteo",
    "canicule": "meteo",
    "grand froid": "meteo",
    "avalanches": "meteo",
    "vagues submersion": "meteo",
    "inondation": "crue",
    "crues": "crue",
}

# domain_id peut être '10', '05', '0610'…
# On extrait le code département en retirant les préfixes IGN (06xx → 06, etc.)
def _normalise_dept(domain_id: str) -> str:
    d = str(domain_id).strip()
    # Codes DOM : '971'-'976' → retourner tel quel
    if len(d) == 3 and d.isdigit():
        return d
    # Codes Corse : '2A', '2B'
    if d.upper() in ("2A", "2B"):
        return d.upper()
    # Préfixe à 4 chiffres type '0610' → '06'
    if len(d) == 4 and d.isdigit():
        return d[:2]
    stripped = d.lstrip("0") or "0"
    return stripped.zfill(2) if stripped.isdigit() else stripped


class MeteoFranceConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "meteo_france"

    @property
    def replace_on_ingest(self) -> bool:
        return True

    async def fetch(self) -> list[dict[str, Any]]:
        all_records: list[dict] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            offset = 0
            while True:
                params = {**VIGILANCE_PARAMS, "offset": offset}
                response = await client.get(VIGILANCE_BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()
                batch = data.get("results", [])
                all_records.extend(batch)
                if len(batch) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE

        results: list[dict[str, Any]] = []
        seen_dept_phenomenon: set[str] = set()

        for record in all_records:
            color_id = int(record.get("color_id", 1))
            if color_id <= 1:
                continue

            gravite = COLOR_ID_TO_GRAVITE.get(color_id, 0)
            color = str(record.get("color", "")).lower()
            if gravite == 0:
                gravite = COLOR_TO_GRAVITE.get(color, 0)
            if gravite == 0:
                continue

            domain_id = str(record.get("domain_id", ""))
            dept_code = _normalise_dept(domain_id)
            dept_name = DEPT_CODE_TO_NAME.get(dept_code, dept_code)
            phenomenon = str(record.get("phenomenon", "vigilance météo")).strip()
            categorie = PHENOMENON_TO_CATEGORIE.get(phenomenon.lower(), "meteo")

            # Déduplique dept+phénomène (plusieurs écheances)
            key = f"{dept_code}:{phenomenon}"
            if key in seen_dept_phenomenon:
                continue
            seen_dept_phenomenon.add(key)

            titre = f"Vigilance {color} – {phenomenon.capitalize()} – {dept_name}"
            date_pub = self._parse_iso(record.get("begin_time") or record.get("product_datetime"))

            pheno_slug = phenomenon.lower().replace(" / ", "-").replace(" ", "-")
            results.append(
                {
                    "source": self.name,
                    "source_url": f"https://vigilance.meteofrance.fr/#{dept_code}-{pheno_slug}",
                    "titre": titre,
                    "auteur": "Météo-France",
                    "date_publication": (date_pub or datetime.now(timezone.utc)).isoformat(),
                    "date_evenement": self._parse_iso(record.get("end_time"), isoformat=True),
                    "categorie": categorie,
                    "gravite": gravite,
                    "lieu_nom": dept_name,
                    "lieu_code_insee": dept_code,
                    "lieu_niveau": "departement",
                    "resume_ia": f"Vigilance météorologique {color} pour {phenomenon} dans le département {dept_name} ({dept_code}).",
                }
            )

        return results

    def _parse_iso(self, value: Any, isoformat: bool = False) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat() if isoformat else dt  # type: ignore[return-value]
        except Exception:
            return None
