"""Supprime le doublon d'index GiST sur events.geom.

`events.geom` portait DEUX index GiST identiques :

  - `ix_events_geom`, déclaré explicitement dans `models.py` ;
  - `idx_events_geom`, que GeoAlchemy2 attache d'office à toute colonne
    `Geometry` (`spatial_index=True` par défaut).

Le doublon existait en production depuis l'origine. La baseline 0001 le
reproduit À DESSEIN — le rôle d'une baseline est de décrire ce qui EST — en
notant que le supprimer serait « une autre migration, avec sa propre
justification ». La voici.

Ce qu'il coûtait : chaque insertion ou mise à jour d'un événement géolocalisé
écrivait dans deux index GiST au lieu d'un, pour un gain de lecture nul (le
planificateur n'en utilise qu'un). L'ingestion écrit en lots à chaque passe.

Lequel garder : `ix_events_geom`, le seul des deux qui soit déclaré. Le drapeau
`spatial_index=False` posé sur la colonne dans `models.py` empêche GeoAlchemy2
de recréer l'autre sur une base neuve, et garde les modèles en accord avec le
schéma migré — sans quoi la comparaison de `test_schema_migrations.py`
signalerait une dérive à chaque exécution.

`DROP INDEX` prend un verrou ACCESS EXCLUSIVE sur la table le temps de
l'opération. Sur `events`, dont la purge borne la taille à quelques dizaines de
milliers de lignes, c'est de l'ordre de la milliseconde. On ne passe donc pas
par `DROP INDEX CONCURRENTLY`, qui ne peut pas tourner dans la transaction de
migration.

`IF EXISTS` : sur une base neuve construite après ce changement, GeoAlchemy2
n'aura jamais créé l'index — la révision doit alors être un non-événement.

Revision ID: 0006_drop_duplicate_geom_index
Revises: 0005_trgm_search_indexes
Create Date: 2026-08-30

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006_drop_duplicate_geom_index"
down_revision: Union[str, None] = "0005_trgm_search_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_events_geom")


def downgrade() -> None:
    # Recrée l'index de GeoAlchemy2 tel qu'il le créait lui-même.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_geom ON events USING gist (geom)"
    )
