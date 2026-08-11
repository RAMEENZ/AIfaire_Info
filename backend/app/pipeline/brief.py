"""Génère un brief quotidien synthétique à partir des événements des dernières 24h."""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

_PARIS = ZoneInfo("Europe/Paris")

# Noms FR sans dépendre d'une locale système (souvent absente en conteneur slim).
_JOURS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MOIS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def _date_fr(dt: datetime) -> str:
    """Ex. 'dimanche 28 juin 2026' à partir d'un datetime (déjà en heure Paris)."""
    return f"{_JOURS_FR[dt.weekday()]} {dt.day} {_MOIS_FR[dt.month - 1]} {dt.year}"


def _periode_fr(hours: int) -> str:
    """Fenêtre couverte, en français lisible.

    Le prompt interpolait bruyamment les heures : le brief hebdomadaire
    annonçait « les dernières 168h », une formulation qu'aucun rédacteur
    n'emploie et qui n'aide pas le modèle à dater ses faits.
    """
    if hours <= 1:
        return "la dernière heure"
    if hours < 24:
        return f"les {hours} dernières heures"
    if hours == 24:
        return "les dernières 24 heures"
    jours = round(hours / 24)
    if jours == 7:
        return "les sept derniers jours"
    return f"les {jours} derniers jours"


# Titres de section attendus dans le texte généré. Le front (DailyBrief.tsx)
# reconnaît un titre par égalité EXACTE avec cette liste : un titre absent ou
# reformulé et la section se retrouve rendue comme un paragraphe ordinaire.
SECTION_TITLES = ("Alertes & vigilances", "Actualité générale", "En régions")


def _missing_sections(content: str) -> list[str]:
    """Titres de section absents du texte généré (chacun seul sur sa ligne)."""
    lignes = {ligne.strip() for ligne in content.splitlines()}
    return [t for t in SECTION_TITLES if t not in lignes]


def _truncate_words(text: str, limit: int) -> str:
    """Tronque la matière soumise au modèle sur une frontière de mot.

    La coupe brute à 200 caractères pouvait laisser un mot — ou un nombre —
    tranché en deux, et le modèle n'a alors aucun moyen de savoir si « 3 0 »
    valait 30 ou 3 000.
    """
    return truncate_clean(text, limit)


_VIGILANCE_CATS = frozenset({"meteo", "crue", "seisme"})


def _hazard_of(e: "Event") -> str | None:
    """Aléa d'une vigilance depuis son titre « Vigilance orange – Canicule – Drôme »
    → « Canicule ». None si l'événement n'est pas une vigilance regroupable."""
    if e.categorie not in _VIGILANCE_CATS:
        return None
    parts = re.split(r"\s[–-]\s", e.titre)
    if len(parts) >= 2 and parts[1].strip():
        return parts[1].strip().capitalize()
    return None


def _aggregate_alerts(alerts: "list[Event]", fmt) -> str:
    """Regroupe les vigilances par (aléa, niveau) en une ligne avec le compte et
    quelques départements ; les autres alertes restent listées individuellement."""
    groups: dict[tuple[str, str], list[str]] = {}
    order: list[tuple[str, str]] = []
    singles: list[str] = []
    for e in alerts:
        hazard = _hazard_of(e)
        if hazard is None:
            singles.append(fmt(e))
            continue
        niveau = {2: "orange", 3: "rouge"}.get(e.gravite, "jaune")
        key = (hazard, niveau)
        if key not in groups:
            groups[key] = []
            order.append(key)
        lieu = (e.lieu_nom or "").strip()
        if lieu and lieu.lower() != "national":
            groups[key].append(lieu)
    lines: list[str] = []
    for hazard, niveau in order:
        lieux = groups[(hazard, niveau)]
        n = len(lieux)
        if n:
            ex = ", ".join(lieux[:6]) + ("…" if n > 6 else "")
            lines.append(f"- {hazard} — vigilance {niveau} : {n} département{'s' if n > 1 else ''} ({ex})")
        else:
            lines.append(f"- {hazard} — vigilance {niveau}")
    lines.extend(singles)
    return "\n".join(lines)

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import DailyBrief, Event
from app.pipeline.sanitize import sanitize_markdown as _sanitize_brief
from app.pipeline.sanitize import truncate_clean

logger = logging.getLogger(__name__)


# ═══ Prompts ════════════════════════════════════════════════════════════════
# Construits par des fonctions plutôt qu'écrits en dur dans generate_daily_brief :
# ils deviennent testables hors ligne (tests/test_brief_prompt.py) et lisibles
# d'un bloc, ce qui compte pour un texte qu'on retouche souvent.

def build_brief_system_prompt(date_fr: str, periode: str, hebdo: bool = False) -> str:
    """Consigne de rédaction du brief.

    Écrit à partir des défauts observés sur les briefs réellement produits :
    faits répétés d'une section à l'autre, chiffres perdus en route, empilement
    sans hiérarchie, remplissage les jours creux et tics de langage
    (« il convient de noter », « la situation reste préoccupante »).
    """
    titres = "\n".join(SECTION_TITLES)
    prompt = f"""RÔLE
Tu es rédacteur en chef d'un service d'information géolocalisé couvrant la France.
Tu écris le brief que lit quelqu'un qui n'a pas suivi l'actualité et veut savoir,
en une minute, ce qui s'est passé et ce qui le concerne près de chez lui.

CADRE TEMPOREL
Nous sommes le {date_fr} (heure de Paris). Les données couvrent {periode}.
Tu peux situer les faits dans le temps avec les repères que les données
autorisent (aujourd'hui, ce week-end, depuis hier, en début de semaine).
N'invente aucune date, aucune heure, aucun chiffre absent des données.

STRUCTURE (impérative)
Trois sections, dans cet ordre. Chaque titre est seul sur sa ligne, copié
exactement ainsi, sans ponctuation ajoutée :
{titres}
Après chaque titre viennent un ou plusieurs paragraphes de prose, séparés par
une ligne vide.

FORME
- Texte brut uniquement : aucun dièse (#), astérisque (*), tiret bas (_),
  crochet [ ], puce, numérotation, ni ligne de séparation (---).
- Aucune étiquette ni code technique, aucun niveau de gravité chiffré.
- Phrases courtes, voix active. Une idée par phrase.
- Pas de formule d'ouverture ni de conclusion : la première phrase d'une
  section est déjà une information.

CE QUI FAIT UN BON BRIEF
1. Hiérarchie. Dans chaque section, le fait le plus important d'abord : celui
   qui touche le plus de personnes ou dont les conséquences sont les plus
   lourdes. Le reste suit par importance décroissante.
2. Concret. Reprends les chiffres, les lieux et les acteurs présents dans les
   données (nombre de départements, de blessés, d'emplois, montants, numéro de
   ligne, durée). Un fait privé de son chiffre perd l'essentiel de sa valeur.
3. Une seule fois. Un fait cité dans une section ne reparaît dans aucune autre,
   même reformulé. Les trois sections se complètent, elles ne se recouvrent pas.
4. Regroupe. Plusieurs faits de même nature (trois cambriolages, quatre
   fermetures de classes, cinq communes touchées) tiennent en une phrase avec
   leur total.
5. Densité plutôt que longueur. Si la matière est mince, écris court : deux
   phrases exactes valent mieux qu'un paragraphe délayé. Ne meuble jamais pour
   atteindre un nombre de phrases.

INTERDITS DE STYLE
- Formules creuses : « il convient de noter », « force est de constater »,
  « la situation reste préoccupante », « à noter également », « dans un tout
  autre registre », « en conclusion », « les autorités appellent à la
  vigilance » (sauf si les données le disent explicitement).
- Commentaire, opinion, pronostic, appel à l'action, question rhétorique.
- Adjectifs d'intensité non étayés : dramatique, spectaculaire, historique,
  sans précédent — sauf s'ils figurent dans les données.
- Nom de média, adresse web, mention de source : jamais.

CONTENU DES SECTIONS
1. Alertes & vigilances — risques en cours et incidents graves : météo, crues,
   séismes, incendies, accidents majeurs, coupures, pollution. Donne l'aléa,
   son niveau, son étendue géographique et, si les données le précisent,
   jusqu'à quand. 2 à 4 phrases. Sans alerte : une seule phrase le disant.
2. Actualité générale — les faits marquants hors alertes : justice, politique,
   économie, société, santé, transport, culture, sport. 3 à 5 phrases.
   Ne redis rien de la section 1.
3. En régions — 2 à 4 faits ancrés dans des territoires DIFFÉRENTS, chacun avec
   le nom du lieu. Varie les régions ; ne concentre pas tout sur l'Île-de-France
   ni sur une seule métropole. Ne redis rien des sections 1 et 2. Rien à
   signaler : une seule phrase le disant.

Langue : français. Ton neutre et factuel. N'écris rien qui ne se déduise pas
des données fournies : en cas de doute sur un détail, tais-le plutôt que de le
supposer."""
    if hebdo:
        prompt += """

BRIEF HEBDOMADAIRE
Ce brief couvre une semaine, pas une journée. Privilégie ce qui a duré, s'est
répété ou a évolué sur plusieurs jours plutôt que le fait isolé d'un matin.
Ouvre chaque section par le mouvement d'ensemble, puis illustre-le. Emploie le
mot « semaine » au moins une fois. N'écris pas « aujourd'hui » : les faits
listés s'étalent sur sept jours."""
    return prompt


def build_brief_user_prompt(
    alerts_text: str,
    news_text: str,
    regional_text: str,
    n_alerts: int,
    n_news: int,
    n_regional: int,
    periode: str,
) -> str:
    """Données brutes soumises au modèle, groupées par section de destination."""
    return (
        f"Voici la matière collectée sur {periode}. Chaque ligne est un fait "
        "vérifié ; le lieu, quand il est connu, figure entre parenthèses en tête.\n\n"
        f"ALERTES & VIGILANCES ({n_alerts}) :\n{alerts_text}\n\n"
        f"ACTUALITÉ GÉNÉRALE ({n_news}) :\n{news_text}\n\n"
        f"EN RÉGIONS ({n_regional}) :\n{regional_text}\n\n"
        "Rédige le brief. Tu n'as pas à tout citer : sélectionne ce qui compte, "
        "hiérarchise, et ne mentionne un même fait qu'une seule fois dans "
        "l'ensemble du texte. Titres en clair, prose simple, aucun symbole de "
        "formatage."
    )


# Tics de langage que le prompt interdit. Les repérer après coup dit si la
# consigne a porté — un prompt ne se juge que sur ce qu'il produit.
_FORMULES_CREUSES = (
    "il convient de noter", "force est de constater", "il est à noter",
    "la situation reste préoccupante", "à noter également", "en conclusion",
    "dans un tout autre registre", "il faut rappeler que", "on notera",
    "reste à savoir", "l'avenir nous dira", "affaire à suivre",
)
_MOT_RE = re.compile(r"[a-zà-öø-ÿ]{5,}", re.I)
# Mots trop fréquents pour signaler quoi que ce soit d'un recoupement.
_MOTS_VIDES = frozenset({
    "après", "avant", "aussi", "entre", "depuis", "encore", "selon", "contre",
    "pendant", "plusieurs", "notamment", "toujours", "jusqu", "cette", "leurs",
})


def split_sections(content: str) -> dict[str, str]:
    """Découpe un brief en {titre de section: corps}. Sections absentes omises."""
    sections: dict[str, list[str]] = {}
    courante: str | None = None
    for ligne in content.splitlines():
        nu = ligne.strip()
        if nu in SECTION_TITLES:
            courante = nu
            sections[courante] = []
        elif courante and nu:
            sections[courante].append(nu)
    return {titre: "\n".join(corps) for titre, corps in sections.items()}


def audit_brief(content: str) -> list[str]:
    """Défauts détectables sans LLM dans un brief généré.

    Sert au diagnostic (`python -m app.maintenance test-brief`) : plutôt que de
    relire à l'œil, on liste ce que le prompt n'a pas réussi à empêcher.
    Retourne une liste de constats en clair, vide si le brief est propre.
    """
    constats: list[str] = []

    for titre in _missing_sections(content):
        constats.append(f"section absente ou mal orthographiée : « {titre} »")

    bas = content.lower()
    for formule in _FORMULES_CREUSES:
        if formule in bas:
            constats.append(f"formule creuse : « {formule} »")

    for symbole, nom in (("#", "dièse"), ("*", "astérisque"), ("[", "crochet")):
        if symbole in content:
            constats.append(f"formatage résiduel : {nom} ({symbole})")

    # Recoupement entre sections : le prompt exige qu'un fait ne soit cité
    # qu'une fois. Deux sections qui partagent beaucoup de mots rares racontent
    # probablement la même chose.
    sections = split_sections(content)
    mots = {
        titre: {m.lower() for m in _MOT_RE.findall(corps)} - _MOTS_VIDES
        for titre, corps in sections.items()
    }
    titres = list(mots)
    for i, a in enumerate(titres):
        for b in titres[i + 1:]:
            communs = mots[a] & mots[b]
            plus_petit = min(len(mots[a]), len(mots[b])) or 1
            if len(communs) / plus_petit > 0.35:
                constats.append(
                    f"recoupement « {a} » / « {b} » : "
                    + ", ".join(sorted(communs)[:6])
                )

    for titre, corps in sections.items():
        if not corps.strip():
            constats.append(f"section vide : « {titre} »")

    return constats


async def _generate_text(system_prompt: str, user_prompt: str) -> Optional[str]:
    """Un appel à Mistral, nettoyé du Markdown résiduel. None si l'appel échoue."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.MISTRAL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.MISTRAL_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    # Basse température : un brief se juge sur l'exactitude, pas
                    # sur la variété de formulation.
                    "temperature": 0.25,
                    "max_tokens": 1000,
                },
            )
            resp.raise_for_status()
            return _sanitize_brief(resp.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        logger.error("Brief generation failed: %s", exc)
        return None


async def build_brief_prompts(hours: int = 24) -> Optional[tuple[str, str, int]]:
    """Rassemble la matière et construit les deux prompts du brief.

    Séparé de l'écriture en base pour qu'on puisse essayer un prompt sur les
    données réelles sans publier le résultat :
    `python -m app.maintenance test-brief`.

    Retourne (prompt système, prompt utilisateur, nombre d'événements), ou None
    si la fenêtre ne contient aucun événement.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    now_paris = now.astimezone(_PARIS)

    async with AsyncSessionLocal() as session:
        # Alertes : événements à gravité élevée (vigilances, incidents…).
        alerts_res = await session.execute(
            select(Event)
            .where(Event.date_publication >= since, Event.gravite >= 2)
            .order_by(Event.gravite.desc(), Event.date_publication.desc())
            .limit(20)
        )
        alerts = list(alerts_res.scalars().all())

        # Actualité générale : les plus récents, EN EXCLUANT les catégories de
        # bulletins d'alerte (météo/crue/séisme). Sans cette exclusion, les
        # vigilances Météo-France — très nombreuses et horodatées en fin de
        # journée — monopolisent aussi ce volet par récence, et l'« actualité »
        # se résume encore à de la météo. On laisse ainsi remonter la presse
        # (société, politique, faits divers, transport, santé, économie…).
        recent_res = await session.execute(
            select(Event)
            .where(
                Event.date_publication >= since,
                Event.categorie.notin_(["meteo", "crue", "seisme"]),
            )
            .order_by(Event.date_publication.desc())
            .limit(60)
        )
        recent = list(recent_res.scalars().all())

        # Actualité régionale : événements localisés (hors national), pour donner
        # au brief un ancrage géographique au lieu d'un tropisme parisien/national.
        # On exclut là encore les bulletins d'alerte météo.
        regional_res = await session.execute(
            select(Event)
            .where(
                Event.date_publication >= since,
                Event.categorie.notin_(["meteo", "crue", "seisme"]),
                Event.lieu_niveau.in_(["commune", "departement", "region"]),
                Event.lieu_nom.isnot(None),
            )
            .order_by(Event.date_publication.desc())
            .limit(80)
        )
        regional_all = list(regional_res.scalars().all())

    # Actualité = récents hors alertes déjà listées. Le prompt demande au modèle
    # de hiérarchiser (le plus important d'abord) : encore faut-il qu'il puisse.
    # Trié par seule récence, un fait divers anodin publié à 18 h passait devant
    # un plan social publié le matin. On remonte donc la gravité AVANT de couper
    # à 25, sinon les faits notables les plus anciens tombaient hors fenêtre.
    alert_ids = {e.id for e in alerts}
    news = sorted(
        (e for e in recent if e.id not in alert_ids),
        key=lambda e: (-(e.gravite or 0), -e.date_publication.timestamp()),
    )[:25]

    # En régions = localisés, dédupliqués à un événement par lieu pour maximiser
    # la diversité géographique, en excluant ce qui est déjà cité ailleurs.
    cited_ids = alert_ids | {e.id for e in news}
    regional: list[Event] = []
    seen_lieux: set[str] = set()
    for e in regional_all:
        if e.id in cited_ids:
            continue
        lieu_key = (e.lieu_nom or "").strip().lower()
        if not lieu_key or lieu_key in seen_lieux or lieu_key == "national":
            continue
        seen_lieux.add(lieu_key)
        regional.append(e)
        if len(regional) >= 8:
            break

    events = alerts + news + regional
    if not events:
        logger.info("Brief: no events in last %dh, skipping", hours)
        return None

    def _fmt(e: Event) -> str:
        # Données fournies au modèle SANS code ni crochet, pour qu'il n'en
        # reproduise pas dans le texte final (cf. règles de forme du prompt).
        loc = f"({e.lieu_nom}) " if e.lieu_nom and e.lieu_nom != "national" else ""
        resume = e.resume_ia or e.titre
        return f"- {loc}{_truncate_words(resume, 220)}"

    # Les vigilances météo/crue/séisme sont très nombreuses et quasi identiques
    # d'un jour à l'autre (ex. canicule orange sur 30 départements). Listées une
    # par une, elles saturent le contexte et donnent un brief « toujours pareil ».
    # On les regroupe par aléa+niveau en une ligne synthétique, ce qui libère de
    # la place pour l'actualité qui, elle, change.
    alerts_text = _aggregate_alerts(alerts, _fmt) or "(aucune alerte majeure)"
    news_text = "\n".join(_fmt(e) for e in news) or "(rien de notable)"
    regional_text = "\n".join(_fmt(e) for e in regional) or "(rien de notable en régions)"
    event_count = len(events)

    periode = _periode_fr(hours)
    hebdo = hours >= 72

    system_prompt = build_brief_system_prompt(_date_fr(now_paris), periode, hebdo)
    user_prompt = build_brief_user_prompt(
        alerts_text, news_text, regional_text,
        len(alerts), len(news), len(regional), periode,
    )
    return system_prompt, user_prompt, event_count


async def generate_daily_brief(hours: int = 24) -> Optional[str]:
    """Génère et sauvegarde le brief. Retourne le texte ou None si échec.

    `hours >= 72` marque le brief comme hebdomadaire (colonne `is_weekly`).
    """
    now = datetime.now(timezone.utc)
    today = now.astimezone(_PARIS).replace(hour=0, minute=0, second=0, microsecond=0)
    # Même seuil que build_brief_prompts : au-delà de trois jours, le brief
    # couvre une semaine et non une journée.
    hebdo = hours >= 72

    built = await build_brief_prompts(hours)
    if built is None:
        return None
    system_prompt, user_prompt, event_count = built

    if not settings.MISTRAL_API_KEY:
        logger.warning("Brief: MISTRAL_API_KEY not set, cannot generate brief")
        return None

    content = await _generate_text(system_prompt, user_prompt)
    if not content:
        # Réponse vide (ou vidée par le nettoyage Markdown) : ne pas écraser le
        # brief de la veille par une page blanche.
        logger.error("Brief: réponse vide du modèle, brief non enregistré")
        return None

    # Le front reconnaît les sections par égalité exacte du titre : si le modèle
    # en a oublié un (ou l'a reformulé), la section se fond dans le corps du
    # texte. Un rappel ciblé suffit presque toujours ; on ne réessaie qu'une fois.
    manquants = _missing_sections(content)
    if manquants:
        logger.warning("Brief: titres de section manquants %s, nouvel essai", manquants)
        retry = await _generate_text(
            system_prompt,
            user_prompt
            + "\n\nRAPPEL : le texte DOIT contenir les trois lignes de titre "
            + ", ".join(f"« {t} »" for t in SECTION_TITLES)
            + ", chacune seule sur sa ligne, orthographiée à l'identique.",
        )
        if retry is not None and not _missing_sections(retry):
            content = retry

    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(DailyBrief).where(DailyBrief.date >= today).limit(1)
        )
        existing_brief = existing.scalar_one_or_none()

        if existing_brief:
            existing_brief.content = content
            existing_brief.event_count = event_count
            existing_brief.generated_at = now
            existing_brief.is_weekly = hebdo
        else:
            session.add(DailyBrief(
                date=today,
                content=content,
                event_count=event_count,
                generated_at=now,
                is_weekly=hebdo,
            ))

        await session.commit()

    logger.info("Brief generated: %d events → %d chars", event_count, len(content))
    return content


async def generate_weekly_brief() -> Optional[str]:
    """Génère le brief de la semaine (lundi matin)."""
    now = datetime.now(timezone.utc)
    monday = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(DailyBrief).where(DailyBrief.date >= monday).limit(1)
        )
        # Ne pas régénérer si c'est déjà fait aujourd'hui. Le marqueur est lu en
        # base : la détection par la présence du mot « semaine » dans le texte
        # sautait la génération dès qu'un brief quotidien employait ce mot.
        existing_brief = existing.scalar_one_or_none()
        if existing_brief and existing_brief.is_weekly:
            logger.info("Weekly brief already generated today")
            return existing_brief.content

    return await generate_daily_brief(hours=168)


async def get_latest_brief() -> Optional[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DailyBrief).order_by(DailyBrief.date.desc()).limit(1)
        )
        brief = result.scalar_one_or_none()
        if brief is None:
            return None
        return {
            "date": brief.date.isoformat(),
            "content": brief.content,
            "event_count": brief.event_count,
            "generated_at": brief.generated_at.isoformat(),
            "is_weekly": brief.is_weekly,
        }
