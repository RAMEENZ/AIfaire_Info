from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    DATABASE_URL: str = "postgresql+asyncpg://faire_info:password@localhost:5432/faire_info"
    ANTHROPIC_API_KEY: str = ""
    METEO_FRANCE_API_KEY: str = ""
    APP_ENV: Literal["development", "production", "test"] = "development"
    LOG_LEVEL: str = "INFO"

    SCHEDULER_TIMEZONE: str = "Europe/Paris"
    SCHEDULER_HOUR_MORNING: int = 9
    SCHEDULER_HOUR_MIDDAY: int = 13
    SCHEDULER_HOUR_EVENING: int = 19
    SCHEDULER_HOUR_NIGHT: int = 23

    MAX_EVENTS_LIMIT: int = 1000
    DEFAULT_EVENTS_LIMIT: int = 500
    DEFAULT_SINCE_HOURS: int = 48

    # CORS : liste d'origines autorisées, séparées par des virgules.
    # "*" autorise toutes les origines (API publique en lecture seule, sans cookies).
    CORS_ORIGINS: str = "*"

    # Ollama : laissé vide → fallback Anthropic ou règles
    OLLAMA_BASE_URL: str = ""
    OLLAMA_MODEL: str = "mistral:7b-instruct"

    # Activer le fetch du contenu complet des articles avant extraction IA.
    # Désactiver si la VM a un accès internet limité ou pour économiser la bande passante.
    FETCH_FULL_ARTICLES: bool = True

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
