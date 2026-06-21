import hashlib
import json
import httpx
from datetime import datetime, timezone
from typing import Any

from app.connectors.base import BaseConnector
from app.geo_data import DEPT_CODE_TO_NAME

_ENDPOINTS = [
    "https://data.enedis.fr/api/explore/v2.1/catalog/datasets/liste-des-coupures-d-electricite-en-cours/records?limit=100&order_by=date_debut_perturbation%20desc",
    "https://opendata.reseaux-energies.fr/api/explore/v2.1/catalog/datasets/coupures-electricite/records?limit=100",
    "https://opendata.enedis.fr/api/explore/v2.1/catalog/datasets/coupures-delectricite/records?limit=100&order_by=date_debut_perturbation%20desc",
    "https://opendata.enedis.fr/api/explore/v2.1/catalog/datasets/coupure-electricite/records?limit=100",
]


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
            data = None
            for url in _ENDPOINTS:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    data = response.json()
                    self._logger.info("Enedis: using endpoint %s", url)
                    break
                except Exception as exc:
                    self._logger.warning("Enedis endpoint failed (%s): %s", url, exc)
            if data is None:
                self._logger.error("All Enedis endpoints failed, returning empty list")
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

                # hash() builtin est randomisé par process (PYTHONHASHSEED) : le
                # même enregistrement produirait une source_url différente à
                # chaque redémarrage, cassant la déduplication ON CONFLICT. On
                # utilise un hash déterministe sur une sérialisation stable.
                record_id = record.get("recordid") or record.get("id")
                if not record_id:
                    digest = hashlib.sha1(
                        json.dumps(record, sort_keys=True, default=str).encode()
                    ).hexdigest()
                    record_id = digest[:16]
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
