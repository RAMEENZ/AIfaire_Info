from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


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
