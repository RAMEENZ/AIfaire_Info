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

    # Ollama : fallback local si MISTRAL_API_KEY est vide
    OLLAMA_BASE_URL: str = ""
    OLLAMA_MODEL: str = "qwen2.5:1.5b"

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
