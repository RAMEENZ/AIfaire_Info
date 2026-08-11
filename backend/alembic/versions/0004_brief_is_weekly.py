"""Marqueur explicite du brief hebdomadaire.

Le caractère hebdomadaire d'un brief était déduit de deux heuristiques
divergentes : la présence du mot « semaine » dans le texte (garde anti-double
génération du lundi) et un nombre d'événements > 100 (affichage côté API). Un
brief quotidien chargé franchissait le seuil, un brief hebdomadaire pouvait
omettre le mot. On enregistre le fait au lieu de le deviner.

Revision ID: 0004_brief_is_weekly
Revises: 0003_push_subscriptions
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_brief_is_weekly"
down_revision = "0003_push_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent : init_db/create_all a pu créer la colonne au démarrage sur les
    # bases existantes (cf. 0002 et 0003).
    inspector = sa.inspect(op.get_bind())
    if "daily_briefs" not in inspector.get_table_names():
        return
    colonnes = {c["name"] for c in inspector.get_columns("daily_briefs")}
    if "is_weekly" in colonnes:
        return
    op.add_column(
        "daily_briefs",
        sa.Column("is_weekly", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Reprise de l'existant avec l'ancienne heuristique — c'est la meilleure
    # information disponible pour les briefs déjà enregistrés.
    op.execute(
        "UPDATE daily_briefs SET is_weekly = true "
        "WHERE lower(content) LIKE '%semaine%' AND event_count > 100"
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "daily_briefs" in inspector.get_table_names():
        colonnes = {c["name"] for c in inspector.get_columns("daily_briefs")}
        if "is_weekly" in colonnes:
            op.drop_column("daily_briefs", "is_weekly")
