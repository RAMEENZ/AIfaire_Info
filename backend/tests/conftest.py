"""Fixtures partagées par toute la suite."""
import pytest

from app.pipeline import mistral_client


@pytest.fixture(autouse=True)
def _disjoncteur_neuf():
    """Réarme le disjoncteur Mistral avant chaque test.

    Il vit dans l'état du module (comme la cadence d'envoi ou le cache ETag) :
    sans ce réarmement, un test simulant des échecs ouvre le circuit et fait
    échouer les SUIVANTS, qui n'appellent alors plus rien. La panne serait dans
    la suite de tests, pas dans le code.
    """
    mistral_client.reinitialiser_disjoncteur()
    yield
    mistral_client.reinitialiser_disjoncteur()
