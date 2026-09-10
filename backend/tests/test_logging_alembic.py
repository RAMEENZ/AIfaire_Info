"""Alembic ne doit pas bâillonner l'application.

`alembic/env.py` appelait `fileConfig(config.config_file_name)` sans condition.
Or `run_migrations()` s'exécute à CHAQUE démarrage du backend, dans le process
de l'application — et `fileConfig()` y fait deux dégâts :

1. `disable_existing_loggers=True` (le défaut) désactive tous les loggers déjà
   créés. Ceux de `app.*` naissent à l'import de `main.py`, donc avant.
2. Elle remplace les handlers de la racine par ceux d'alembic.ini, décrochant
   le RotatingFileHandler que `main.py` installe sur LOG_DIR.

Effet mesuré en production : muet du 30/08/2026 (bascule Alembic) au 10/09.
Quand Mistral est tombé le 03/09, plus rien n'écrivait — ni fichier, ni stdout.
La panne a duré une semaine sans laisser une ligne, alors que le code sait
parfaitement la journaliser (`Mistral … : HTTP 429`).

Ces tests verrouillent les deux moitiés du correctif : le drapeau, et surtout
la garde qui empêche l'appel quand l'application pilote Alembic.
"""
import ast
import logging
from contextlib import contextmanager
from logging.config import fileConfig
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_ALEMBIC_INI = _BACKEND / "alembic.ini"
_ENV_PY = _BACKEND / "alembic" / "env.py"

# Un logger applicatif représentatif : créé à l'import du module, comme tous
# les autres, donc déjà présent quand les migrations s'exécutent.
_LOGGER_APP = "app.pipeline.brief"


@contextmanager
def _logging_intact():
    """Restaure la configuration de logging : `fileConfig` est global."""
    racine = logging.getLogger()
    handlers, niveau = list(racine.handlers), racine.level
    etats = {
        nom: obj.disabled
        for nom, obj in logging.Logger.manager.loggerDict.items()
        if isinstance(obj, logging.Logger)
    }
    try:
        yield
    finally:
        racine.handlers[:] = handlers
        racine.setLevel(niveau)
        for nom, disabled in etats.items():
            obj = logging.Logger.manager.loggerDict.get(nom)
            if isinstance(obj, logging.Logger):
                obj.disabled = disabled


def test_fileconfig_par_defaut_bâillonne_les_loggers_applicatifs():
    """Caractérise le défaut qui a rendu le backend muet.

    Ce test ne protège pas le correctif : il documente POURQUOI il existe. S'il
    venait à échouer (changement de comportement de la bibliothèque standard),
    c'est la justification du correctif qu'il faudrait réexaminer, pas le test.
    """
    with _logging_intact():
        logger = logging.getLogger(_LOGGER_APP)
        logger.disabled = False
        fileConfig(str(_ALEMBIC_INI))
        assert logger.disabled is True, (
            "fileConfig() par défaut est censée désactiver les loggers existants — "
            "si ce n'est plus le cas, la garde de env.py peut être réexaminée"
        )


def test_le_drapeau_preserve_les_loggers_applicatifs():
    """En ligne de commande, configurer le logging ne doit faire taire personne."""
    with _logging_intact():
        logger = logging.getLogger(_LOGGER_APP)
        logger.disabled = False
        fileConfig(str(_ALEMBIC_INI), disable_existing_loggers=False)
        assert logger.disabled is False


def _appel_fileconfig(arbre: ast.Module) -> ast.Call:
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Call) and getattr(noeud.func, "id", "") == "fileConfig":
            return noeud
    raise AssertionError("aucun appel à fileConfig() trouvé dans alembic/env.py")


def test_env_py_ne_configure_pas_le_logging_quand_l_application_pilote():
    """La garde elle-même, lue dans le source d'env.py.

    `env.py` n'est pas importable hors d'Alembic (il exécute les migrations à
    l'import) : on inspecte donc son arbre syntaxique. La propriété vérifiée est
    précise — l'appel doit être gardé par l'absence de `attributes["connection"]`,
    le discriminant déjà utilisé par `run_migrations_online()` : l'application le
    pose, la ligne de commande jamais.
    """
    arbre = ast.parse(_ENV_PY.read_text(encoding="utf-8"))
    appel = _appel_fileconfig(arbre)

    drapeau = [
        kw for kw in appel.keywords
        if kw.arg == "disable_existing_loggers" and kw.value.value is False
    ]
    assert drapeau, "fileConfig() doit passer disable_existing_loggers=False"

    garde = next(
        (n for n in ast.walk(arbre)
         if isinstance(n, ast.If) and any(appel is c for c in ast.walk(n))),
        None,
    )
    assert garde is not None, "l'appel à fileConfig() doit être gardé par un `if`"
    source_garde = ast.unparse(garde.test)
    assert "connection" in source_garde and "attributes" in source_garde, (
        "la garde doit exclure le cas où l'application fournit la connexion "
        f"(condition trouvée : {source_garde})"
    )
