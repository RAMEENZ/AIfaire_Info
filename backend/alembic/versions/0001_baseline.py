"""Baseline — le schéma tel qu'il existait quand Alembic a pris la main.

Cette révision était auparavant un appel à `Base.metadata.create_all()`. C'était
le défaut central du dispositif : une baseline qui vaut « ce que models.py dit
aujourd'hui » n'est pas une baseline. Elle se réécrivait à chaque évolution des
modèles, si bien que rejouer l'historique depuis zéro ne reconstituait pas
l'historique mais l'état courant — et que les révisions suivantes (0002 à 0004)
décrivaient des tables que 0001 venait déjà de créer.

Le DDL est donc explicite et figé. Il ne doit plus jamais changer : toute
évolution du schéma passe par une NOUVELLE révision.

Ce que cette baseline contient, et pourquoi :

- Les trois tables d'origine — `events`, `connector_status`, `daily_briefs`.
  `daily_stats` et `push_subscriptions` arrivent en 0002 et 0003, `is_weekly`
  en 0004 : chaque révision redevient un fait daté.
- Les colonnes que `migrate_db()` ajoutait par `ALTER TABLE … IF NOT EXISTS`
  (`events.tags`, `connector_status.last_success`, `.consecutive_failures`).
  Cette fonction disparaît ; ce qu'elle garantissait devait aller quelque part.
- DEUX index GiST sur `geom` : `ix_events_geom`, déclaré dans `models.py`, et
  `idx_events_geom`, que GeoAlchemy2 crée d'office pour toute colonne
  `Geometry`. Ce doublon existe en production depuis l'origine. Il est
  reproduit ici À DESSEIN : le rôle d'une baseline est de décrire ce qui EST,
  pas ce qui aurait dû être. Le supprimer est un correctif légitime — mais
  c'est une autre migration, avec sa propre justification.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostGIS conditionne events.geom. Présente d'office sur l'image
    # postgis/postgis ; ailleurs, la créer demande un rôle privilégié.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # Base déjà peuplée par l'ancien `create_all` : la migration n'a rien à
    # faire. Le cas se présente sur toute installation antérieure à cette
    # révision — c'est ce que le stamp de `database.run_migrations()` évite,
    # mais on ne dépend pas de lui pour être correct.
    if sa.inspect(op.get_bind()).has_table("events"):
        return

    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("titre", sa.Text(), nullable=False),
        sa.Column("auteur", sa.String(length=256), nullable=True),
        sa.Column("date_publication", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_evenement", sa.DateTime(timezone=True), nullable=True),
        sa.Column("categorie", sa.String(length=64), nullable=False),
        sa.Column("gravite", sa.Integer(), nullable=False),
        sa.Column("lieu_nom", sa.String(length=256), nullable=True),
        sa.Column("lieu_code_insee", sa.String(length=10), nullable=True),
        sa.Column("lieu_lat", sa.Float(), nullable=True),
        sa.Column("lieu_lon", sa.Float(), nullable=True),
        sa.Column("lieu_niveau", sa.String(length=32), nullable=False),
        sa.Column("lieu_confiance_geo", sa.Float(), nullable=False),
        # GeoAlchemy2 attache ici son propre index GiST (idx_events_geom).
        sa.Column("geom", Geometry("POINT", srid=4326), nullable=True),
        sa.Column("resume_ia", sa.Text(), nullable=True),
        sa.Column("tags", ARRAY(sa.String()), server_default="{}", nullable=False),
        sa.Column("cluster_id", sa.String(length=36), nullable=True),
        sa.Column("score_confiance", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_url"),
    )
    op.create_index("ix_events_source", "events", ["source"])
    op.create_index("ix_events_categorie", "events", ["categorie"])
    op.create_index("ix_events_cluster_id", "events", ["cluster_id"])
    op.create_index("ix_events_date_publication", "events", ["date_publication"])
    op.create_index("ix_events_source_gravite", "events", ["source", "gravite"])
    op.create_index("ix_events_gravite_date", "events", ["gravite", "date_publication"])
    op.create_index("ix_events_geom", "events", ["geom"], postgresql_using="gist")

    op.create_table(
        "connector_status",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("last_run", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_count", sa.Integer(), nullable=False),
        # Distingue un connecteur qui n'a jamais marché d'un connecteur
        # momentanément en panne.
        sa.Column("last_success", sa.DateTime(timezone=True), nullable=True),
        # Panne transitoire (« dégradé ») vs chronique (« erreur »).
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )

    op.create_table(
        "daily_briefs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date"),
    )


def downgrade() -> None:
    # Une baseline ne se défait pas : on ne détruit jamais les données d'un
    # déploiement par le retour arrière de sa première révision.
    pass
