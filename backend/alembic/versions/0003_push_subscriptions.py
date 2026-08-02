"""push_subscriptions — abonnements Web Push.

Idempotente comme 0002 : init_db (create_all au démarrage) crée déjà les
nouvelles tables, donc la migration ne fait rien si le backend a booté avant.

Revision ID: 0003_push_subscriptions
Revises: 0002_daily_stats
Create Date: 2026-07-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_push_subscriptions"
down_revision: Union[str, None] = "0002_daily_stats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("push_subscriptions"):
        return
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        # L'endpoint du service de push identifie l'abonnement de façon unique.
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        # "" = alertes nationales ; sinon code département.
        sa.Column("departement", sa.String(length=3), nullable=False, server_default=""),
        sa.Column("gravite_min", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_push_dept_gravite", "push_subscriptions", ["departement", "gravite_min"])


def downgrade() -> None:
    op.drop_index("ix_push_dept_gravite", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
