import logging
from pathlib import Path

import sqlalchemy as sa
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


# Chemin de alembic.ini, à côté du paquet `app/`.
_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

# Révision à estampiller sur une base qui préexiste à Alembic. Voir
# `_stamp_puis_upgrade`.
_BASELINE = "0001_baseline"


def _stamp_puis_upgrade(connection) -> None:
    """Amène la base au dernier niveau de schéma. Trois cas, un seul chemin.

    1. **Base neuve** — ni `alembic_version` ni `events` : `upgrade head`
       rejoue tout l'historique et construit le schéma.
    2. **Base antérieure à Alembic** — pas d'`alembic_version`, mais `events`
       existe : c'est une base construite par l'ancien couple
       `create_all` + `migrate_db()`. On l'estampille à la baseline, puis on
       applique la suite. Les révisions 0002 à 0005 sont toutes gardées
       (`has_table`, `IF NOT EXISTS`) : sur une telle base, elles ne font rien.
       C'est ce qui rend la bascule sans effet sur l'existant.
    3. **Base déjà migrée** — `alembic_version` présente : `upgrade head`, et
       il n'y a en général rien à faire.

    Le cas 2 est le seul délicat, et il ne se produit qu'une fois par base.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    # Alembic réutilise CETTE connexion (voir alembic/env.py) au lieu d'ouvrir
    # un second moteur sur la même base.
    cfg.attributes["connection"] = connection

    tables = set(sa.inspect(connection).get_table_names())
    if "alembic_version" not in tables and "events" in tables:
        logger.info(
            "Base antérieure à Alembic détectée (tables présentes, pas de "
            "alembic_version) — estampillage à %s avant migration.", _BASELINE,
        )
        command.stamp(cfg, _BASELINE)

    command.upgrade(cfg, "head")


async def run_migrations() -> None:
    """Applique les migrations Alembic au démarrage.

    Remplace l'ancien couple `init_db()` (create_all) + `migrate_db()` (DDL
    manuel). Ces deux fonctions coexistaient avec Alembic, qui n'était jamais
    exécuté : une colonne ajoutée avait trois domiciles possibles, et celui que
    le README recommandait n'était pas celui qui s'exécutait.

    Le schéma continue d'être géré automatiquement au démarrage — ce n'est pas
    une nouveauté, c'est ce que faisait déjà `migrate_db()`. Le conteneur peut
    être recréé par autoheal à tout moment : il doit rester autonome.

    On laisse remonter toute exception : un backend qui démarre sur un schéma
    qu'il n'a pas pu mettre à niveau produirait des erreurs bien plus difficiles
    à lire que le refus de démarrer.
    """
    from app.models import Event, ConnectorStatus, DailyBrief  # noqa: F401 — enregistre les modèles
    async with engine.begin() as conn:
        await conn.run_sync(_stamp_puis_upgrade)
    logger.info("Schéma à jour (alembic upgrade head)")
