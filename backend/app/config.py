import logging
import re

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal

logger = logging.getLogger(__name__)

# Mots de passe de base de données trop faibles : refusés en production.
_WEAK_DB_PASSWORDS = frozenset({
    "password", "passwd", "postgres", "admin", "root", "changeme", "change-me",
    "123456", "12345678", "azerty", "qwerty", "secret", "test", "faire_info",
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    DATABASE_URL: str = "postgresql+asyncpg://faire_info:password@localhost:5432/faire_info"
    METEO_FRANCE_API_KEY: str = ""

    APP_ENV: Literal["development", "production", "test"] = "development"
    LOG_LEVEL: str = "INFO"

    SCHEDULER_TIMEZONE: str = "Europe/Paris"

    # Heures des ingestions complètes (heure locale du fuseau ci-dessus).
    # 07h au réveil, 12h à la mi-journée, 19h en fin de journée : trois
    # passages qui suivent le rythme de publication de la presse plutôt qu'un
    # intervalle régulier. Le plus grand écart, de 19h à 07h, fait douze
    # heures — bien en deçà des HEALTHZ_MAX_DATA_AGE_HOURS qui déclarent le
    # conteneur malade. Les sources d'alerte (météo, crues, séismes) restent
    # de toute façon relevées toutes les heures par HOURLY_ALERT_INGESTION,
    # nuit comprise.
    # Format : heures séparées par des virgules, ex. "7,12,19" ou "6,11,16,21,2".
    INGEST_HOURS: str = "7,12,19"

    # Heures de génération du brief : chacune suit son ingestion de deux
    # heures, largement de quoi laisser l'enrichissement se terminer (une
    # ingestion de MAX_PRESSE_ARTICLES articles prend de l'ordre du quart
    # d'heure). Un brief planifié sans ingestion en amont ne ferait que
    # reformuler le précédent. Même format et mêmes garde-fous que
    # INGEST_HOURS.
    BRIEF_HOURS: str = "9,14,21"

    MAX_EVENTS_LIMIT: int = 1000
    DEFAULT_EVENTS_LIMIT: int = 500
    DEFAULT_SINCE_HOURS: int = 48

    # CORS : liste d'origines autorisées, séparées par des virgules.
    # "*" autorise toutes les origines (API publique en lecture seule, sans cookies).
    CORS_ORIGINS: str = "*"

    # Clé optionnelle pour l'endpoint POST /api/ingest/run.
    # Vide = pas d'auth (dev/local). En prod, définir une valeur aléatoire forte.
    INGEST_API_KEY: str = ""

    # Documentation interactive (Swagger /docs, ReDoc /redoc, /openapi.json).
    # Sécurisé par défaut : désactivée. Mettre ENABLE_DOCS=true en local pour
    # explorer l'API. Laisser à false en production expose moins la surface API.
    ENABLE_DOCS: bool = False

    # Mistral AI (prioritaire sur Ollama quand la clé est renseignée)
    MISTRAL_API_KEY: str = ""
    MISTRAL_MODEL: str = "mistral-small-latest"

    # Tentatives par appel Mistral, reprises comprises. Un HTTP 429 (« trop de
    # requêtes ») n'est pas une panne : il se résout en patientant. Sans reprise,
    # l'extraction retombait sur les règles — résumé tronqué, aucun tag, lieu
    # « national » — et le brief n'était pas produit du tout (relevé du
    # 11/08/2026 : 3 articles sur 15 perdus ainsi). Mettre 1 pour désactiver.
    MISTRAL_MAX_RETRIES: int = 4

    # Appels Mistral simultanés. Avec l'espacement ci-dessous, la concurrence ne
    # sert plus qu'à recouvrir la latence : quatre suffisent, et un nombre bas
    # évite que des reprises simultanées ne repartent en rafale.
    MISTRAL_MAX_CONCURRENCY: int = 4

    # Espacement minimal (secondes) entre deux départs de requête Mistral.
    # C'est le vrai garde-fou contre la limitation de débit : la reprise seule
    # ne suffisait pas — relevé du 11/08/2026, 5 articles sur 15 ont épuisé
    # leurs quatre tentatives en 429, et ces 5 articles sont EXACTEMENT ceux
    # ressortis sans tags et avec un résumé recopié du titre. Coût : une
    # ingestion de MAX_PRESSE_ARTICLES articles dure au moins
    # MAX_PRESSE_ARTICLES × cette valeur (120 s pour 120 articles à 1 s), à
    # comparer aux minutes que prend déjà l'enrichissement. Mettre 0 pour
    # désactiver ; augmenter si des 429 subsistent dans les journaux.
    MISTRAL_MIN_INTERVAL_SECONDS: float = 1.0

    # Ollama : fallback local si MISTRAL_API_KEY est vide
    OLLAMA_BASE_URL: str = ""
    OLLAMA_MODEL: str = "qwen2.5:1.5b"

    # Consulter robots.txt avant de télécharger le CORPS d'un article.
    # Un flux RSS est publié pour être repris ; aspirer le texte intégral pour
    # le passer à un modèle de langage est autre chose, et la presse française
    # le refuse largement : mesuré le 11/08/2026, 678 des 867 flux (78 %)
    # pointent vers un hôte qui l'interdit — actu.fr, ici.fr, France 3 Régions,
    # franceinfo, Le Monde. Les flux, eux, continuent d'être lus normalement :
    # c'est leur raison d'être.
    # COÛT ASSUMÉ, et il porte sur la majorité du corpus : pour ces sources
    # l'extraction retombe sur titre + chapô RSS, ce qui se produit déjà quand
    # un téléchargement échoue. Mettre false rétablit l'ancien comportement.
    RESPECT_ROBOTS_TXT: bool = True

    # Activer le fetch du contenu complet des articles avant extraction IA.
    # Désactiver si la VM a un accès internet limité ou pour économiser la bande passante.
    FETCH_FULL_ARTICLES: bool = True

    # Plafond d'articles de presse traités par cycle d'ingestion (les plus
    # récents). Chaque article passe par le LLM (classement + résumé + lieu),
    # ~12 s sur CPU avec un petit modèle : sans plafond, un run de ~1000 articles
    # sature le CPU pendant plus d'une heure avant le moindre commit. 120 ≈ 12 min.
    MAX_PRESSE_ARTICLES: int = 120

    # Délai maximal accordé à la phase de collecte (fetch) d'un connecteur. Au-delà,
    # on abandonne CE connecteur (0 événement, erreur enregistrée) sans bloquer les
    # autres : une source qui répond au compte-gouttes ne doit pas figer toute
    # l'ingestion. Généreux car presse_rss interroge ~114 flux. La phase
    # d'enrichissement IA (postérieure au fetch) n'est pas concernée par ce délai.
    CONNECTOR_FETCH_TIMEOUT_SECONDS: int = 120

    # Cache Redis (optionnel). Si vide, le cache est désactivé.
    # En production : redis://redis:6379
    REDIS_URL: str = ""
    # Durée de vie du cache API événements (secondes).
    REDIS_EVENTS_TTL: int = 120

    # Plafond de connexions SSE (/events/stream) simultanées. Chaque flux ouvert
    # sonde la base toutes les 30 s : sans borne, de nombreux onglets/clients
    # peuvent épuiser le pool de connexions PostgreSQL. Au-delà du plafond, le
    # serveur répond 503 et le front retombe sur le polling SWR (5 min).
    MAX_SSE_CONNECTIONS: int = 100

    # Circuit-breaker des flux RSS presse : après FEED_FAILURE_THRESHOLD échecs
    # consécutifs, un flux est mis de côté pendant FEED_SKIP_RUNS cycles
    # d'ingestion, puis re-testé (un seul essai ; nouvel échec → nouvelle mise à
    # l'écart). État en mémoire (comme le cache ETag) : un redémarrage du
    # backend re-teste tous les flux. À 3-4 ingestions/jour, 8 runs ≈ 2 jours.
    FEED_FAILURE_THRESHOLD: int = 3
    FEED_SKIP_RUNS: int = 8

    # Webhook de notification (optionnel) : URL appelée quand un connecteur dépasse
    # le seuil d'échecs consécutifs. Compatible Discord, Slack, ntfy, etc.
    # Exemple ntfy : https://ntfy.sh/mon-topic
    WEBHOOK_URL: str = ""
    # Nombre d'échecs consécutifs déclenchant le webhook.
    WEBHOOK_THRESHOLD: int = 3

    # Healthcheck de fraîcheur (GET /healthz) : le conteneur est déclaré
    # « unhealthy » si plus aucun événement n'a été ingéré depuis ce délai.
    # Avec 3 ingestions/jour (écart max 12 h), 26 h = un cycle entièrement
    # raté + marge. Panne du 27-30/07/2026 : scheduler mort dans un conteneur
    # « healthy » pendant 3 jours — ce seuil l'aurait rendue visible dès J+1.
    HEALTHZ_MAX_DATA_AGE_HOURS: int = 26
    # Retard toléré sur l'heure de la prochaine ingestion planifiée avant de
    # passer unhealthy (aligné sur le misfire_grace_time d'APScheduler : 1 h).
    HEALTHZ_SCHEDULER_GRACE_MINUTES: int = 60
    # Fenêtre après le démarrage pendant laquelle la fraîcheur des données
    # n'est pas exigée : l'ingestion de démarrage peut prendre >10 min
    # (MAX_PRESSE_ARTICLES × LLM) et la base peut légitimement être vide/stale.
    HEALTHZ_BOOT_GRACE_MINUTES: int = 30

    # Passage horaire des sources d'alerte (météo, crues, séismes) en plus des
    # 3 ingestions complètes quotidiennes. APIs structurées, aucun coût LLM :
    # une vigilance orange apparaît en ~1 h au lieu d'attendre le prochain run.
    HOURLY_ALERT_INGESTION: bool = True

    # Écarte les articles d'affiliation des flux de presse (bons plans, promos,
    # comparatifs de prix) : sans lieu, sans gravité, ils n'ont rien à faire sur
    # une carte d'information. Filtre volontairement prudent (deux signaux
    # concordants exigés) — voir app/pipeline/commercial.py. Mettre à false pour
    # tout laisser passer.
    FILTER_COMMERCIAL_CONTENT: bool = True

    # Intervalle minimal (secondes) entre deux requêtes vers un même hôte lors
    # de la collecte RSS. La concurrence par hôte borne les requêtes
    # SIMULTANÉES, pas le débit : trois en parallèle qui se renouvellent
    # aussitôt, ce sont toujours des dizaines d'appels en quelques secondes.
    # Mesure de précaution contre les WAF anti-bot ; son bénéfice n'a pas été
    # démontré sur un blocage déjà posé. Coût : le plus gros hôte (actu.fr,
    # 114 flux) prend 114 × cette valeur, à comparer aux 120 s de
    # CONNECTOR_FETCH_TIMEOUT_SECONDS. Mettre 0 pour désactiver.
    FEED_HOST_MIN_INTERVAL_SECONDS: float = 0.3

    # ── Notifications Web Push (VAPID) ──────────────────────────────────────
    # Générer une paire une seule fois :
    #   docker compose exec backend python -m app.maintenance vapid-keys
    # La clé publique est distribuée aux navigateurs, la privée signe les
    # envois. Sans ces valeurs, les endpoints de notification renvoient 503 et
    # l'interface masque l'option — l'application fonctionne normalement.
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    # Contact exigé par la spécification VAPID (les services de push l'utilisent
    # pour signaler un problème d'émission).
    VAPID_CONTACT_EMAIL: str = ""

    # Répertoire des logs applicatifs persistants (RotatingFileHandler).
    # Vide = stdout uniquement. En prod : /app/logs, monté en volume — les logs
    # survivent à la recréation du conteneur (panne de 07/2026 : autopsie
    # impossible, les logs étaient morts avec l'ancien conteneur).
    LOG_DIR: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        # Fail-closed en production : le wildcard "*" (valeur par défaut) est
        # neutralisé. Le front parle à l'API en same-origin via nginx, donc rien
        # n'est cassé ; seules les requêtes XHR cross-origin de sites tiers sont
        # bloquées. Pour exposer publiquement l'API en cross-origin, définir
        # explicitement CORS_ORIGINS=https://exemple.fr,https://autre.fr .
        if self.APP_ENV == "production" and origins == ["*"]:
            logger.warning(
                "CORS: '*' neutralisé en production (fail-closed). Le front "
                "same-origin fonctionne ; définissez CORS_ORIGINS pour autoriser "
                "des origines tierces."
            )
            return []
        return origins

    @model_validator(mode="after")
    def _reject_insecure_defaults_in_prod(self) -> "Settings":
        # Fail-closed : en production, refuser de démarrer avec un mot de passe de
        # base de données faible/par défaut (visible dans le code ou trivial).
        if self.APP_ENV == "production":
            m = re.search(r"://[^:/@]+:([^@]+)@", self.DATABASE_URL)
            pwd = (m.group(1) if m else "").lower()
            if pwd in _WEAK_DB_PASSWORDS:
                raise ValueError(
                    "DATABASE_URL utilise un mot de passe faible/par défaut en "
                    "production. Définissez un mot de passe fort via l'environnement "
                    "(POSTGRES_PASSWORD)."
                )
        return self


settings = Settings()
