import httpx
from datetime import datetime, timezone
from typing import Any

from app.connectors.base import BaseConnector

TRONCONS_URL = "https://www.vigicrues.gouv.fr/services/1/TronconHydro.json/?TypTH=8&CdEntVigiCru=13"
VIGILANCE_URL = "https://www.vigicrues.gouv.fr/services/1/InfoVigiCru.json/?TypInfoVigiCru=1"

NIVEAU_TO_GRAVITE: dict[int, int] = {1: 0, 2: 1, 3: 2, 4: 3}

NIVEAU_LABELS: dict[int, str] = {
    1: "Vert",
    2: "Jaune",
    3: "Orange",
    4: "Rouge",
}


class VigicruesConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "vigicrues"

    async def fetch(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp_vigi = await client.get(VIGILANCE_URL)
            resp_vigi.raise_for_status()
            vigi_data = resp_vigi.json()

        results: list[dict[str, Any]] = []

        entites = (
            vigi_data.get("CruesObservees", {}).get("InfoVigiCru", [])
            or vigi_data.get("InfoVigiCru", [])
            or []
        )

        if isinstance(entites, dict):
            entites = [entites]

        for entite in entites:
            try:
                niveau_raw = entite.get("NivSituVigiCruEntVigiCru") or entite.get("NivSituVigiCru", 1)
                niveau = int(niveau_raw)
                gravite = NIVEAU_TO_GRAVITE.get(niveau, 0)

                if gravite == 0:
                    continue

                nom = entite.get("LbEntVigiCru") or entite.get("NomEntVigiCru") or "Cours d'eau"
                code = entite.get("CdEntVigiCru") or entite.get("CdTronconVigiCru") or ""
                dept = entite.get("CdDepartement") or entite.get("NumDep") or ""

                date_maj_raw = entite.get("DateMiseAJourVigi") or entite.get("DtHrCreatInfoVigiCru")
                date_pub = self._parse_date(date_maj_raw) or datetime.now(timezone.utc)

                label = NIVEAU_LABELS.get(niveau, "Inconnu")
                titre = f"Vigilance crues {label} – {nom}"

                source_url = f"https://www.vigicrues.gouv.fr/niv_troncon.php?ent={code}"

                results.append(
                    {
                        "source": self.name,
                        "source_url": source_url,
                        "titre": titre,
                        "auteur": "Vigicrues",
                        "date_publication": date_pub.isoformat(),
                        "date_evenement": None,
                        "categorie": "crue",
                        "gravite": gravite,
                        "lieu_nom": nom,
                        "lieu_code_insee": str(dept) if dept else None,
                        "lieu_niveau": "departement" if dept else "national",
                        "raw": entite,
                    }
                )
            except Exception as exc:
                self._logger.warning("Skipping vigicrues entry: %s", exc)
                continue

        return results

    def _parse_date(self, value: Any) -> datetime | None:
        if not value:
            return None
        try:
            s = str(value).strip()
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(s, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except ValueError:
                    continue
        except Exception:
            pass
        return None
