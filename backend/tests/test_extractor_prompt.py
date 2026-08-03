"""Tests des prompts d'extraction et de la validation de leurs sorties.

Le prompt et le validateur forment un même contrat : ce que le prompt exige, le
validateur doit l'accepter ; ce que le prompt interdit, le validateur doit le
rattraper (un LLM désobéit régulièrement). Ces tests vérifient les deux faces.
"""
import json
import re

import pytest

from app.categories import CATEGORIES
from app.pipeline import extractor
from app.pipeline.extractor import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_SMALL,
    _USELESS_TAGS,
    _validate_extraction,
)


# ── Contrat du prompt ───────────────────────────────────────────────────────

@pytest.mark.parametrize("prompt", [SYSTEM_PROMPT, SYSTEM_PROMPT_SMALL], ids=["complet", "court"])
def test_les_categories_sont_injectees_depuis_la_source_unique(prompt):
    """La liste des catégories vit dans app.categories. Si elle cesse d'être
    injectée, le modèle propose des catégories hors taxonomie, silencieusement
    coercées en « actualite »."""
    assert "__CATEGORIES_" not in prompt, "gabarit non substitué"
    for cat in CATEGORIES:
        assert cat in prompt, f"catégorie {cat!r} absente du prompt"


@pytest.mark.parametrize("prompt", [SYSTEM_PROMPT, SYSTEM_PROMPT_SMALL], ids=["complet", "court"])
def test_le_prompt_freine_le_repli_sur_actualite(prompt):
    """« actualite » représentait 32 % des événements : un fourre-tout qui vide
    les filtres de leur sens. Le prompt doit explicitement le décourager."""
    assert re.search(r"actualite.{0,40}(que si|dernier recours)", prompt, re.I | re.S)


@pytest.mark.parametrize("prompt", [SYSTEM_PROMPT, SYSTEM_PROMPT_SMALL], ids=["complet", "court"])
def test_le_prompt_demande_lieu_type(prompt):
    assert "lieu_type" in prompt
    for niveau in ("commune", "departement", "region", "national"):
        assert niveau in prompt


@pytest.mark.parametrize("prompt", [SYSTEM_PROMPT, SYSTEM_PROMPT_SMALL], ids=["complet", "court"])
def test_le_prompt_ecarte_les_faux_lieux(prompt):
    """Clubs et journaux portent des noms de villes : sans garde-fou, « Paris FC »
    plante un marqueur à Paris pour un match joué ailleurs."""
    assert "Paris FC" in prompt
    assert "Nice-Matin" in prompt


@pytest.mark.parametrize("prompt", [SYSTEM_PROMPT, SYSTEM_PROMPT_SMALL], ids=["complet", "court"])
def test_le_prompt_interdit_les_tags_creux(prompt):
    assert "france" in prompt.lower()
    assert re.search(r'"(actualité|actualite)"', prompt)


def test_le_prompt_prefere_la_commune_a_la_region():
    assert "Quimper" in SYSTEM_PROMPT and "Bretagne" in SYSTEM_PROMPT


def test_le_prompt_reserve_la_gravite_3():
    """Une gravité 3 déclenche des notifications push : elle doit rester rare."""
    assert re.search(r"3 = URGENCE", SYSTEM_PROMPT)
    assert "TRÈS RARE" in SYSTEM_PROMPT


@pytest.mark.parametrize("prompt", [SYSTEM_PROMPT, SYSTEM_PROMPT_SMALL], ids=["complet", "court"])
def test_les_exemples_du_prompt_sont_du_json_valide_et_conforme(prompt):
    """Un exemple malformé ou incohérent apprend l'erreur au modèle. On revalide
    donc chaque exemple par le validateur de production."""
    # Le gabarit de format ({"lieu_nom": "...", …}) n'est pas un exemple :
    # ses valeurs sont des espaces réservés, pas des données à valider.
    exemples = [
        ligne for ligne in prompt.splitlines()
        if ligne.startswith('{"lieu_nom"') and '"lieu_nom": "..."' not in ligne
    ]
    assert len(exemples) >= 2, "au moins deux exemples attendus (few-shot)"
    for ligne in exemples:
        brut = json.loads(ligne)  # lève si le JSON est invalide
        valide = _validate_extraction(brut)
        # Le validateur ne doit rien avoir eu à corriger.
        assert valide["categorie"] == brut["categorie"], f"catégorie hors taxonomie : {ligne}"
        assert valide["lieu_type"] == brut["lieu_type"], f"lieu_type invalide : {ligne}"
        assert valide["tags"] == [t.lower() for t in brut["tags"]], f"tag creux : {ligne}"
        assert valide["gravite"] == brut["gravite"]


@pytest.mark.parametrize("prompt", [SYSTEM_PROMPT, SYSTEM_PROMPT_SMALL], ids=["complet", "court"])
def test_les_prompts_sont_en_caracteres_latins(prompt):
    """Garde-fou anti-coquille : une frappe malheureuse peut glisser un
    caractère d'un autre alphabet dans le prompt sans qu'aucun test ne bronche."""
    intrus = sorted({c for c in prompt if ord(c) > 0x2FFF})
    assert not intrus, f"caractères non latins dans le prompt : {intrus}"


def test_le_prompt_court_reste_court():
    """Il existe pour les modèles < 3 B, qui décrochent sur les longues
    consignes : s'il grossit comme l'autre, il perd sa raison d'être."""
    assert len(SYSTEM_PROMPT_SMALL) < len(SYSTEM_PROMPT) / 2


# ── Validation des sorties ──────────────────────────────────────────────────

def test_les_tags_creux_sont_filtres():
    out = _validate_extraction({
        "lieu_nom": "Colmar", "categorie": "culture",
        "tags": ["France", "Actualité", "halle", "société", "patrimoine"],
    })
    assert out["tags"] == ["halle", "patrimoine"]


def test_les_tags_sont_normalises_et_plafonnes():
    out = _validate_extraction({"tags": ["Grève", "SNCF", "TRAIN", "retard", "trafic", "sixième"]})
    assert out["tags"] == ["grève", "sncf", "train", "retard", "trafic"]


def test_aucun_tag_creux_ne_survit_a_la_liste_noire():
    out = _validate_extraction({"tags": sorted(_USELESS_TAGS)})
    assert out["tags"] == []


def test_un_tag_qui_repete_le_lieu_est_ecarte():
    """Observé en production : lieu_nom « Leyme » et tag « leyme ». Le lieu est
    déjà un champ ; le répéter en tag ne fait filtrer personne."""
    out = _validate_extraction({
        "lieu_nom": "Leyme", "categorie": "culture",
        "tags": ["opéra", "leyme", "puccini"],
    })
    assert out["tags"] == ["opéra", "puccini"]


def test_le_tag_du_lieu_est_ecarte_malgre_accents_et_traits_dunion():
    out = _validate_extraction({
        "lieu_nom": "Mont-de-Marsan", "categorie": "incendie",
        "tags": ["mont de marsan", "parking", "véhicules"],
    })
    assert out["tags"] == ["parking", "véhicules"]


def test_un_tag_qui_repete_la_categorie_est_ecarte():
    out = _validate_extraction({
        "lieu_nom": "Vénissieux", "categorie": "ordre_public",
        "tags": ["ordre public", "cambriolage", "interpellation"],
    })
    assert out["tags"] == ["cambriolage", "interpellation"]


def test_les_tags_en_double_sont_fusionnes():
    out = _validate_extraction({"tags": ["Grève", "grève", "GRÈVE", "sncf"]})
    assert out["tags"] == ["grève", "sncf"]


def test_un_tag_proche_du_lieu_sans_etre_le_lieu_est_conserve():
    """Le filtre ne doit pas mordre sur les quartiers ou les lieux-dits, qui eux
    apportent une précision que le champ lieu ne porte pas."""
    out = _validate_extraction({
        "lieu_nom": "Mont-de-Marsan", "categorie": "incendie",
        "tags": ["quartier du peyrouat", "parking"],
    })
    assert "quartier du peyrouat" in out["tags"]


# ── Troncature des résumés ──────────────────────────────────────────────────

def test_le_resume_long_est_coupe_a_la_derniere_phrase_complete():
    """`[:500]` tranchait au caractère près et laissait des moignons du genre
    « La pénurie nationale att » servis tels quels dans le fil."""
    phrase = "Un incendie a détruit un entrepôt et mobilisé quarante pompiers toute la nuit. "
    out = _validate_extraction({"resume_ia": phrase * 10})["resume_ia"]
    assert len(out) <= 500
    assert out.endswith(".")
    assert not out.endswith("…")
    # Aucun mot tronqué : le texte reste un multiple entier de la phrase.
    assert out.count("pompiers") == out.count("incendie")


def test_le_resume_sans_ponctuation_est_coupe_au_mot():
    """Repli quand aucune phrase complète ne tient dans le budget : on coupe au
    mot et on le signale par une ellipse, jamais au milieu d'un mot."""
    out = _validate_extraction({"resume_ia": "mot " * 300})["resume_ia"]
    assert len(out) <= 501  # 500 + l'ellipse
    assert out.endswith("…")
    assert not out.endswith("mo…")


def test_le_resume_court_est_intact():
    texte = "Trois blessés dans une collision à Colmar."
    assert _validate_extraction({"resume_ia": texte})["resume_ia"] == texte


@pytest.mark.parametrize("valeur,attendu", [
    ("commune", "commune"),
    ("Commune", "commune"),
    ("DEPARTEMENT", "departement"),
    ("ville", ""),          # hors nomenclature
    ("", ""),
    (None, ""),
    (42, ""),
])
def test_lieu_type_est_normalise_ou_ignore(valeur, attendu):
    assert _validate_extraction({"lieu_type": valeur})["lieu_type"] == attendu


def test_lieu_type_absent_ne_casse_rien():
    """Les petits modèles locaux omettent parfois le champ : l'extraction doit
    rester exploitable, seul le raccourci de géocodage est perdu."""
    out = _validate_extraction({"lieu_nom": "Colmar", "categorie": "culture"})
    assert out["lieu_type"] == ""
    assert out["lieu_nom"] == "Colmar"


def test_categorie_inventee_est_ramenee_a_actualite():
    assert _validate_extraction({"categorie": "faits_divers"})["categorie"] == "actualite"


def test_gravite_hors_bornes_est_ecretee():
    assert _validate_extraction({"gravite": 9})["gravite"] == 3
    assert _validate_extraction({"gravite": -2})["gravite"] == 0
    assert _validate_extraction({"gravite": "beaucoup"})["gravite"] == 0


# ── Raccourci de géocodage par lieu_type ────────────────────────────────────

async def test_lieu_type_commune_resout_directement_les_coordonnees(monkeypatch):
    """lieu_type="commune" évite un aller-retour au géocodeur ET l'ambiguïté
    ville/département (Vienne, Lot, Somme…)."""
    async def _extraction(*args, **kwargs):
        return {
            "lieu_nom": "Colmar", "lieu_type": "commune", "categorie": "culture",
            "resume_ia": "La halle rénovée rouvre.", "gravite": 0, "tags": ["halle"],
        }

    async def _geocode_interdit(lieu):  # pragma: no cover - ne doit pas être appelé
        raise AssertionError("le géocodeur ne devait pas être sollicité")

    monkeypatch.setattr(extractor, "extract_article", _extraction)
    monkeypatch.setattr(extractor, "geocode", _geocode_interdit)
    monkeypatch.setattr(extractor.settings, "FETCH_FULL_ARTICLES", False)
    extractor._extract_cache.clear()

    out = await extractor.maybe_extract({
        "source": "presse_rss", "titre": "La halle rénovée rouvre à Colmar",
        "description": "", "source_url": "https://example.com/a",
    })

    assert out["lieu_niveau"] == "commune"
    assert out["skip_geocoding"] is True
    assert out["lieu_code_insee"] == "68066"
    assert out["lieu_lat"] == pytest.approx(48.07, abs=0.1)
