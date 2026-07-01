import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db, migrate_db
from app.api.routes.events import router as events_router
from app.api.routes.health import router as health_router
from app.pipeline.geocoder import close_geo_client
from app.pipeline.scheduler import start_scheduler, stop_scheduler, startup_ingestion

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting FAIRE INFO backend (env=%s)", settings.APP_ENV)

    # Avertissement de sécurité : mot de passe DB par défaut en production
    if settings.APP_ENV == "production" and "password" in settings.DATABASE_URL:
        logger.warning(
            "SECURITY: DATABASE_URL contains the default password 'password'. "
            "Set POSTGRES_PASSWORD in your environment before going live."
        )
    if settings.APP_ENV == "production" and not settings.INGEST_API_KEY:
        logger.warning(
            "SECURITY: INGEST_API_KEY is not set — POST /api/ingest/run is unprotected. "
            "Set INGEST_API_KEY in your environment to restrict access."
        )

    await init_db()
    await migrate_db()
    logger.info("Database initialized")

    start_scheduler()

    import asyncio

    def _on_startup_done(task: asyncio.Task) -> None:
        exc = task.exception() if not task.cancelled() else None
        if exc:
            logger.error("startup_ingestion raised an unhandled exception: %s", exc)

    task = asyncio.create_task(startup_ingestion())
    task.add_done_callback(_on_startup_done)

    yield

    stop_scheduler()
    await close_geo_client()
    logger.info("FAIRE INFO backend stopped")


app = FastAPI(
    title="FAIRE INFO API",
    description="Agrégateur d'information géolocalisé pour la France",
    version="1.0.0",
    lifespan=lifespan,
    # Docs interactives désactivées par défaut (ENABLE_DOCS=false) : on n'expose
    # pas Swagger/ReDoc/openapi.json publiquement. Activable en local.
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
)

# API publique en lecture seule : pas de cookies/credentials, donc on peut
# autoriser toutes les origines en toute sécurité (la combinaison "*" +
# allow_credentials=True est rejetée par les navigateurs et serait invalide).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(events_router, prefix="/api", tags=["events"])
app.include_router(health_router, prefix="/api", tags=["health"])


API_VERSION = "1.0.0"
# Commit déployé, injecté à l'exécution (docker run -e GIT_SHA=$(git rev-parse …)).
# Facilite le diagnostic : « quelle version tourne réellement ? »
GIT_SHA = os.environ.get("GIT_SHA", "")


@app.get("/")
async def root() -> dict:
    return {
        "service": "FAIRE INFO API",
        "status": "running",
        "version": API_VERSION,
        "commit": GIT_SHA or None,
    }
