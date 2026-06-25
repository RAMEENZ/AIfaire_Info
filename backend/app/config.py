from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


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

    # Webhook de notification (optionnel) : URL appelée quand un connecteur dépasse
    # le seuil d'échecs consécutifs. Compatible Discord, Slack, ntfy, etc.
    # Exemple ntfy : https://ntfy.sh/mon-topic
    WEBHOOK_URL: str = ""
    # Nombre d'échecs consécutifs déclenchant le webhook.
    WEBHOOK_THRESHOLD: int = 3

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @model_validator(mode="after")
    def _reject_insecure_defaults_in_prod(self) -> "Settings":
        # Fail-closed : en production, refuser de démarrer avec le mot de passe
        # de base de données par défaut (visible dans le code source).
        if self.APP_ENV == "production" and ":password@" in self.DATABASE_URL:
            raise ValueError(
                "DATABASE_URL utilise le mot de passe par défaut 'password' en "
                "production. Définissez un mot de passe fort via l'environnement."
            )
        return self


settings = Settings()
