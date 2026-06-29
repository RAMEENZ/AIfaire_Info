"""Opérations de maintenance ponctuelles, exécutables dans le conteneur :

    docker compose exec backend python -m app.maintenance backfill-locations [--dry-run]
    docker compose exec backend python -m app.maintenance check-feeds [--verbose]

Placé dans le package `app` (et non dans scripts/) car l'image Docker ne copie
que `app/` — un script sous scripts/ ne serait pas présent en production.
"""
import asyncio
import sys
from collections import Counter

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
        # On reprend aussi les 'departement' : un précédent backfill a pu les
        # placer au centroïde départemental alors que le slug donne la commune.
        rows = (await session.execute(
            select(Event).where(
                Event.source == "presse_rss",
                Event.lieu_niveau.in_(["national", "departement"]),
                Event.source_url.like("http%"),
            )
        )).scalars().all()

        print(f"{len(rows)} articles 'national'/'departement' à examiner…")
        for e in rows:
            loc = location_from_url(e.source_url)
            if not loc:
                continue

            if loc["niveau"] == "commune":
                lat, lon, insee, niveau, nom = (
                    loc["lat"], loc["lon"], loc["code_insee"], "commune", loc["lieu_nom"])
                communes += 1
            elif e.lieu_niveau == "national":
                geo = await geocode(loc["lieu_nom"])  # national → centroïde départemental
                if geo["lat"] is None:
                    continue
                lat, lon, insee, niveau, nom = (
                    geo["lat"], geo["lon"], geo.get("code_insee"), geo["niveau"], loc["lieu_nom"])
                depts += 1
            else:
                continue  # déjà 'departement' et l'URL ne donne pas mieux : on n'y touche pas

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


async def check_feeds(verbose: bool = False) -> dict:
    """Sonde les 877 flux RSS et reporte leur santé (vivant / vide / 4xx / 5xx /
    erreur réseau). Sert à repérer les flux morts à élaguer."""
    import httpx
    import feedparser
    from app.connectors.presse_rss import RSS_FEEDS, UA

    stats: Counter = Counter()
    dead: list[tuple] = []
    sem = asyncio.Semaphore(24)
    loop = asyncio.get_event_loop()

    async def probe(cfg: dict) -> None:
        name, url = cfg.get("name", "?"), cfg.get("url", "")
        async with sem:
            try:
                async with httpx.AsyncClient(
                    headers={"User-Agent": UA}, follow_redirects=True, timeout=15.0
                ) as client:
                    r = await client.get(url)
            except Exception as exc:
                stats["erreur_reseau"] += 1
                dead.append((type(exc).__name__, name, url))
                return
            if r.status_code >= 500:
                stats["http_5xx"] += 1
                dead.append((r.status_code, name, url))
            elif r.status_code >= 400:
                stats["http_4xx"] += 1
                dead.append((r.status_code, name, url))
            else:
                feed = await loop.run_in_executor(None, feedparser.parse, r.content)
                if len(getattr(feed, "entries", [])):
                    stats["ok"] += 1
                else:
                    stats["vide_0_item"] += 1
                    dead.append(("0 items", name, url))

    await asyncio.gather(*[probe(c) for c in RSS_FEEDS])

    total = sum(stats.values())
    alive = stats.get("ok", 0)
    print(f"=== Santé des {total} flux RSS ===")
    for k in ("ok", "vide_0_item", "http_4xx", "http_5xx", "erreur_reseau"):
        print(f"  {k:16} {stats.get(k, 0)}")
    print(f"--> {alive}/{total} flux vivants ({100 * alive / max(total, 1):.0f} %), "
          f"{len(dead)} à problème")
    dead.sort(key=lambda d: str(d[0]))
    shown = dead if verbose else dead[:40]
    for status, name, url in shown:
        print(f"  [{status}] {name} — {url}")
    if not verbose and len(dead) > 40:
        print(f"  … +{len(dead) - 40} autres (relancer avec --verbose)")
    return dict(stats)


def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "backfill-locations":
        asyncio.run(backfill_url_locations(dry_run="--dry-run" in argv))
        return 0
    if cmd == "check-feeds":
        asyncio.run(check_feeds(verbose="--verbose" in argv))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
