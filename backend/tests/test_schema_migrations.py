"""Le schéma a désormais UN seul maître : la chaîne de migrations Alembic.

Trois mécanismes coexistaient — `create_all` au démarrage, du DDL manuel dans
`migrate_db()`, et des révisions Alembic que rien n'exécutait jamais. Une
colonne ajoutée avait trois domiciles possibles, et celui que le README
recommandait n'était pas celui qui s'exécutait.

Ces tests verrouillent les deux propriétés qui rendent l'unification sûre :

1. **Une base neuve migrée == `models.py`.** Sans quoi la chaîne de migrations
   et l'ORM divergeraient en silence, et deux installations n'auraient pas le
   même schéma. C'est déjà arrivé : avant ce travail, 0002 et 0003 déclaraient
   des `server_default` absents des modèles.
2. **Une base construite par l'ANCIEN chemin est estampillée, pas reconstruite.**
   C'est le cas de la production. Le jour de la bascule, la migration doit être
   inerte : même schéma, mêmes données.

Ils ne s'exécutent que si `TEST_DATABASE_URL` est défini (la CI fournit un
service PostGIS) et créent leur propre base jetable, pour ne pas marcher sur
celle des tests d'API.
"""
import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL non défini : tests de schéma ignorés"
)

# Écarts attendus entre le schéma migré et `models.py`, et pourquoi :
#
# - `spatial_ref_sys` appartient à PostGIS, pas à l'application.
# - Les index trigrammes sont créés par la révision 0005 et volontairement
#   ABSENTS des modèles : ils dépendent de l'extension `pg_trgm`, dont la
#   création demande un rôle privilégié. Les déclarer dans `models.py` ferait
#   échouer un `create_all` là où l'extension manque, alors que la recherche
#   doit simplement retomber sur le parcours séquentiel.
#
# Tout autre écart est une dérive réelle et doit faire échouer le test.
_ECARTS_ATTENDUS = {
    ("remove_table", "spatial_ref_sys"),
    ("remove_index", "ix_events_titre_trgm"),
    ("remove_index", "ix_events_resume_ia_trgm"),
    ("remove_index", "ix_events_lieu_nom_trgm"),
    ("remove_index", "ix_events_auteur_trgm"),
}


def _etiquette(ecart) -> tuple:
    """(type, nom) d'un écart rendu par `compare_metadata`."""
    genre = ecart[0]
    objet = ecart[1]
    return genre, getattr(objet, "name", str(objet))


async def _base_jetable():
    """Crée une base vide dédiée et renvoie son URL. PostGIS activée."""
    from sqlalchemy import text

    nom = f"schema_test_{uuid.uuid4().hex[:12]}"
    # `CREATE DATABASE` refuse de tourner dans une transaction.
    admin = create_async_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{nom}"'))
    await admin.dispose()

    url = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/" + nom
    moteur = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with moteur.connect() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    await moteur.dispose()
    return nom, url


async def _supprimer(nom: str) -> None:
    from sqlalchemy import text

    admin = create_async_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{nom}" WITH (FORCE)'))
    await admin.dispose()


@pytest.fixture
async def base_neuve(monkeypatch):
    """Base vide, avec `app.database` reconfiguré pour pointer dessus."""
    import app.database as db

    nom, url = await _base_jetable()
    moteur = create_async_engine(url)
    monkeypatch.setattr(db, "engine", moteur)
    try:
        yield moteur
    finally:
        await moteur.dispose()
        await _supprimer(nom)


async def _ecarts(moteur):
    """Écarts entre le schéma réel et `models.py`, via l'autogénérateur."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.database import Base
    import app.models  # noqa: F401 — enregistre les tables dans metadata

    def comparer(conn):
        return compare_metadata(MigrationContext.configure(conn), Base.metadata)

    async with moteur.connect() as conn:
        return await conn.run_sync(comparer)


async def _version_alembic(moteur) -> str | None:
    """Révision enregistrée, ou None si la base ignore encore Alembic."""
    from sqlalchemy import text

    async with moteur.connect() as conn:
        existe = await conn.execute(text("SELECT to_regclass('alembic_version')"))
        if existe.scalar_one() is None:
            return None
        res = await conn.execute(text("SELECT version_num FROM alembic_version"))
        ligne = res.first()
        return ligne[0] if ligne else None


async def test_base_neuve_migree_correspond_aux_modeles(base_neuve):
    """`alembic upgrade head` sur une base vierge doit produire `models.py`."""
    from app.database import run_migrations

    await run_migrations()

    inattendus = [e for e in await _ecarts(base_neuve) if _etiquette(e) not in _ECARTS_ATTENDUS]
    assert not inattendus, (
        "Le schéma produit par les migrations diverge de models.py : "
        f"{[_etiquette(e) for e in inattendus]}"
    )


async def test_base_neuve_est_au_dernier_niveau(base_neuve):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.database import _ALEMBIC_INI, run_migrations

    await run_migrations()

    tete = ScriptDirectory.from_config(Config(str(_ALEMBIC_INI))).get_current_head()
    assert await _version_alembic(base_neuve) == tete


async def test_les_index_trigrammes_sont_bien_crees(base_neuve):
    """Ils n'existaient que dans `migrate_db()`. Les perdre en unifiant les
    mécanismes aurait été silencieux : la recherche aurait continué de
    fonctionner, en parcours séquentiel."""
    from sqlalchemy import text

    from app.database import run_migrations

    await run_migrations()
    async with base_neuve.connect() as conn:
        res = await conn.execute(text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename='events' AND indexname LIKE '%%_trgm'"
        ))
        noms = {r[0] for r in res}
    assert noms == {
        "ix_events_titre_trgm", "ix_events_resume_ia_trgm",
        "ix_events_lieu_nom_trgm", "ix_events_auteur_trgm",
    }


async def test_base_preexistante_est_estampillee_et_non_reconstruite(base_neuve):
    """Le cas de la production : schéma déjà là, aucune trace d'Alembic.

    On reconstitue l'ancien chemin (`create_all`), on insère une ligne, puis on
    bascule. La migration doit être inerte : mêmes objets, données intactes,
    et la base marquée au dernier niveau.
    """
    from sqlalchemy import text

    from app.database import Base, run_migrations
    import app.models  # noqa: F401

    async with base_neuve.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "INSERT INTO events (id, source, source_url, titre, date_publication, "
            "categorie, gravite, lieu_niveau, lieu_confiance_geo, score_confiance, "
            "created_at, tags) VALUES ('evt-temoin','presse_rss','https://exemple.fr/a',"
            "'Un titre', now(), 'meteo', 2, 'commune', 0.9, 1.0, now(), '{}')"
        ))

    assert await _version_alembic(base_neuve) is None, "pas encore d'alembic_version"
    avant = {_etiquette(e) for e in await _ecarts(base_neuve)}

    await run_migrations()

    apres = {_etiquette(e) for e in await _ecarts(base_neuve)}
    # Les index trigrammes apparaissent (0005) ; rien d'autre ne doit bouger.
    assert apres - avant <= _ECARTS_ATTENDUS
    assert not (avant - apres - _ECARTS_ATTENDUS)

    async with base_neuve.connect() as conn:
        res = await conn.execute(text("SELECT count(*) FROM events WHERE id='evt-temoin'"))
        assert res.scalar_one() == 1, "la bascule ne doit toucher aucune donnée"

    assert await _version_alembic(base_neuve) is not None, "la base doit être estampillée"


async def test_rejouer_les_migrations_ne_fait_rien(base_neuve):
    """Le conteneur peut être recréé par autoheal à tout moment : le second
    passage doit être un non-événement."""
    from app.database import run_migrations

    await run_migrations()
    version = await _version_alembic(base_neuve)
    await run_migrations()
    assert await _version_alembic(base_neuve) == version
    inattendus = [e for e in await _ecarts(base_neuve) if _etiquette(e) not in _ECARTS_ATTENDUS]
    assert not inattendus
