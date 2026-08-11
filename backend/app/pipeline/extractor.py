import asyncio
import hashlib
import html as _html
import json
import logging
import re
import unicodedata
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_PARIS = ZoneInfo("Europe/Paris")

import httpx

from app.categories import (
    CATEGORIES_PLAIN,
    CATEGORIES_QUOTED,
    CATEGORY_SET,
    DEFAULT_CATEGORY,
)
from app.config import settings
from app.pipeline.geocoder import geocode
from app.pipeline.mistral_client import chat as mistral_chat
from app.pipeline.sanitize import sanitize_markdown, truncate_clean

logger = logging.getLogger(__name__)

_extract_cache: dict[str, dict[str, Any]] = {}
_MAX_EXTRACT_CACHE = 2048

_OLLAMA_SEMAPHORE = asyncio.Semaphore(2)
_MISTRAL_SEMAPHORE = asyncio.Semaphore(settings.MISTRAL_MAX_CONCURRENCY)


def _cache_key(titre: str, description: str) -> str:
    return hashlib.sha256((titre + (description or "")[:200]).encode()).hexdigest()


def _cache_put(key: str, value: dict[str, Any]) -> None:
    # Demi-éviction (comme geocoder) plutôt que clear() total : évite que tout
    # le cache devienne froid d'un coup, ce qui provoquerait un afflux d'appels
    # LLM payants juste après le franchissement de la capacité.
    if len(_extract_cache) >= _MAX_EXTRACT_CACHE:
        keys = list(_extract_cache)
        for k in keys[: len(keys) // 2]:
            del _extract_cache[k]
    _extract_cache[key] = value

SYSTEM_PROMPT = """\
Tu extrais des données structurées d'articles de presse française pour une carte d'actualité géolocalisée.
Tu ne rédiges pas : tu remplis des champs à partir du seul texte fourni.

RÈGLE ABSOLUE : n'invente rien. Si une information n'est pas dans le texte, utilise la valeur de repli indiquée.

═══ lieu_nom ═══
Le lieu français LE PLUS PRÉCIS explicitement nommé dans l'article.
Ordre de préférence : commune > département > région > "national".
- Une commune est citée → donne la commune, jamais sa région ("Quimper", pas "Bretagne").
- Plusieurs communes → celle où se produit le fait principal.
- Aucun lieu français nommé, fait de portée nationale, ou événement à l'étranger → "national".
- Un pays ou une ville étrangère ne va JAMAIS dans ce champ ; dans ce cas, "national".
- Attention aux faux lieux : noms de clubs ("Paris FC", "AS Monaco"), de journaux
  ("Nice-Matin", "La Provence"), d'entreprises. Ce ne sont pas des lieux d'événement.
- Écris le nom seul, sans article ni département entre parenthèses : "Bar-le-Duc", pas "Bar-le-Duc (55)".

═══ lieu_type ═══
Nature du lieu ci-dessus : "commune", "departement", "region" ou "national".
Sert à lever les homonymies (Vienne la ville ≠ la Vienne le département).
N'annonce "commune" que si tu es sûr du nom exact : une commune que tu n'aurais
pas su écrire correctement vaut mieux déclarée "national" qu'inventée.

═══ categorie ═══
Une seule valeur parmi : __CATEGORIES_QUOTED__

N'utilise "actualite" QU'EN DERNIER RECOURS, si aucune autre catégorie ne convient.
La plupart des articles ont une catégorie précise — cherche-la avant de renoncer.

Départage des cas fréquents :
- Fait divers, justice, police, procès, délinquance → "ordre_public"
- Incendie de forêt ou d'habitation → "incendie" (même si l'origine est criminelle)
- Accident de la route, travaux, trafic, train, avion → "transport"
- Vie municipale, élections, préfecture, budget public → "politique"
- Entreprise, commerce, agriculture, immobilier → "economie"
- Hôpital, épidémie, rappel de produit, médecine, alerte sanitaire → "sante"
- Festival, musée, patrimoine, spectacle, sport de loisir associatif → "culture"
- Compétition sportive, club, match, championnat → "sport"

Classe d'après le SUJET de l'article, pas d'après le secteur de la personne dont
il parle. Deux pièges récurrents :
- Emploi, recrutement, pénurie de main-d'œuvre, salaires, plan social → toujours
  "economie", même quand le métier concerné relève de la santé, du sport ou de
  l'enseignement. Recruter des infirmiers ou des maîtres-nageurs est un sujet
  d'emploi, pas un sujet médical ou sportif.
- Un texte de loi, une délibération, un budget public → "politique", même quand
  il porte sur l'industrie, la santé ou les transports.

═══ resume_ia ═══
1 à 2 phrases factuelles, en français, qui répondent à : quoi, où, qui, avec quelle conséquence.
- N'écris PAS une paraphrase du titre : apporte l'information que le titre ne donne pas
  (chiffres, circonstances, suites).
  Épreuve à passer : si ton résumé, lu seul, n'apprend rien de plus que le titre, il est raté.
  Recommence en cherchant dans le texte un chiffre, une date, une cause ou une conséquence.
- Ne commence pas en recopiant les mots du titre.
- Rapporte LE FAIT, jamais le texte qui le rapporte. N'écris ni "l'article",
  ni "le papier", ni "l'auteur", ni "selon ce reportage" : le lecteur veut
  l'information, pas un commentaire sur sa mise en forme.
- Aucune formule d'accroche ni de teasing ("on vous explique", "voici pourquoi").
- Termine par une phrase complète, point final compris. Mieux vaut une phrase entière
  que deux dont la seconde s'arrête au milieu.
- Si le texte est trop pauvre pour un vrai résumé, reformule sobrement le fait principal
  en une phrase, et arrête-toi là — n'étire pas, ne suppose pas.

═══ gravite ═══
Mesure l'impact réel sur la population, pas l'émotion suscitée.
- 3 = URGENCE : crise nationale touchant toute la population (attentat majeur, catastrophe
  nationale, pandémie déclarée). TRÈS RARE — un fait divers, même tragique, n'est jamais 3.
- 2 = ALERTE : alerte officielle d'une autorité (Météo-France orange ou rouge, ANSM,
  Vigicrues 3-4, arrêté préfectoral), ou événement causant des victimes multiples.
- 1 = VIGILANCE : vigilance météo jaune, risque annoncé sans victime, perturbation
  notable des transports, fermeture temporaire.
- 0 = INFORMATION : actualité courante. La grande majorité des articles = 0.
En cas d'hésitation entre deux niveaux, choisis le plus bas.

═══ tags ═══
3 à 5 mots-clés thématiques, en minuscules, sans accent superflu ni doublon.
- Ne répète NI lieu_nom NI categorie, ni aucune de leurs variantes : sur un article
  situé à Leyme, "leyme" est un tag inutile — le lieu est déjà un champ.
- Interdits car sans valeur de filtrage : "france", "actualité", "info", "news", "société".
- Préfère le concret : "grève", "canicule", "rappel produit", "conseil municipal".
- Un bon tag est celui qu'un lecteur taperait pour retrouver ce type d'article.

═══ FORMAT ═══
Réponds UNIQUEMENT par un objet JSON valide, sans texte avant ni après :
{"lieu_nom": "...", "lieu_type": "...", "categorie": "...", "resume_ia": "...", "gravite": 0, "tags": ["...", "..."]}

Exemples :

Article : "Incendie dans un entrepôt de Vénissieux : 40 pompiers mobilisés, aucun blessé"
{"lieu_nom": "Vénissieux", "lieu_type": "commune", "categorie": "incendie", "resume_ia": "Un entrepôt de Vénissieux a pris feu dans la nuit, mobilisant 40 pompiers. Le sinistre n'a fait aucun blessé.", "gravite": 1, "tags": ["entrepôt", "pompiers", "sinistre"]}

Article : "Le conseil municipal vote le budget 2027 à l'unanimité"
{"lieu_nom": "national", "lieu_type": "national", "categorie": "politique", "resume_ia": "Le conseil municipal a adopté son budget 2027 à l'unanimité.", "gravite": 0, "tags": ["conseil municipal", "budget", "vote"]}

Article : "Guerre en Ukraine : nouvelle frappe sur Kharkiv"
{"lieu_nom": "national", "lieu_type": "national", "categorie": "actualite", "resume_ia": "Une nouvelle frappe a visé la ville de Kharkiv, en Ukraine.", "gravite": 0, "tags": ["ukraine", "frappe", "conflit"]}

Article : "Le recrutement de maîtres-nageurs sous tension dans le Tarn-et-Garonne"
{"lieu_nom": "Tarn-et-Garonne", "lieu_type": "departement", "categorie": "economie", "resume_ia": "Le département peine à recruter des maîtres-nageurs sauveteurs pour surveiller ses bassins cet été. La pénurie de diplômés touche l'ensemble du pays.", "gravite": 0, "tags": ["recrutement", "pénurie", "piscine"]}
"""

# Prompt allégé pour les petits modèles locaux (qwen2.5:1.5b, phi3:mini…).
# Plus direct, moins de prose — les modèles <3B suivent mieux les instructions
# courtes avec un exemple concret plutôt qu'une longue description.
SYSTEM_PROMPT_SMALL = """\
Extrait 6 champs d'un article d'actualité française. Réponds UNIQUEMENT en JSON, sans texte avant ni après.
N'invente rien : si l'info manque, mets la valeur de repli.

Champs :
- lieu_nom : le lieu français LE PLUS PRÉCIS cité (commune de préférence, ex: "Quimper" et non "Bretagne").
  "national" si aucun lieu français, si portée nationale, ou si l'événement est à l'étranger.
  Jamais un pays étranger. Attention : "Paris FC", "Nice-Matin" sont des noms de club/journal, pas des lieux.
- lieu_type : "commune", "departement", "region" ou "national".
- categorie : UN SEUL parmi : __CATEGORIES_PLAIN__
  N'utilise "actualite" que si aucune autre ne convient.
  Repères : fait divers/justice → ordre_public ; route/train → transport ; mairie/élection/loi → politique ;
  entreprise/emploi/recrutement → economie ; feu → incendie ; festival/musée → culture ; match/club → sport.
  Classe d'après le sujet, pas d'après le métier : recruter des infirmiers ou des
  maîtres-nageurs est un sujet d'emploi (economie), pas de santé ni de sport.
- resume_ia : 1 phrase factuelle qui apporte plus que le titre (chiffres, circonstances).
  Si elle ne fait que redire le titre, elle est inutile. Termine-la par un point.
- gravite : 0=info (la plupart), 1=vigilance, 2=alerte officielle, 3=urgence nationale (très rare).
  En cas de doute, prends le plus bas.
- tags : 3 à 5 mots-clés en minuscules, concrets, sans "france" ni "actualité",
  et sans redire le lieu ni la catégorie.

Exemples :
{"lieu_nom": "Vénissieux", "lieu_type": "commune", "categorie": "incendie", "resume_ia": "Un entrepôt a brûlé cette nuit, mobilisant 40 pompiers, sans faire de blessé.", "gravite": 1, "tags": ["entrepôt", "pompiers"]}
{"lieu_nom": "national", "lieu_type": "national", "categorie": "politique", "resume_ia": "Le conseil municipal a adopté son budget 2027 à l'unanimité.", "gravite": 0, "tags": ["conseil municipal", "budget"]}
{"lieu_nom": "Tarn-et-Garonne", "lieu_type": "departement", "categorie": "economie", "resume_ia": "Le département peine à recruter des maîtres-nageurs pour surveiller ses bassins cet été.", "gravite": 0, "tags": ["recrutement", "pénurie", "piscine"]}
"""

# Injection de la liste canonique des catégories (source unique : app.categories)
# dans les prompts — évite de re-dupliquer l'énumération.
SYSTEM_PROMPT = SYSTEM_PROMPT.replace("__CATEGORIES_QUOTED__", CATEGORIES_QUOTED)
SYSTEM_PROMPT_SMALL = SYSTEM_PROMPT_SMALL.replace("__CATEGORIES_PLAIN__", CATEGORIES_PLAIN)

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "crue":         ["crue", "inondation", "débordement", "vigicrues", "montée des eaux",
                     "submersion", "zone inondable", "plan de prévention inondation"],
    "meteo":        ["météo", "météorologique", "tempête", "orage", "canicule", "verglas",
                     "neige", "vigilance météo", "vague de chaleur", "gel", "grêle",
                     "vent violent", "pluie intense", "forte chaleur", "brouillard",
                     "épisode méditerranéen", "vigilance jaune", "vigilance orange", "vigilance rouge"],
    "seisme":       ["séisme", "tremblement de terre", "magnitude", "secousse sismique", "sismique",
                     "secousse tellurique", "activité volcanique"],
    "energie":      ["coupure électricité", "réseau électrique", "enedis", "délestage",
                     "blackout", "panne de courant", "panne d'électricité", "panne edf",
                     "rupture d'approvisionnement", "réseau enedis", "tension sur le réseau",
                     "panne de gaz", "réseau gazier", "grdf", "gestionnaire réseau",
                     "réseau de transport", "rte électricité"],
    "transport":    ["sncf", "grève des transports", "perturbation trafic", "retard train",
                     "ratp", "autoroute", "accident de la route", "bouchon",
                     "circulation perturbée", "axe coupé", "route barrée", "fermeture autoroute",
                     "grève sncf", "trafic ferroviaire", "train supprimé", "rer", "transilien",
                     "déviation", "travaux routiers", "carambolage", "collision",
                     "poids lourd", "tramway", "ligne de bus", "aéroport", "vol annulé",
                     "gare routière", "péage", "sécurité routière", "permis de conduire",
                     "accident mortel sur la route", "piéton renversé"],
    # Inclut la chronique judiciaire et les faits divers, qui forment une part
    # importante de la presse régionale et tombaient jusqu'ici dans le
    # fourre-tout « actualite ».
    "ordre_public": ["manifestation", "émeute", "violence urbaine", "attentat", "terrorisme",
                     "incendie criminel", "fusillade", "agression", "cambriolage", "braquage",
                     "prise d'otage", "mort suspecte", "homicide", "tir",
                     "procès", "tribunal", "cour d'assises", "condamné", "condamnation",
                     "garde à vue", "mis en examen", "parquet", "réquisitions",
                     "interpellation", "interpellé", "gendarmerie", "commissariat",
                     "police municipale", "stupéfiants", "trafic de drogue",
                     "violences conjugales", "escroquerie", "vol aggravé", "détention provisoire",
                     "plainte", "enquête judiciaire", "délinquance", "rodéo urbain"],
    "incendie":     ["incendie de forêt", "feu de forêt", "feux de forêt", "départ de feu",
                     "sapeur-pompier", "pompiers", "SDIS", "DFCI", "hectares brûlés",
                     "pyromane", "incendie criminel", "brûlis"],
    "nucleaire":    ["nucléaire", "central nucléaire", "réacteur", "IRSN", "ASN", "EDF nucléaire",
                     "radioactivité", "irradiation", "contamination radioactive", "fuite radioactive",
                     "incident nucléaire", "centrale atomique", "combustible nucléaire"],
    "pollution":    ["pollution", "qualité de l'air", "indice de qualité", "particules fines",
                     "PM2.5", "PM10", "dioxyde d'azote", "ozone", "alerte pollution",
                     "pollution atmosphérique", "nappe phréatique contaminée", "marée noire",
                     "déversement", "dégazage", "pollution des eaux", "eau potable"],
    "cyber":        ["cyberattaque", "ransomware", "piratage", "ANSSI", "CERT-FR", "vulnérabilité",
                     "faille de sécurité", "logiciel malveillant", "phishing", "hameçonnage",
                     "violation de données", "fuite de données", "intrusion informatique",
                     "rançongiciel", "attaque informatique"],
    "sante":        ["épidémie", "pandémie", "virus", "contamination", "hôpital débordé",
                     "urgences saturées", "santé publique", "santépublique", "spf", "alerte sanitaire",
                     "intoxication", "rappel de lot", "listeria", "salmonelle", "grippe",
                     "gastro-entérite", "dépistage", "vaccination", "variole du singe",
                     "ansm", "médicament", "dispositif médical", "alerte sanitaire",
                     "crise sanitaire", "canicule sanitaire", "surveillance épidémique",
                     # Accès aux soins : c'est bien un sujet de santé, à distinguer
                     # du recrutement d'un soignant, qui relève de l'emploi.
                     "désert médical", "déserts médicaux", "accès aux soins"],
    "sport":        ["football", "rugby", "tennis", "basket", "handball", "cyclisme",
                     "ligue 1", "ligue des champions", "coupe de france", "roland-garros",
                     "jeux olympiques", "tour de france", "formule 1", "grand prix",
                     "championnat", "match", "compétition sportive", "athlétisme", "natation",
                     "l'équipe", "mondial", "qualification", "finale", "podium"],
    "economie":     ["bourse", "cac 40", "inflation", "récession", "chômage", "pib",
                     "banque centrale", "taux d'intérêt", "licenciement", "plan social",
                     "faillite", "résultats financiers", "pouvoir d'achat", "déficit",
                     "dette publique", "budget de l'état", "croissance économique",
                     "marché de l'emploi", "entreprise en difficulté",
                     "redressement judiciaire", "liquidation judiciaire", "usine",
                     "recrutement", "créations d'emplois", "chiffre d'affaires",
                     "commerçant", "artisan", "zone d'activité", "agriculteur",
                     "agriculture", "viticulture", "récolte", "exploitation agricole",
                     "immobilier", "prix de l'immobilier", "start-up", "chambre de commerce",
                     # Emploi : un sujet d'embauche reste économique même quand le
                     # métier relève de la santé ou du sport (maîtres-nageurs,
                     # infirmiers). Le classement suit le sujet, pas le secteur.
                     "recruter", "embauche", "embaucher", "main-d'œuvre",
                     "pénurie de personnel", "offre d'emploi", "poste vacant",
                     "salaire", "syndicat", "chômage technique", "apprentissage"],
    "politique":    ["conseil municipal", "conseil départemental", "conseil régional",
                     "intercommunalité", "communauté de communes", "municipales",
                     "préfet", "délibération", "budget municipal", "adjoint au maire",
                     "gouvernement", "assemblée nationale", "sénat", "élection", "ministre",
                     "président de la république", "réforme", "motion de censure", "remaniement",
                     "député", "parti politique", "scrutin", "campagne électorale",
                     "conseil des ministres", "premier ministre", "élysée", "matignon",
                     "projet de loi", "référendum"],
    "culture":      ["festival", "cinéma", "musée", "exposition", "concert", "théâtre",
                     "spectacle", "littérature", "roman", "album", "patrimoine", "césars",
                     "festival de cannes", "œuvre d'art", "vernissage", "biennale",
                     "saison culturelle", "scène nationale",
                     "médiathèque", "bibliothèque", "carnaval", "brocante", "vide-grenier",
                     "kermesse", "fête de la musique", "fête votive", "salon du livre",
                     "conférence", "opéra", "chorale", "cirque", "danse"],
}

GRAVITY_KEYWORDS: dict[int, list[str]] = {
    3: [
        # Crises nationales uniquement
        "état d'urgence", "catastrophe nationale", "plan rouge",
        "attentat", "attaque terroriste", "alerte attentat",
        "mort", "tués", "victimes", "décès", "bilan humain",
        "blessés graves", "en danger de mort", "urgence absolue",
        "immeuble effondré", "explosion meurtrière", "incendie mortel",
        "évacuation massive", "noyé", "enseveli", "disparu en mer",
    ],
    2: [
        # Alertes officielles et incidents graves localisés
        "alerte orange", "vigilance orange", "alerte rouge météo", "vigilance rouge",
        "alerte officielle", "alerte sanitaire", "rappel de médicament", "rappel de lot",
        "alerte vigicrues", "crue importante", "inondation grave",
        "arrêté préfectoral d'urgence", "fermeture préfectorale",
        "confinement", "évacuation préventive", "zone de danger",
        "couvre-feu", "blessés légers", "blessés", "blessé", "perturbation majeure confirmée",
    ],
    1: [
        # Vigilances météo et risques signalés sans victime
        "vigilance jaune", "vigilance météo", "avis de vigilance",
        "risque de", "prudence recommandée", "attention particulière",
        "perturbation prévue", "trafic perturbé", "grève prévue",
        "ralentissement important", "fermeture temporaire de route",
    ],
}

# Valeurs renvoyées par le modèle qui ne sont PAS des lieux français géocodables :
# on les ramène à « national » pour éviter un géocodage hasardeux (ex. « Mondial »
# matche une commune, « N/A » part en requête API inutile).
_NON_LIEU_VALUES = {
    "", "n/a", "na", "null", "none", "inconnu", "non spécifié", "non specifie",
    "monde", "international", "étranger", "etranger", "europe", "ue",
    "france", "nationale", "pays", "non localisable",
}


# Mots-clés trop génériques pour filtrer quoi que ce soit dans un corpus qui
# est, par construction, de l'actualité française.
_USELESS_TAGS = frozenset({
    "france", "français", "française", "actualité", "actualite", "actualités",
    "info", "infos", "information", "news", "société", "societe", "divers",
    "national", "général", "general",
})

# Niveaux admis pour lieu_type (champ facultatif renvoyé par le modèle).
_LIEU_TYPES = frozenset({"commune", "departement", "region", "national"})


def _tag_key(valeur: str) -> str:
    """Forme canonique d'un tag, pour comparer « Leyme », « leyme » et « LEYME »,
    ou « ordre public » et « ordre_public »."""
    decompose = unicodedata.normalize("NFD", valeur.lower())
    sans_accent = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", sans_accent)


_USELESS_TAG_KEYS = frozenset(_tag_key(t) for t in _USELESS_TAGS)


def _clean_tags(raw_tags: Any, lieu_nom: str, categorie: str) -> list[str]:
    """Normalise, dédoublonne et élague les tags renvoyés par le modèle.

    Le prompt interdit déjà de répéter le lieu ou la catégorie et de produire
    des mots-clés creux — mais le modèle le fait quand même (« leyme » sur un
    article dont lieu_nom vaut « Leyme »). Un tag qui reprend une information
    déjà portée par un autre champ n'aide à filtrer personne.
    """
    if not isinstance(raw_tags, list):
        return []
    exclus = {_tag_key(lieu_nom), _tag_key(categorie)} | _USELESS_TAG_KEYS
    tags: list[str] = []
    vus: set[str] = set()
    for brut in raw_tags:
        if not brut or not str(brut).strip():
            continue
        tag = str(brut).strip().lower()
        cle = _tag_key(tag)
        if not cle or cle in exclus or cle in vus:
            continue
        vus.add(cle)
        tags.append(tag)
        if len(tags) == 5:
            break
    return tags


def _validate_extraction(raw: dict) -> dict[str, Any]:
    """Normalize and validate a raw extraction dict from any AI backend."""
    _raw_lieu = raw.get("lieu_nom")
    lieu_nom = (str(_raw_lieu).strip() if _raw_lieu and _raw_lieu != "null" else "") or "national"
    if lieu_nom.lower() in _NON_LIEU_VALUES:
        lieu_nom = "national"

    categorie = str(raw.get("categorie", DEFAULT_CATEGORY)).strip()
    if categorie not in CATEGORY_SET:
        # Coercion silencieuse historique : on la trace désormais pour rendre un
        # éventuel drift de taxonomie observable (catégorie inventée par le LLM).
        if categorie and categorie != DEFAULT_CATEGORY:
            logger.debug("Catégorie inconnue '%s' coercée en '%s'", categorie, DEFAULT_CATEGORY)
        categorie = DEFAULT_CATEGORY

    _raw_resume = raw.get("resume_ia")
    # Coupe à la dernière phrase complète : `[:500]` tranchait au caractère près
    # et laissait des moignons (« La pénurie nationale att ») directement servis
    # dans le fil et repris tels quels dans le brief du soir.
    resume_ia = truncate_clean(
        sanitize_markdown(
            str(_raw_resume).strip() if _raw_resume and _raw_resume != "null" else ""
        ),
        500,
        prefer_sentence=True,
    )

    try:
        gravite = max(0, min(3, int(raw.get("gravite", 0))))
    except (TypeError, ValueError):
        gravite = 0

    tags = _clean_tags(raw.get("tags", []), lieu_nom, categorie)

    # lieu_type : facultatif (les modèles anciens ou petits peuvent l'omettre).
    # Sert au géocodeur à lever les homonymies ville/département (« Vienne »).
    lieu_type = str(raw.get("lieu_type", "") or "").strip().lower()
    if lieu_type not in _LIEU_TYPES:
        lieu_type = ""

    return {
        "lieu_nom": lieu_nom,
        "lieu_type": lieu_type,
        "categorie": categorie,
        "resume_ia": resume_ia,
        "gravite": gravite,
        "tags": tags,
    }


def _build_user_content(titre: str, description: str, full_text: str | None = None) -> str:
    """Build the user message sent to any AI backend."""
    # Heure de Paris (et non UTC) : près de minuit, l'UTC donne la veille et
    # fait dater les articles « d'hier » à tort.
    today = datetime.now(_PARIS).strftime("%d/%m/%Y")
    parts = [f"Date: {today}", f"Titre: {titre}"]
    if full_text:
        # Full article text gives much better location and tag extraction
        parts.append(f"\nContenu de l'article:\n{full_text[:3000]}")
    else:
        clean_desc = _strip_html(description) if description else ""
        if clean_desc:
            parts.append(f"\nDescription: {clean_desc[:1000]}")
    return "\n".join(parts)


async def _extract_with_ollama(titre: str, description: str,
                                full_text: str | None = None) -> dict[str, Any] | None:
    """Call the local Ollama model. Returns None on any error (caller falls back)."""
    user_content = _build_user_content(titre, description, full_text)
    # Les petits modèles (<3B) suivent mieux un prompt court et direct.
    is_small_model = any(
        tag in settings.OLLAMA_MODEL.lower()
        for tag in ("1.5b", "3b", "mini", "small", "tiny", "1b", "0.5b")
    )
    prompt = SYSTEM_PROMPT_SMALL if is_small_model else SYSTEM_PROMPT

    async with _OLLAMA_SEMAPHORE:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": settings.OLLAMA_MODEL,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": user_content},
                        ],
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.1, "num_predict": 350},
                    },
                )
                resp.raise_for_status()
                raw_text = resp.json()["message"]["content"].strip()
        except Exception as exc:
            logger.warning("Ollama extraction failed for '%s': %s", titre[:60], exc)
            return None

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        start, end = raw_text.find("{"), raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(raw_text[start:end])
            except json.JSONDecodeError:
                logger.warning("Ollama: unparseable JSON for '%s'", titre[:60])
                return None
        else:
            logger.warning("Ollama: no JSON in response for '%s'", titre[:60])
            return None

    return _validate_extraction(result)


async def _extract_with_mistral(titre: str, description: str,
                                full_text: str | None = None) -> dict[str, Any] | None:
    """Call the Mistral AI API. Returns None on any error (caller falls back)."""
    user_content = _build_user_content(titre, description, full_text)

    async with _MISTRAL_SEMAPHORE:
        raw_text = await mistral_chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=350,
            temperature=0.1,
            response_format={"type": "json_object"},
            etiquette=f"extraction '{titre[:50]}'",
        )
    if not raw_text:
        return None
    logger.info("Mistral OK [%s] '%s'", settings.MISTRAL_MODEL, titre[:50])

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        start, end = raw_text.find("{"), raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(raw_text[start:end])
            except json.JSONDecodeError:
                logger.warning("Mistral: unparseable JSON for '%s'", titre[:60])
                return None
        else:
            logger.warning("Mistral: no JSON in response for '%s'", titre[:60])
            return None

    return _validate_extraction(result)


TOPONYM_PATTERNS: list[str] = [
    r'\bà\s+([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,3})',
    r'\ben\s+([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,2})',
    r'\bdans\s+(?:le |la |les |l\')?([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,2})',
    r'\bprès\s+de\s+([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,2})',
    r'\bau\s+large\s+de\s+([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+)',
    r'\bsur\s+(?:le |la |les |l\')?([A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+(?:[- ][A-ZÉÀÈÊËÙÛÜ][a-zéàèêëîïôûùüç]+){0,2})',
]


def _strip_html(text: str) -> str:
    """Supprime les balises HTML et décode les entités."""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = _html.unescape(text)
    return ' '.join(text.split())


async def _rule_based_extract(titre: str, description: str | None) -> dict[str, Any]:
    """Extraction par règles (sans IA) : catégorie, gravité et lieu par regex + géocodage."""
    clean_desc = _strip_html(description) if description else None
    text = (titre + " " + (clean_desc or "")).lower()

    # --- Catégorie ---
    categorie = "actualite"
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw.lower() in text for kw in keywords):
            categorie = cat
            break

    # --- Gravité ---
    gravite = 0
    for level in (3, 2, 1):
        if any(kw.lower() in text for kw in GRAVITY_KEYWORDS[level]):
            gravite = level
            break

    # --- Lieu par regex : titre d'abord, puis description ---
    lieu_nom = "national"
    texts_to_search = [titre]
    if clean_desc:
        # Only first 300 chars of description for performance
        texts_to_search.append(clean_desc[:300])

    for search_text in texts_to_search:
        for pattern in TOPONYM_PATTERNS:
            for match in re.finditer(pattern, search_text):
                candidate = match.group(1).strip()
                try:
                    geo = await geocode(candidate)
                    if geo.get("confiance_geo", 0.0) >= 0.65:
                        lieu_nom = candidate
                        break
                except Exception as exc:
                    logger.debug("Geocoding candidate '%s' failed: %s", candidate, exc)
            if lieu_nom != "national":
                break
        if lieu_nom != "national":
            break

    # --- Résumé ---
    resume_ia = (clean_desc[:280] if clean_desc else None) or titre[:200]

    return {
        "lieu_nom": lieu_nom,
        "categorie": categorie,
        "resume_ia": resume_ia,
        "gravite": gravite,
        "tags": [],
    }


async def extract_article(titre: str, description: str,
                          full_text: str | None = None) -> dict[str, Any]:
    """Extraction : Mistral API → Ollama local → fallback règles."""
    key = _cache_key(titre, description)
    if key in _extract_cache:
        return _extract_cache[key]

    result: dict[str, Any] | None = None

    if settings.MISTRAL_API_KEY:
        result = await _extract_with_mistral(titre, description, full_text)
        if result is None:
            logger.info("Mistral unavailable — falling back to Ollama/rules")

    if result is None and settings.OLLAMA_BASE_URL:
        result = await _extract_with_ollama(titre, description, full_text)
        if result is None:
            logger.info("Ollama unavailable — falling back to rule-based extraction")

    if result is None:
        result = await _rule_based_extract(titre, description)

    _cache_put(key, result)
    return result


# Sources autoritatives → catégorie forcée (indépendamment de l'extraction NLP)
SOURCE_CAT_OVERRIDES: dict[str, str] = {
    "santé publique france": "sante",
    "spf": "sante",
    "ansm": "sante",
    "vigicrues": "crue",
    "météo-france": "meteo",
    "meteo-france": "meteo",
    "ministère intérieur": "ordre_public",
    "ministere interieur": "ordre_public",
}


_FRANCE_HINTS_RE = re.compile(
    r"\b(france|français|française|franco-\w+|hexagone|paris|lyon|marseille|bordeaux|"
    r"toulouse|nantes|lille|strasbourg|rennes|montpellier|nice|grenoble|metz|nancy|"
    r"caen|rouen|bretagne|normandie|alsace|occitanie|provence|île-de-france|"
    r"préfet|préfecture|mairie|maire|conseil municipal|"
    r"sncf|ratp|edf|enedis|météo-france|insee|sénat|élysée|matignon|"
    r"assemblée nationale|gendarmerie|igpn|macron|premier ministre|"
    r"gouvernement français|départem|région|commune|arrondissement)\b",
    re.IGNORECASE,
)


# Marqueurs d'un article dont le SUJET est à l'étranger. Volontairement courte
# et sans ambiguïté : elle ne sert qu'à écarter ce qui est manifestement
# hors-scope pour une carte de France.
# Pays et villes dont la mention SEULE (sans indice français par ailleurs)
# signale un article étranger. Volontairement large depuis le 11/08/2026 : la
# liste d'origine couvrait 45 entrées et ignorait presque toute l'Amérique
# latine, l'Europe de l'Est, l'Afrique et l'Asie du Sud-Est — « Séisme en
# Colombie : 181 morts » passait pour français et ressortait en gravité 3,
# c'est-à-dire en notification push rouge pour un lecteur à Brest.
#
# Écartés délibérément, car homonymes de mots ou de lieux français : chili
# (le piment), panama (le chapeau), malte (le malt), luxembourg (le jardin et
# le Sénat), monaco (omniprésent dans les pages sport), niger et congo
# (fleuves autant que pays). L'ordre de _looks_french limite de toute façon
# les dégâts : un indice français l'emporte sur un indice étranger.
_FOREIGN_FOCUS_RE = re.compile(
    r"\b("
    # Europe
    r"ukraine|ukrainien|russie|russe|moscou|kiev|kyiv|"
    r"allemagne|allemand|berlin|espagne|espagnol|madrid|barcelone|"
    r"italie|italien|rome|milan|portugal|portugais|lisbonne|"
    r"royaume-uni|londres|angleterre|britannique|écosse|ecosse|irlande|"
    r"belgique|belge|bruxelles|suisse|genève|geneve|pays-bas|amsterdam|"
    r"pologne|polonais|varsovie|roumanie|hongrie|budapest|tchèque|tcheque|prague|"
    r"autriche|vienne \(autriche\)|slovaquie|slovénie|slovenie|croatie|serbie|"
    r"bulgarie|grèce|grece|athènes|athenes|albanie|"
    r"suède|suede|stockholm|norvège|norvege|oslo|danemark|copenhague|"
    r"finlande|helsinki|islande|"
    # Amériques
    r"états-unis|etats-unis|américain|americain|washington|new york|floride|texas|"
    r"canada|canadien|québec|quebec|montréal|montreal|"
    r"brésil|bresil|brésilien|bresilien|argentine|argentin|mexique|mexicain|"
    # « chili » sauf « chili con carne » : le Chili est une zone sismique
    # majeure, trop coûteuse à ignorer pour un homonyme culinaire.
    r"venezuela|colombie|colombien|chili(?!\s+con)|"
    r"pérou|perou|péruvien|peruvien|bolivie|"
    r"équateur|equateur|uruguay|paraguay|cuba|cubain|haïti|haiti|"
    r"nicaragua|honduras|guatemala|"
    # Proche et Moyen-Orient
    r"gaza|israël|israel|israélien|israelien|palestin|liban|libanais|"
    r"iran|iranien|irak|irakien|syrie|syrien|jordanie|arabie saoudite|"
    r"émirats|emirats|qatar|yémen|yemen|"
    # Asie
    r"chine|chinois|pékin|pekin|shanghai|taïwan|taiwan|hong kong|"
    r"inde|indien|new delhi|pakistan|pakistanais|bangladesh|afghanistan|"
    r"japon|japonais|tokyo|corée|coree|coréen|coreen|séoul|seoul|"
    r"indonésie|indonesie|philippines|thaïlande|thailande|bangkok|"
    r"vietnam|birmanie|myanmar|népal|nepal|sri lanka|"
    # Afrique
    r"maroc|marocain|rabat|algérie|algerie|algérien|algerien|alger|"
    r"tunisie|tunisien|libye|égypte|egypte|égyptien|egyptien|le caire|"
    r"sénégal|senegal|sénégalais|senegalais|dakar|mali|burkina|"
    r"côte d'ivoire|cote d'ivoire|ivoirien|abidjan|cameroun|gabon|"
    r"nigeria|nigérian|nigerian|kenya|éthiopie|ethiopie|soudan|somalie|"
    r"tchad|mauritanie|madagascar|afrique du sud|"
    # Océanie et divers
    r"australie|australien|nouvelle-zélande|nouvelle-zelande|"
    r"turquie|turc|ankara|istanbul"
    r")\b",
    re.IGNORECASE,
)


def _looks_french(titre: str, description: str) -> bool:
    """L'article relève-t-il de l'actualité française ?

    Sert à épargner un appel au modèle sur les dépêches internationales, qui
    finiraient de toute façon en « national ».

    L'implantation d'origine exigeait un indice français EXPLICITE — « france »,
    « paris », « préfet », une vingtaine de grandes villes — et concluait
    « étranger » par défaut. Elle écartait donc massivement ce qui fait le cœur
    du produit : « Le chef d'état-major d'Épinal suspendu », « Corte : un
    incendie se déclare à proximité d'habitations » et « Situation signalée à
    Carreau Z'ananas » étaient tous jugés non français (relevé du 03/08/2026) et
    n'atteignaient jamais le modèle — l'information locale parle de petites
    communes, précisément celles qu'aucune liste de grandes villes ne contient.

    On raisonne maintenant dans le bon sens : le corpus EST de la presse
    française, donc le doute profite au français. Seul un marqueur étranger net,
    sans le moindre indice français, fait renoncer à l'extraction.
    """
    text = titre + " " + (description or "")[:300]

    if _FRANCE_HINTS_RE.search(text):
        return True
    # Une commune française nommée dans le titre vaut tous les indices : c'est
    # la table des 35 000, pas une liste de vingt métropoles.
    from app.communes_db import commune_from_text
    if commune_from_text(titre):
        return True
    # Le marqueur étranger doit être dans le TITRE, qui dit le sujet. Cité dans
    # le corps, il n'est souvent qu'une comparaison ou un élément de contexte.
    # L'asymétrie commande la prudence : se tromper vers « français » coûte un
    # appel au modèle, se tromper vers « étranger » dégrade un article local.
    if _FOREIGN_FOCUS_RE.search(titre):
        return False
    # Aucun indice dans un sens ni dans l'autre : presse française par défaut.
    return True


# Plafond de gravité déterministe pour la presse. Le petit modèle local
# sur-évalue massivement (≈40 % des articles classés en alerte). On borne sa
# sortie par un scan de mots-clés conservateur : une gravité élevée n'est retenue
# que si des termes d'alerte EXPLICITES apparaissent. Le LLM ne peut que RÉDUIRE
# ce plafond (min), jamais inventer une alerte. Échelle de l'app : 3 = crise
# nationale (très rare), 2 = alerte officielle, 1 = vigilance/incident, 0 = info.
_GRAVITY_CEIL_3_RE = re.compile(
    r"\b(état d'urgence|catastrophe nationale|plan rouge|attentat|"
    r"attaque terroriste|pandémie|alerte enlèvement)\b",
    re.IGNORECASE,
)
_GRAVITY_CEIL_2_RE = re.compile(
    r"\b(vigilance orange|vigilance rouge|alerte rouge|alerte orange|"
    r"rappel (?:de )?(?:produit|lot|médicament)|vigicrues|arrêté préfectoral|"
    r"évacuation|confinement|couvre-feu|prise d'otage|fusillade|explosion|"
    r"séisme|magnitude|effondrement)\b",
    re.IGNORECASE,
)
_GRAVITY_CEIL_1_RE = re.compile(
    r"\b(vigilance jaune|accident|incendie|bless[ée]s?|noyades?|noyés?|"
    r"grève|manifestation|perturbation|canicule|vague de chaleur|orages?|"
    r"tempête|intempéries|coupure|inondation|crue|disparition)\b",
    re.IGNORECASE,
)


def _press_gravity_ceiling(titre: str, description: str) -> int:
    text = f"{titre} {description or ''}"
    if _GRAVITY_CEIL_3_RE.search(text):
        return 3
    if _GRAVITY_CEIL_2_RE.search(text):
        return 2
    if _GRAVITY_CEIL_1_RE.search(text):
        return 1
    return 0



async def maybe_extract(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("skip_extraction"):
        return item

    needs_extraction = (
        item.get("source") == "presse_rss"
        or not item.get("lieu_nom")
        or not item.get("resume_ia")
    )

    if not needs_extraction:
        return item

    titre = item.get("titre", "")
    description = item.get("description", "") or item.get("raw", {}).get("summary", "")

    _has_ai = bool(settings.MISTRAL_API_KEY or settings.OLLAMA_BASE_URL)

    # Pour la presse généraliste, beaucoup d'articles concernent l'étranger.
    # Si le titre+description ne contient aucun indice français ET qu'un backend
    # IA est configuré (Mistral ou Ollama), on bascule directement sur le fallback
    # règles pour ne pas consommer de quota/CPU sur des articles hors-scope.
    if (
        _has_ai
        and item.get("source") == "presse_rss"
        and not _looks_french(titre, description)
    ):
        extraction = await _rule_based_extract(titre, description)
        # La gravité ≥ 2 ouvre DEUX canaux d'alerte française : la section
        # « Alertes & vigilances » du brief, et surtout les notifications push
        # (push.py sélectionne Event.gravite >= 2). Or les règles attribuent la
        # gravité au seul mot-clé de catégorie, sans notion de lieu : « Séisme
        # en Colombie : au moins 181 morts » ressortait en gravité 3, donc en
        # notification rouge sur le téléphone d'un lecteur à Brest (relevé du
        # 11/08/2026). Un fait étranger a sa place dans le fil — pas dans le
        # canal d'alerte d'un service géolocalisé sur la France.
        if extraction.get("gravite", 0) >= 2:
            logger.info("Article hors France, gravité %d ramenée à 1 : %s",
                        extraction["gravite"], titre[:70])
            extraction["gravite"] = 1
    else:
        # Fetch full article content when an AI backend is available — richer context
        # greatly improves location extraction and tag quality.
        full_text: str | None = None
        if settings.FETCH_FULL_ARTICLES and _has_ai:
            source_url = item.get("source_url", "")
            if source_url:
                from app.pipeline.fetcher import fetch_article_text
                full_text = await fetch_article_text(source_url)

        extraction = await extract_article(titre, description, full_text)

    updated = dict(item)

    if updated.get("source") == "presse_rss":
        # Pour la presse, le verdict du modèle fait autorité, y compris
        # « national » : sinon un article international/national repris par un
        # flux régional (ex. « Guerre au Moyen-Orient » sur Actu Occitanie)
        # hériterait à tort de la région du flux et serait mal placé sur la carte.
        updated["lieu_nom"] = extraction["lieu_nom"]
        # Le modèle indique aussi la nature du lieu ("commune", "departement",
        # "region"). Quand elle est fournie et que le nom est ambigu (Vienne la
        # ville / la Vienne le département, Lot, Somme, Aube…), on résout
        # directement au bon niveau au lieu de laisser le géocodeur deviner.
        _lieu_type = extraction.get("lieu_type") or ""
        if _lieu_type == "commune" and updated["lieu_nom"] != "national":
            from app.communes_db import lookup_commune
            _c = lookup_commune(updated["lieu_nom"])
            if _c:
                updated["lieu_lat"] = _c["lat"]
                updated["lieu_lon"] = _c["lon"]
                updated["lieu_code_insee"] = _c["code_insee"]
                updated["lieu_niveau"] = "commune"
                updated["lieu_confiance_geo"] = 0.85
                updated["skip_geocoding"] = True
            else:
                # Le modèle affirme une commune que la table des 35 000 ne connaît
                # pas : c'est presque toujours un lieu inventé ou mal lu
                # (« Nauxion », relevé le 03/08/2026). Laisser le géocodeur
                # chercher un nom qui n'existe pas invite une correspondance floue
                # de l'API externe — donc un marqueur au mauvais endroit. Or un
                # faux marqueur trompe le lecteur, là où un événement « national »
                # reste simplement hors carte. On préfère renoncer.
                logger.info(
                    "Commune inconnue '%s' annoncée par le modèle — repli national",
                    updated["lieu_nom"],
                )
                updated["lieu_nom"] = "national"
        elif updated["lieu_nom"] != "national":
            # Même principe, pour les cas que le test ci-dessus laissait passer.
            # Il ne se déclenchait que si le modèle DÉCLARAIT lui-même une
            # commune : lieu_type absent ou inattendu, et le nom partait au
            # géocodage sans avoir été vérifié par personne. Or la BAN répond
            # toujours quelque chose (Kiev → Quiévy, Gaza → Gazaupouy), et son
            # score ne permet pas de trier — voir est_lieu_connu.
            from app.pipeline.toponym import est_lieu_connu
            if not est_lieu_connu(updated["lieu_nom"]):
                logger.info(
                    "Lieu inconnu '%s' (lieu_type=%r) — repli national",
                    updated["lieu_nom"], _lieu_type or None,
                )
                updated["lieu_nom"] = "national"
        # Repli : LLM = "national" mais le lieu est récupérable. Beaucoup
        # d'articles locaux étaient classés « national » faute d'extraction LLM
        # alors que l'info est gratuite dans l'URL (code INSEE/postal/département).
        # Priorité : commune exacte via INSEE/CP de l'URL (coords injectées
        # directement) > ville/région citée dans le titre > département de l'URL.
        if updated["lieu_nom"] == "national":
            from app.pipeline.toponym import toponym_from_title, location_from_url
            loc = location_from_url(item.get("source_url", ""))
            if loc and loc["niveau"] == "commune":
                updated["lieu_nom"] = loc["lieu_nom"]
                updated["lieu_lat"] = loc["lat"]
                updated["lieu_lon"] = loc["lon"]
                updated["lieu_code_insee"] = loc["code_insee"]
                updated["lieu_niveau"] = "commune"
                updated["lieu_confiance_geo"] = 0.9
                updated["skip_geocoding"] = True  # coords exactes, pas de re-géocodage
            else:
                # Deux cas où l'on s'interdit de DEVINER le lieu depuis le texte.
                #
                # 1. Le sport : les noms de clubs contiennent des villes
                #    (« Paris FC », « AS Monaco », « OGC Nice ») → faux pins.
                # 2. Le modèle AFFIRME une portée nationale (lieu_type =
                #    "national"). C'est une conclusion prise en ayant lu
                #    l'article entier, quand un lieu_nom vide n'est qu'une
                #    absence d'information. La contredire par une expression
                #    régulière sur le titre produit des contresens : « Incendies.
                #    Le Var inquiet […] en Grèce » se voyait planté dans le Var
                #    alors que l'article traitait des feux de Gironde (relevé du
                #    03/08/2026).
                #
                # Le repli par URL, lui, reste appliqué dans les deux cas : un
                # code INSEE ou postal dans le chemin est un fait, pas une
                # devinette.
                sans_devinette_textuelle = (
                    extraction.get("categorie") == "sport" or _lieu_type == "national"
                )
                # Commune nommée dans le titre : la table locale couvre 35 000
                # communes là où la liste de toponymes n'en connaît que ~70
                # (grandes villes). Garde-fous dans commune_from_text :
                # population ≥ 3 000, nom propre, liste noire d'homonymes.
                commune = None
                if not sans_devinette_textuelle:
                    from app.communes_db import commune_from_text
                    commune = commune_from_text(item.get("titre", ""))
                if commune:
                    updated["lieu_nom"] = commune["nom"]
                    updated["lieu_lat"] = commune["lat"]
                    updated["lieu_lon"] = commune["lon"]
                    updated["lieu_code_insee"] = commune["code_insee"]
                    updated["lieu_niveau"] = "commune"
                    # Sous le 0.9 d'un code INSEE lu dans l'URL : ici le nom est
                    # déduit d'un texte, donc un cran moins sûr.
                    updated["lieu_confiance_geo"] = 0.75
                    updated["skip_geocoding"] = True
                else:
                    _topo = (
                        None if sans_devinette_textuelle
                        else toponym_from_title(item.get("titre", ""))
                    )
                    if not _topo and loc:
                        _topo = loc["lieu_nom"]
                    if _topo:
                        updated["lieu_nom"] = _topo
    elif not updated.get("lieu_nom") and extraction["lieu_nom"] != "national":
        updated["lieu_nom"] = extraction["lieu_nom"]

    if not updated.get("resume_ia"):
        updated["resume_ia"] = extraction["resume_ia"]
    if not updated.get("categorie") or updated.get("source") == "presse_rss":
        updated["categorie"] = extraction["categorie"]

    if updated.get("source") == "presse_rss":
        # Borne la gravité du petit modèle par un plafond déterministe (cf.
        # _press_gravity_ceiling) : sans corroboration par mot-clé d'alerte, un
        # article ordinaire reste à 0 même si le modèle a halluciné un « 3 ».
        ceiling = _press_gravity_ceiling(titre, description)
        updated["gravite"] = min(int(extraction["gravite"]), ceiling)
    elif updated.get("gravite", 0) == 0 and extraction["gravite"] > 0:
        updated["gravite"] = extraction["gravite"]

    updated["tags"] = extraction.get("tags", [])

    # Override catégorie pour les sources autoritatives connues
    auteur_lower = (updated.get("auteur") or "").lower()
    for keyword, forced_cat in SOURCE_CAT_OVERRIDES.items():
        if keyword in auteur_lower:
            updated["categorie"] = forced_cat
            break

    return updated
