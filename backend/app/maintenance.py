"""Opérations de maintenance ponctuelles, exécutables dans le conteneur :

    docker compose exec backend python -m app.maintenance backfill-locations [--dry-run]
    docker compose exec backend python -m app.maintenance check-feeds [--verbose]
    docker compose exec backend python -m app.maintenance vapid-keys
    docker compose exec backend python -m app.maintenance test-brief [--hours 24]
    docker compose exec backend python -m app.maintenance test-extraction [--limit 15]
    docker compose exec backend python -m app.maintenance clean-extractions [--dry-run]
    docker compose exec backend python -m app.maintenance audit-commercial [--limit 400 | --live]

Les deux commandes `test-*` servent à juger les prompts sur les données
réelles : elles appellent le modèle mais n'écrivent RIEN en base.
`clean-extractions` fait l'inverse : aucun appel au modèle, mais elle répare
les extractions déjà stockées (tags redondants, résumés coupés).

Placé dans le package `app` (et non dans scripts/) car l'image Docker ne copie
que `app/` — un script sous scripts/ ne serait pas présent en production.
"""
import asyncio
import sys
import textwrap
from collections import Counter
from typing import Optional

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Event

# Longueur à laquelle l'ancienne troncature `resume_ia[:500]` coupait, au
# caractère près. Sert à distinguer un résumé tranché d'un résumé simplement
# privé de son point final (voir clean_extractions).
_LIMITE_RESUME_HISTORIQUE = 500
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
    system_prompt, user_prompt, repartition = built

    print(f"=== Matière : {sum(repartition.values())} événements sur {hours} h ===")
    # Détail par section : un brief creux « En régions » se lit tout autrement
    # selon qu'on lui a fourni 8 événements localisés ou aucun.
    for titre, n in repartition.items():
        print(f"  {titre} : {n}" + ("   ← aucune matière fournie" if n == 0 else ""))
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
    des résumés. Ne modifie aucun événement existant.

    Le pipeline complet (`maybe_extract`) est rejoué, pas seulement l'appel au
    modèle : le repli par URL (code INSEE, code postal, département), les
    surcharges par source et le raccourci `lieu_type` récupèrent une partie des
    articles que le modèle rend « national ». Mesurer le modèle seul donnait un
    taux de non-localisation nettement plus sombre que la réalité affichée sur
    la carte — le premier relevé du 03/08/2026 annonçait ainsi 33 % de
    « national » là où le pipeline en localise une partie.
    """
    from app.config import settings
    from app.pipeline.extractor import _looks_french, extract_article, maybe_extract

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
    tags_total = paraphrases = inacheves = sans_tags = 0
    national_modele = national_pipeline = recuperes = sans_lieu_type = 0
    hors_llm = 0

    for e in rows:
        # Le pipeline n'appelle le modèle que si l'article lui paraît français ;
        # sinon il retombe sur l'extracteur par règles, bien plus grossier.
        # Comparer une sortie du modèle à un résultat obtenu par règles, sans le
        # dire, rendait ce diagnostic incompréhensible (relevé du 03/08/2026).
        via_llm = _looks_french(e.titre, e.resume_ia or "")
        if not via_llm:
            hors_llm += 1
        # 1) Le modèle seul — ce que le prompt produit.
        brut = await extract_article(e.titre, e.resume_ia or "", None)
        # 2) Le pipeline complet — ce qui finit réellement sur la carte.
        final = await maybe_extract({
            "source": e.source,
            "titre": e.titre,
            "description": e.resume_ia or "",
            "source_url": e.source_url,
            "auteur": e.auteur,
        })

        resume = brut["resume_ia"]
        cats[brut["categorie"]] += 1
        tags_total += len(brut["tags"])
        if not brut["tags"]:
            sans_tags += 1
        if not brut.get("lieu_type"):
            sans_lieu_type += 1

        modele_national = brut["lieu_nom"] == "national"
        final_national = (final.get("lieu_nom") or "national") == "national"
        national_modele += modele_national
        national_pipeline += final_national
        if modele_national and not final_national:
            recuperes += 1

        mots_titre = set(e.titre.lower().split())
        mots_resume = set(resume.lower().split())
        if mots_titre and len(mots_titre & mots_resume) / len(mots_titre) > 0.8:
            paraphrases += 1
        if resume and resume[-1] not in ".!?…»\"":
            inacheves += 1

        # Titre et résumé affichés ENTIERS : une coupe d'affichage ferait passer
        # un résumé sain pour un résumé tronqué (elle l'a déjà fait).
        print(f"\n— {e.titre}")
        lieu_final = final.get("lieu_nom") or "national"
        rattrape = "  ← récupéré par le pipeline" if modele_national and not final_national else ""
        print(f"  catégorie {brut['categorie']:<12} lieu {lieu_final} "
              f"({brut.get('lieu_type') or 'type non fourni'})  gravité {brut['gravite']}{rattrape}")
        if not via_llm:
            print("            ⚠ jugé non français : le pipeline n'appelle PAS le modèle "
                  "sur cet article, il retombe sur les règles")
        elif lieu_final != brut["lieu_nom"]:
            print(f"            (le modèle disait « {brut['lieu_nom']} »)")
        print(f"  tags      {', '.join(brut['tags']) or '(aucun)'}")
        print(textwrap.fill(resume, width=96,
                            initial_indent="  résumé    ", subsequent_indent="            "))

    n = len(rows)

    def pct(k: int) -> str:
        return f"{100 * k / n:.0f} %"

    print(f"\n=== Bilan sur {n} articles ===")
    print(f"  écartés du modèle (jugés non FR): {pct(hors_llm)}"
          + ("   ← extraction par règles, bien plus grossière" if hors_llm else ""))
    print(f"  « actualite » (fourre-tout)     : {pct(cats['actualite'])}")
    print(f"  « national » selon le modèle    : {pct(national_modele)}")
    print(f"  « national » APRÈS pipeline     : {pct(national_pipeline)}"
          f"   ← ce qui compte : hors carte")
    print(f"  récupérés par le repli URL      : {recuperes}")
    print(f"  lieu_type renseigné             : {pct(n - sans_lieu_type)}")
    print(f"  tags par article                : {tags_total / n:.1f}")
    print(f"  articles sans aucun tag         : {pct(sans_tags)}")
    print(f"  résumés paraphrasant le titre   : {pct(paraphrases)}")
    print(f"  résumés coupés en cours         : {pct(inacheves)}")
    print("\nRépartition des catégories :")
    for cat, k in cats.most_common():
        print(f"  {cat:<14} {k}")
    return {
        "categories": dict(cats), "n": n, "hors_llm": hors_llm,
        "national_modele": national_modele, "national_pipeline": national_pipeline,
    }


async def clean_extractions(dry_run: bool = False) -> dict:
    """Répare les extractions déjà en base, sans rappeler le modèle.

    Deux défauts se sont accumulés avant leur correction dans le pipeline :
    des résumés coupés au caractère près (« La pénurie nationale att ») et des
    tags qui répètent le lieu ou la catégorie. Les deux sont réparables de
    façon déterministe à partir de ce qui est stocké — une ré-extraction
    coûterait un appel LLM par article et ne serait pas reproductible.
    """
    from app.pipeline.extractor import _clean_tags
    from app.pipeline.sanitize import last_complete_sentence

    tags_nettoyes = resumes_repares = resumes_irreparables = points_ajoutes = 0

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(Event))).scalars().all()
        print(f"{len(rows)} événements à examiner…")

        for e in rows:
            propres = _clean_tags(list(e.tags or []), e.lieu_nom or "", e.categorie or "")
            if propres != list(e.tags or []):
                tags_nettoyes += 1
                if not dry_run:
                    e.tags = propres

            resume = (e.resume_ia or "").strip()
            if not resume or resume[-1] in ".!?…»\"":
                continue

            # Absence de ponctuation finale : deux causes très différentes, qu'il
            # serait trompeur de traiter pareil. Ce qui les sépare n'est pas la
            # longueur mais la STRUCTURE — un texte tranché garde une phrase
            # entière suivie d'un moignon, un texte simplement mal ponctué n'a
            # qu'une seule phrase, complète.
            phrase_entiere = last_complete_sentence(resume)

            if phrase_entiere and len(phrase_entiere) >= len(resume) // 2:
                # « … cet été. La pénurie nationale att » → on jette le moignon.
                resumes_repares += 1
                if not dry_run:
                    e.resume_ia = phrase_entiere
            elif phrase_entiere or len(resume) >= _LIMITE_RESUME_HISTORIQUE - 10:
                # Soit la réparation ôterait plus de la moitié du texte, soit le
                # résumé bute contre l'ancienne limite sans contenir une seule
                # phrase complète : rien à sauver proprement, on n'y touche pas.
                resumes_irreparables += 1
            else:
                # « Trois blessés dans une collision à Colmar » → une phrase
                # entière à qui il ne manque que son point. La tronquer
                # détruirait de l'information pour corriger une ponctuation.
                points_ajoutes += 1
                if not dry_run:
                    e.resume_ia = resume + "."

        if not dry_run:
            await session.commit()

    mode = "SIMULATION — rien écrit" if dry_run else "appliqué"
    print(f"\n[{mode}]")
    print(f"  {tags_nettoyes} listes de tags élaguées (lieu, catégorie, doublons)")
    print(f"  {resumes_repares} résumés tranchés ramenés à leur dernière phrase complète")
    print(f"  {resumes_irreparables} résumés tranchés laissés tels quels "
          f"(la réparation en aurait ôté plus de la moitié)")
    print(f"  {points_ajoutes} résumés entiers auxquels il ne manquait que le point final")
    return {
        "tags_nettoyes": tags_nettoyes,
        "resumes_repares": resumes_repares,
        "resumes_irreparables": resumes_irreparables,
        "points_ajoutes": points_ajoutes,
        "dry_run": dry_run,
    }


async def audit_commercial_live() -> dict:
    """Mesure la présence de contenus marchands sur les flux EN DIRECT.

    Les événements en base ne répondent pas à la question : ils ont déjà subi le
    filtre, la déduplication ET le plafond de 120 par run — soit moins de 2 %
    des ~7 900 titres qu'un cycle collecte. Pour savoir si le filtre est trop
    strict ou s'il n'y a réellement rien à écarter, il faut regarder la matière
    brute.

    Collecte les flux (aucun appel au modèle, aucune écriture) avec le filtre et
    le plafond neutralisés, puis compte par source.
    """
    from app.config import settings as _s
    from app.connectors.presse_rss import PresseRSSConnector
    from app.pipeline.commercial import is_commercial

    filtre_initial = _s.FILTER_COMMERCIAL_CONTENT
    plafond_initial = _s.MAX_PRESSE_ARTICLES
    _s.FILTER_COMMERCIAL_CONTENT = False
    _s.MAX_PRESSE_ARTICLES = 100_000
    try:
        print("Collecte des flux en cours (une à deux minutes)…")
        items = await PresseRSSConnector().run()
    finally:
        _s.FILTER_COMMERCIAL_CONTENT = filtre_initial
        _s.MAX_PRESSE_ARTICLES = plafond_initial

    if not items:
        print("Aucun article collecté — flux injoignables ?")
        return {}

    par_source: Counter = Counter()
    total_par_source: Counter = Counter()
    exemples: list[str] = []
    for it in items:
        source = (it.get("auteur") or "source inconnue").strip()
        total_par_source[source] += 1
        if is_commercial(it.get("titre", ""), it.get("description", "")):
            par_source[source] += 1
            if len(exemples) < 25:
                exemples.append(f"[{source[:22]}] {it.get('titre', '')[:100]}")

    marchands = sum(par_source.values())
    n = len(items)
    print(f"\n=== {marchands}/{n} titres marchands ({100 * marchands / n:.2f} %) ===\n")
    if not marchands:
        print(
            "Aucun contenu marchand détecté sur la matière brute.\n"
            "Le « 0 écartés » de l'ingestion est donc exact : ces flux n'en\n"
            "publient pas, ou pas en ce moment."
        )
        return {"total": n, "marchands": 0}

    print(f"{'Source':<38} {'marchands':>10} {'total':>7} {'part':>6}")
    for source, k in par_source.most_common(20):
        total = total_par_source[source]
        print(f"{source[:38]:<38} {k:>10} {total:>7} {100 * k / total:>5.1f} %")
    print("\nExemples :")
    for ex in exemples:
        print(f"  {ex}")
    return {"total": n, "marchands": marchands, "par_source": dict(par_source)}


async def audit_commercial(limit: int = 400) -> dict:
    """Compte les articles marchands par flux, sur les événements en base.

    Attention : les événements stockés ont déjà subi le filtre, la déduplication
    et le plafond de 120 par run. Pour mesurer la vraie prévalence sur la
    matière brute, utiliser `audit-commercial --live`.

    Aucun appel au modèle, aucune écriture.
    """
    from app.pipeline.commercial import is_commercial

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

    par_auteur: Counter = Counter()
    total_par_auteur: Counter = Counter()
    exemples: dict[str, list[str]] = {}
    for e in rows:
        auteur = (e.auteur or "source inconnue").strip()
        total_par_auteur[auteur] += 1
        if is_commercial(e.titre, e.resume_ia or ""):
            par_auteur[auteur] += 1
            exemples.setdefault(auteur, []).append(e.titre)

    marchands = sum(par_auteur.values())
    n = len(rows)
    print(f"=== {marchands}/{n} articles marchands ({100 * marchands / n:.0f} %) ===\n")
    if not marchands:
        print("Aucun contenu marchand détecté sur cet échantillon.")
        return {"total": n, "marchands": 0}

    print(f"{'Source':<38} {'marchands':>10} {'total':>7} {'part':>6}")
    for auteur, k in par_auteur.most_common():
        total = total_par_auteur[auteur]
        print(f"{auteur[:38]:<38} {k:>10} {total:>7} {100 * k / total:>5.0f} %")

    print("\nExemples :")
    for auteur, titres in list(exemples.items())[:5]:
        for titre in titres[:2]:
            print(f"  [{auteur[:24]}] {titre[:96]}")

    print(
        "\nUne source dont la part dépasse ~30 % mérite d'être retirée de "
        "presse_rss plutôt que filtrée article par article."
    )
    return {"total": n, "marchands": marchands, "par_source": dict(par_auteur)}


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
    if cmd == "audit-commercial":
        if "--live" in argv:
            asyncio.run(audit_commercial_live())
        else:
            asyncio.run(audit_commercial(limit=_arg_int(argv, "--limit", 400)))
        return 0
    if cmd == "clean-extractions":
        asyncio.run(clean_extractions(dry_run="--dry-run" in argv))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
