"""Opérations de maintenance ponctuelles, exécutables dans le conteneur :

    docker compose exec backend python -m app.maintenance backfill-locations [--dry-run]

Placé dans le package `app` (et non dans scripts/) car l'image Docker ne copie
que `app/` — un script sous scripts/ ne serait pas présent en production.
"""
import asyncio
import sys

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Event
from app.pipeline.geocoder import geocode
from app.pipeline.toponym import location_from_url


async def backfill_url_locations(dry_run: bool = False) -> dict:
    """Re-localise les articles presse « national » dont l'URL contient un code
    de localisation (INSEE actu.fr, code postal Ouest-France, département
    leparisien.fr). 100 % déterministe (aucun appel LLM). Nécessaire car une
    ré-ingestion ne ré-extrait pas les URL déjà connues."""
    updated = communes = depts = 0
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Event).where(
                Event.source == "presse_rss",
                Event.lieu_niveau == "national",
                Event.source_url.like("http%"),
            )
        )).scalars().all()

        print(f"{len(rows)} articles 'national' à examiner…")
        for e in rows:
            loc = location_from_url(e.source_url)
            if not loc:
                continue

            if loc["niveau"] == "commune":
                lat, lon, insee, niveau, nom = (
                    loc["lat"], loc["lon"], loc["code_insee"], "commune", loc["lieu_nom"])
                communes += 1
            else:
                geo = await geocode(loc["lieu_nom"])  # département → centroïde
                if geo["lat"] is None:
                    continue
                lat, lon, insee, niveau, nom = (
                    geo["lat"], geo["lon"], geo.get("code_insee"), geo["niveau"], loc["lieu_nom"])
                depts += 1

            if not dry_run:
                e.lieu_nom = nom
                e.lieu_lat = lat
                e.lieu_lon = lon
                e.lieu_code_insee = insee
                e.lieu_niveau = niveau
                e.lieu_confiance_geo = 0.9
                e.geom = f"SRID=4326;POINT({lon} {lat})"
            updated += 1

        if not dry_run:
            await session.commit()

    mode = "SIMULATION — rien écrit" if dry_run else "appliqué"
    print(f"[{mode}] {updated} re-localisés : {communes} communes (INSEE/CP), {depts} départements")
    return {"updated": updated, "communes": communes, "departements": depts, "dry_run": dry_run}


def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    dry = "--dry-run" in argv
    if cmd == "backfill-locations":
        asyncio.run(backfill_url_locations(dry_run=dry))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
