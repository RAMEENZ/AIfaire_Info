"""daily_stats — agrégats quotidiens (jour × catégorie × département).

Conserve les tendances longues alors que les événements bruts sont purgés
après 36 h – 30 j. Remplie avant chaque purge (upsert idempotent).

Revision ID: 0002_daily_stats
Revises: 0001_baseline
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_daily_stats"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent : init_db (create_all au démarrage) crée déjà les nouvelles
    # tables — si le backend a booté avant `alembic upgrade`, la table existe.
    # Dans ce cas la migration n'a rien à faire (équivaut à un stamp).
    if sa.inspect(op.get_bind()).has_table("daily_stats"):
        return
    op.create_table(
        "daily_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("jour", sa.Date(), nullable=False),
        sa.Column("categorie", sa.String(length=64), nullable=False),
        # "" = national/non localisé (pas NULL : les NULL sont distincts dans
        # une contrainte unique Postgres, ce qui casserait l'upsert ON CONFLICT).
        # PAS de server_default : `models.py` n'en déclare pas, et la table est
        # CRÉÉE ici, pas altérée — un défaut serveur n'est nécessaire que pour
        # ajouter une colonne NOT NULL à une table déjà peuplée. En déclarer un
        # ici faisait diverger le schéma produit par Alembic de celui produit
        # par l'ORM : deux installations, deux schémas.
        sa.Column("departement", sa.String(length=3), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "jour", "categorie", "departement", name="uq_daily_stats_jour_cat_dept"
        ),
    )
    op.create_index("ix_daily_stats_jour", "daily_stats", ["jour"])


def downgrade() -> None:
    op.drop_index("ix_daily_stats_jour", table_name="daily_stats")
    op.drop_table("daily_stats")
