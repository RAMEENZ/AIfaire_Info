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


settings = Settings()
