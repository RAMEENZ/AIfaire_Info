"""Baseline — schéma courant (events, connector_status, daily_briefs).

Point de départ des migrations versionnées :
- **Base existante** (créée par init_db/create_all) : ne PAS exécuter upgrade ;
  lancer une seule fois `alembic stamp 0001_baseline` pour marquer la base
  comme déjà à ce niveau.
- **Base neuve** : `alembic upgrade head` crée tout le schéma.

La création s'appuie sur les modèles ORM (source unique de vérité,
`checkfirst=True` → idempotent). Les migrations SUIVANTES doivent en revanche
être écrites avec des opérations `op.*` explicites, pour rester rejouables
même quand les modèles auront continué d'évoluer.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-02

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extension PostGIS requise par events.geom. Déjà présente sur l'image
    # postgis/postgis ; ailleurs, nécessite un rôle privilégié.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    from app.database import Base
    import app.models  # noqa: F401 — enregistre les tables dans metadata

    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Baseline : pas de retour arrière automatique (on ne détruit jamais les
    # données d'un déploiement par un downgrade de baseline).
    pass
