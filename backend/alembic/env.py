"""Environnement Alembic — mode asynchrone (asyncpg), URL lue depuis la config
de l'application (app.config.settings), métadonnées depuis les modèles ORM."""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from app.config import settings
from app.database import Base
import app.models  # noqa: F401 — enregistre Event/ConnectorStatus/DailyBrief dans metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# URL depuis la config applicative (.env / variables d'environnement) — jamais
# en dur dans alembic.ini.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Mode offline : génère le SQL sans se connecter (alembic upgrade --sql)."""
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    # Connexion fournie par l'appelant (app.database.run_migrations, qui joue
    # les migrations au démarrage du backend) : on la réutilise au lieu
    # d'ouvrir un second moteur. Sans cela, l'application et Alembic
    # ouvriraient deux connexions concurrentes sur la même base, et la
    # migration s'exécuterait hors de la transaction de l'appelant.
    connexion = config.attributes.get("connection")
    if connexion is not None:
        do_run_migrations(connexion)
        return
    # Invocation en ligne de commande (`alembic upgrade head`) : Alembic est
    # seul, il ouvre son propre moteur.
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
