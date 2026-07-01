import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

logger = logging.getLogger(__name__)


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    from app.models import Event, ConnectorStatus, DailyBrief  # noqa: F401 — registers models in metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def migrate_db() -> None:
    """Idempotent DDL migrations for columns added after initial create_all."""
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE events ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}' NOT NULL"
        ))
        # Suivi de santé des connecteurs (panne transitoire vs chronique).
        await conn.execute(text(
            "ALTER TABLE connector_status ADD COLUMN IF NOT EXISTS last_success TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE connector_status ADD COLUMN IF NOT EXISTS "
            "consecutive_failures INTEGER DEFAULT 0 NOT NULL"
        ))

    # Index trigramme (pg_trgm) pour la recherche texte `q` (ILIKE '%…%' sur
    # titre/résumé/lieu/auteur), aujourd'hui résolue par scan séquentiel. Best
    # effort dans une transaction SÉPARÉE : la création d'extension exige un
    # rôle privilégié — si elle échoue, on retombe simplement sur le scan
    # séquentiel (comportement actuel), sans jamais bloquer le démarrage. Les
    # index existants ne sont pas recréés (IF NOT EXISTS).
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            for col in ("titre", "resume_ia", "lieu_nom", "auteur"):
                await conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS ix_events_{col}_trgm "
                    f"ON events USING gin ({col} gin_trgm_ops)"
                ))
    except Exception as exc:
        logger.info(
            "pg_trgm search indexes not created (%s) — text search falls back "
            "to sequential scan", exc,
        )
