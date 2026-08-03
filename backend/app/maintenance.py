"""Opérations de maintenance ponctuelles, exécutables dans le conteneur :

    docker compose exec backend python -m app.maintenance backfill-locations [--dry-run]
    docker compose exec backend python -m app.maintenance check-feeds [--verbose]
    docker compose exec backend python -m app.maintenance vapid-keys
    docker compose exec backend python -m app.maintenance test-brief [--hours 24]
    docker compose exec backend python -m app.maintenance test-extraction [--limit 15]

Les deux commandes `test-*` servent à juger les prompts sur les données
réelles : elles appellent le modèle mais n'écrivent RIEN en base.

Placé dans le package `app` (et non dans scripts/) car l'image Docker ne copie
que `app/` — un script sous scripts/ ne serait pas présent en production.
"""
import asyncio
import sys
from collections import Counter
from typing import Optional

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


def generate_vapid_keys() -> dict:
    """Génère une paire de clés VAPID pour les notifications Web Push.

    À exécuter une seule fois ; reporter les valeurs dans le .env du serveur.
    Changer de clé invalide TOUS les abonnements existants.
    """
    import base64

    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid01

    vapid = Vapid01()
    vapid.generate_keys()
    private_key = vapid.private_pem().decode()
    # La clé publique attendue par `pushManager.subscribe` est le point EC
    # non compressé, encodé en base64 URL-safe sans remplissage.
    raw_public = vapid.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    public_key = base64.urlsafe_b64encode(raw_public).decode().rstrip("=")

    print("Ajoutez ces lignes au .env du serveur, puis redémarrez le backend :\n")
    print(f"VAPID_PUBLIC_KEY={public_key}")
    print("VAPID_PRIVATE_KEY=<contenu PEM ci-dessous, sur une seule ligne avec des \\n>")
    print("VAPID_CONTACT_EMAIL=vous@exemple.fr\n")
    print("--- clé privée (PEM) ---")
    print(private_key)
    print(
        "\nAttention : la clé privée ne doit jamais être commitée. "
        "Changer de paire invalide tous les abonnements déjà enregistrés."
    )
    return {"public_key": public_key}


async def test_brief(hours: int = 24) -> Optional[str]:
    """Génère un brief sur les données réelles, l'affiche et l'audite — SANS
    l'enregistrer. Sert à juger une retouche de prompt avant de la déployer."""
    from app.config import settings
    from app.pipeline.brief import _generate_text, audit_brief, build_brief_prompts

    if not settings.MISTRAL_API_KEY:
        print("MISTRAL_API_KEY absente : impossible d'appeler le modèle.")
        return None

    built = await build_brief_prompts(hours)
    if built is None:
        print(f"Aucun événement sur les dernières {hours} h : rien à résumer.")
        return None
    system_prompt, user_prompt, event_count = built

    print(f"=== Matière : {event_count} événements sur {hours} h ===")
    print(f"prompt système : {len(system_prompt)} caractères")
    print(f"prompt données : {len(user_prompt)} caractères\n")

    content = await _generate_text(system_prompt, user_prompt)
    if not content:
        print("Échec de l'appel au modèle (voir les logs).")
        return None

    print("=== Brief produit (NON enregistré) ===")
    print(content)

    constats = audit_brief(content)
    print("\n=== Audit automatique ===")
    if constats:
        for c in constats:
            print(f"  ⚠ {c}")
    else:
        print("  Aucun défaut détecté (sections, formules creuses, formatage, redites).")
    mots = len(content.split())
    print(f"  {mots} mots — environ {max(1, round(mots / 200))} min de lecture")
    return content


async def test_extraction(limit: int = 15) -> dict:
    """Rejoue l'extraction sur les derniers articles de presse et mesure ce qui
    compte : part de « actualite », part de « national », qualité des tags et
    des résumés. Ne modifie aucun événement existant."""
    from app.config import settings
    from app.pipeline.extractor import extract_article

    if not settings.MISTRAL_API_KEY:
        print("MISTRAL_API_KEY absente : impossible d'appeler le modèle.")
        return {}

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Event)
            .where(Event.source == "presse_rss")
            .order_by(Event.date_publication.desc())
            .limit(limit)
        )).scalars().all()

    if not rows:
        print("Aucun article de presse en base.")
        return {}

    cats: Counter = Counter()
    lieux: Counter = Counter()
    tags_total = paraphrases = 0

    for e in rows:
        res = await extract_article(e.titre, e.resume_ia or "", None)
        cats[res["categorie"]] += 1
        lieux[res.get("lieu_type") or ("national" if res["lieu_nom"] == "national" else "?")] += 1
        tags_total += len(res["tags"])
        # Un résumé qui reprend le titre mot pour mot n'apporte rien : le prompt
        # l'interdit explicitement, on vérifie que la consigne passe.
        mots_titre = set(e.titre.lower().split())
        mots_resume = set(res["resume_ia"].lower().split())
        if mots_titre and len(mots_titre & mots_resume) / len(mots_titre) > 0.8:
            paraphrases += 1

        print(f"\n— {e.titre[:100]}")
        print(f"  catégorie {res['categorie']:<12} lieu {res['lieu_nom']} "
              f"({res.get('lieu_type') or 'type non fourni'})  gravité {res['gravite']}")
        print(f"  tags      {', '.join(res['tags']) or '(aucun)'}")
        print(f"  résumé    {res['resume_ia'][:180]}")

    n = len(rows)
    print(f"\n=== Bilan sur {n} articles ===")
    print(f"  « actualite » (fourre-tout) : {100 * cats['actualite'] / n:.0f} %")
    print(f"  « national » (hors carte)   : {100 * lieux['national'] / n:.0f} %")
    print(f"  lieu_type renseigné         : {100 * (n - lieux['?']) / n:.0f} %")
    print(f"  tags par article            : {tags_total / n:.1f}")
    print(f"  résumés paraphrasant le titre : {100 * paraphrases / n:.0f} %")
    print("\nRépartition des catégories :")
    for cat, k in cats.most_common():
        print(f"  {cat:<14} {k}")
    return {"categories": dict(cats), "n": n}


def _arg_int(argv: list[str], nom: str, defaut: int) -> int:
    """Lit `--nom N` dans argv ; retourne `defaut` si absent ou illisible."""
    if nom in argv:
        i = argv.index(nom)
        if i + 1 < len(argv):
            try:
                return int(argv[i + 1])
            except ValueError:
                pass
    return defaut


def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "vapid-keys":
        generate_vapid_keys()
        return 0
    if cmd == "backfill-locations":
        asyncio.run(backfill_url_locations(dry_run="--dry-run" in argv))
        return 0
    if cmd == "check-feeds":
        asyncio.run(check_feeds(verbose="--verbose" in argv))
        return 0
    if cmd == "test-brief":
        asyncio.run(test_brief(hours=_arg_int(argv, "--hours", 24)))
        return 0
    if cmd == "test-extraction":
        asyncio.run(test_extraction(limit=_arg_int(argv, "--limit", 15)))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
