import httpx
from datetime import datetime, timezone
from typing import Any

from app.connectors.base import BaseConnector
from app.geo_data import DEPT_CODE_TO_NAME

COUPURES_URL = (
    "https://opendata.enedis.fr/api/explore/v2.1/catalog/datasets"
    "/coupures-delectricite/records?limit=100&order_by=date_debut_perturbation%20desc"
)

FALLBACK_URL = (
    "https://opendata.enedis.fr/api/explore/v2.1/catalog/datasets"
    "/bilan-electrique-demi-heure/records?limit=1"
)


def _count_clients(record: dict) -> int:
    for key in ("nb_clients_touches", "nombre_clients", "clients_touches", "nb_clients"):
        v = record.get(key)
        if v is not None:
            try:
                return int(v)
            except (ValueError, TypeError):
                pass
    return 0


def _clients_to_gravite(nb: int) -> int:
    if nb >= 10000:
        return 3
    if nb >= 1000:
        return 2
    if nb >= 100:
        return 1
    return 0


class EnedisConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "enedis"

    async def fetch(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(COUPURES_URL)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
                self._logger.warning("Primary endpoint failed (%s), trying fallback", exc)
                try:
                    fallback_resp = await client.get(FALLBACK_URL)
                    fallback_resp.raise_for_status()
                except Exception as fallback_exc:
                    self._logger.error("Fallback also failed: %s", fallback_exc)
                    return []
                self._logger.info("Fallback endpoint is reachable but contains no coupure data.")
                return []

        results: list[dict[str, Any]] = []
        records = data.get("results", [])

        for record in records:
            try:
                nb_clients = _count_clients(record)
                gravite = _clients_to_gravite(nb_clients)

                commune = (
                    record.get("commune")
                    or record.get("libelle_commune")
                    or record.get("nom_commune")
                    or ""
                )
                dept = record.get("departement") or record.get("num_departement") or ""

                date_debut_raw = (
                    record.get("date_debut_perturbation")
                    or record.get("date_debut")
                    or record.get("horodate")
                )
                date_fin_raw = record.get("date_fin_perturbation") or record.get("date_fin")

                date_pub = self._parse_date(date_debut_raw) or datetime.now(timezone.utc)

                cause = record.get("cause_perturbation") or record.get("cause") or "Coupure"
                dept_name = DEPT_CODE_TO_NAME.get(str(dept).zfill(2)) if dept else None
                lieu_label = commune or dept_name or (f"Département {dept}" if dept else "France")
                titre = f"{cause} – {lieu_label}"
                if nb_clients:
                    titre += f" ({nb_clients:,} clients)"

                record_id = record.get("recordid") or record.get("id") or hash(str(record))
                source_url = f"https://opendata.enedis.fr/explore/dataset/coupures-delectricite/record/{record_id}"

                date_fin = self._parse_date(date_fin_raw)
                resume = titre
                if date_fin:
                    resume += f". Fin prévue : {date_fin.strftime('%d/%m/%Y %H:%M')} UTC."

                results.append(
                    {
                        "source": self.name,
                        "source_url": source_url,
                        "titre": titre,
                        "auteur": "Enedis",
                        "date_publication": date_pub.isoformat(),
                        "date_evenement": date_fin.isoformat() if date_fin else None,
                        "categorie": "energie",
                        "gravite": gravite,
                        "lieu_nom": lieu_label,
                        "lieu_code_insee": str(dept) if dept else None,
                        "lieu_niveau": "commune" if commune else ("departement" if dept else "national"),
                        "resume_ia": resume,
                        "skip_extraction": True,
                        "raw": record,
                    }
                )
            except Exception as exc:
                self._logger.warning("Skipping enedis record: %s", exc)
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
