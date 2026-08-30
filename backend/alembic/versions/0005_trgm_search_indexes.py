"""Index trigrammes (pg_trgm) pour la recherche texte de /events.

Le paramètre `q` de `/events` fait un `ILIKE '%…%'` sur titre, résumé, lieu et
auteur — un motif que seul un index GIN trigramme peut servir autrement que par
un parcours séquentiel.

Ces index existaient déjà, mais nulle part dans l'historique : ils étaient créés
par `migrate_db()`, la fonction de DDL manuel que cette série de migrations
remplace. Sans cette révision, unifier les mécanismes les aurait silencieusement
supprimés des bases neuves — la recherche aurait continué de fonctionner, en
parcours séquentiel, et personne ne l'aurait vu avant que la table ne grossisse.

BEST EFFORT, comme l'était `migrate_db()` : créer une extension demande un rôle
privilégié, dont on ne dispose pas partout. En cas d'échec on trace et on
continue — la recherche retombe sur le parcours séquentiel, exactement le
comportement d'avant. Faire échouer un démarrage pour un index de confort serait
un mauvais échange.

Revision ID: 0005_trgm_search_indexes
Revises: 0004_brief_is_weekly
Create Date: 2026-08-30

"""
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_trgm_search_indexes"
down_revision: Union[str, None] = "0004_brief_is_weekly"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_COLONNES = ("titre", "resume_ia", "lieu_nom", "auteur")


def upgrade() -> None:
    # Point de sauvegarde : si la création échoue faute de privilèges, on
    # annule CE bloc sans emporter la transaction de migration entière — sinon
    # la révision serait marquée en échec et le démarrage bloqué. `CREATE
    # EXTENSION` et `CREATE INDEX` (non concurrent) étant transactionnels sous
    # PostgreSQL, un savepoint suffit ; pas besoin d'un bloc autocommit, qui ne
    # fonctionnerait pas quand les migrations tournent sur une connexion
    # fournie par l'application.
    bind = op.get_bind()
    try:
        with bind.begin_nested():
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            for col in _COLONNES:
                bind.execute(sa.text(
                    f"CREATE INDEX IF NOT EXISTS ix_events_{col}_trgm "
                    f"ON events USING gin ({col} gin_trgm_ops)"
                ))
    except Exception as exc:
        logger.warning(
            "Index trigrammes non créés (%s) — la recherche texte retombe sur "
            "le parcours séquentiel, comme avant cette révision.", exc,
        )


def downgrade() -> None:
    for col in _COLONNES:
        op.execute(f"DROP INDEX IF EXISTS ix_events_{col}_trgm")
    # L'extension n'est pas supprimée : d'autres objets peuvent en dépendre.
