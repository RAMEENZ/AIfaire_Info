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

# Configuration du logging : réservée à l'invocation EN LIGNE DE COMMANDE.
#
# `fileConfig()` fait deux choses destructrices quand l'application pilote
# Alembic dans son propre process (au démarrage, via app.database.run_migrations) :
#
#   1. `disable_existing_loggers=True` (le défaut) DÉSACTIVE tous les loggers
#      déjà créés. Ceux de `app.*` naissent à l'import de `main.py`, donc bien
#      avant : `app.pipeline.brief`, `app.pipeline.extractor`, `app.pipeline.robots`…
#      cessaient d'émettre quoi que ce soit, à n'importe quel niveau.
#   2. Elle REMPLACE les handlers de la racine par ceux d'alembic.ini (une
#      console stderr, racine à WARNING) — décrochant au passage le
#      RotatingFileHandler que `main.py` venait d'installer sur LOG_DIR.
#
# Mesuré en production : après la bascule vers Alembic (30/08/2026), le backend
# est devenu MUET — plus une ligne applicative dans `logs/backend.log` ni sur
# stdout, la dernière étant celle d'Alembic elle-même, à l'instant du basculement.
# Quand Mistral est tombé le 03/09, aucune trace n'a été écrite : c'est
# exactement la cécité que les logs persistants avaient été ajoutés pour
# supprimer, après la panne de 07/2026.
#
# `config.attributes["connection"]` est le discriminant, déjà utilisé plus bas
# par run_migrations_online() : l'application le pose, la CLI jamais. En CLI on
# configure donc le logging, mais sans faire taire les loggers existants.
if config.config_file_name is not None and config.attributes.get("connection") is None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

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
