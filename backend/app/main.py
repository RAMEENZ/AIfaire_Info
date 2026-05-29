import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db, migrate_db
from app.api.routes.events import router as events_router
from app.api.routes.health import router as health_router
from app.pipeline.scheduler import start_scheduler, stop_scheduler, startup_ingestion

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting FAIRE INFO backend (env=%s)", settings.APP_ENV)
    await init_db()
    await migrate_db()
    logger.info("Database initialized")

    start_scheduler()

    import asyncio
    asyncio.create_task(startup_ingestion())

    yield

    stop_scheduler()
    logger.info("FAIRE INFO backend stopped")


app = FastAPI(
    title="FAIRE INFO API",
    description="Agrégateur d'information géolocalisé pour la France",
    version="1.0.0",
    lifespan=lifespan,
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


@app.get("/")
async def root() -> dict:
    return {"service": "FAIRE INFO API", "status": "running", "version": "1.0.0"}
