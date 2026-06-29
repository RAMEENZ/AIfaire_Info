"""Verrouille la taxonomie : source unique (app.categories) réellement partagée
par l'API et l'extracteur, et présence des nouvelles catégories (sport…)."""
from app.api.routes.events import VALID_CATEGORIES
from app.categories import CATEGORIES, CATEGORY_SET, DEFAULT_CATEGORY
from app.pipeline.extractor import SYSTEM_PROMPT, SYSTEM_PROMPT_SMALL, _validate_extraction


def test_api_validation_uses_the_single_source():
    assert VALID_CATEGORIES is CATEGORY_SET


def test_new_topics_are_first_class_categories():
    for c in ("sport", "economie", "politique", "culture"):
        assert c in CATEGORY_SET


def test_prompts_have_no_unsubstituted_placeholder():
    assert "__CATEGORIES" not in SYSTEM_PROMPT
    assert "__CATEGORIES" not in SYSTEM_PROMPT_SMALL
    # La liste canonique est bien injectée dans le grand prompt.
    assert '"sport"' in SYSTEM_PROMPT


def test_extractor_accepts_sport_and_coerces_unknown():
    assert _validate_extraction({"categorie": "sport"})["categorie"] == "sport"
    assert _validate_extraction({"categorie": "licorne"})["categorie"] == DEFAULT_CATEGORY
    # Pas de doublon dans la liste canonique.
    assert len(CATEGORIES) == len(set(CATEGORIES))
