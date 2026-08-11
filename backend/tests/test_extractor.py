"""Tests for the extractor's offline logic: HTML stripping, rule-based
categorisation and gravity scoring, and the source-category overrides.

`geocode` is monkeypatched to a no-op so the rule-based toponym pass
never touches the network.
"""
import pytest

from app.pipeline import extractor
from app.pipeline.extractor import (
    _strip_html,
    _rule_based_extract,
    maybe_extract,
    SOURCE_CAT_OVERRIDES,
)


@pytest.fixture(autouse=True)
def _no_network_geocode(monkeypatch):
    """Replace geocode with a stub that never resolves a location."""
    async def fake_geocode(lieu):
        return {"lat": None, "lon": None, "code_insee": None,
                "niveau": "national", "confiance_geo": 0.0}
    monkeypatch.setattr(extractor, "geocode", fake_geocode)
    # Disable the Ollama path so maybe_extract uses the rule-based fallback
    monkeypatch.setattr(extractor.settings, "OLLAMA_BASE_URL", "")
    extractor._extract_cache.clear()
    yield
    extractor._extract_cache.clear()


# --- _strip_html --------------------------------------------------------

def test_strip_html_removes_tags():
    assert _strip_html("<p>Bonjour <b>monde</b></p>") == "Bonjour monde"


def test_strip_html_decodes_entities():
    assert _strip_html("Caf&eacute; &amp; th&eacute;") == "Café & thé"


def test_strip_html_collapses_whitespace():
    assert _strip_html("a\n\n  b\t c") == "a b c"


# --- rule-based categorisation -----------------------------------------

@pytest.mark.parametrize("text,expected_cat", [
    ("Vigilance crues orange sur la Loire", "crue"),
    ("Tempête et vent violent attendus demain", "meteo"),
    ("Séisme de magnitude 4 ressenti", "seisme"),
    ("Coupure d'électricité massive, panne de courant", "energie"),
    ("Grève SNCF : trafic ferroviaire perturbé", "transport"),
    ("Manifestation et violence urbaine en centre-ville", "ordre_public"),
    ("Alerte sanitaire : rappel de lot de listeria", "sante"),
    # Politique locale : classé « actualite » jusqu'en 07/2026 faute de
    # mot-clé — c'était la limitation des règles, pas le classement souhaité.
    ("Le conseil municipal vote son budget", "politique"),
    # Reste sans catégorie dédiée : « actualite » est ici le bon verdict.
    ("Le marché hebdomadaire change d'horaires", "actualite"),
])
async def test_categorisation(text, expected_cat):
    result = await _rule_based_extract(text, None)
    assert result["categorie"] == expected_cat


@pytest.mark.parametrize("text,expected_gravite", [
    ("Catastrophe : plusieurs morts dans l'incendie", 3),
    ("Situation critique, nombreux blessés", 2),
    ("Vigilance et prudence recommandées", 1),
    ("Réunion ordinaire du conseil", 0),
])
async def test_gravity_scoring(text, expected_gravite):
    result = await _rule_based_extract(text, None)
    assert result["gravite"] == expected_gravite


async def test_rule_based_defaults_to_national_without_toponym():
    result = await _rule_based_extract("Une réunion importante", None)
    assert result["lieu_nom"] == "national"


# --- maybe_extract ------------------------------------------------------

async def test_maybe_extract_skips_when_flagged():
    item = {"skip_extraction": True, "titre": "x", "source": "renass"}
    result = await maybe_extract(item)
    assert result is item


async def test_maybe_extract_fills_missing_fields_for_presse():
    item = {
        "source": "presse_rss",
        "titre": "Coupure d'électricité géante, panne de courant",
        "description": "",
        "auteur": "Le Monde",
    }
    result = await maybe_extract(item)
    assert result["categorie"] == "energie"
    assert result["resume_ia"]  # non-empty


async def test_source_override_forces_category():
    # ANSM is an authoritative health source -> category forced to "sante"
    item = {
        "source": "presse_rss",
        "titre": "Communiqué relatif à un produit",
        "description": "",
        "auteur": "ANSM",
    }
    result = await maybe_extract(item)
    assert result["categorie"] == "sante"


def test_source_overrides_table_contains_known_authorities():
    assert SOURCE_CAT_OVERRIDES["ansm"] == "sante"
    assert SOURCE_CAT_OVERRIDES["vigicrues"] == "crue"
    assert SOURCE_CAT_OVERRIDES["météo-france"] == "meteo"


# --- Garde-fou des lieux inventés ---------------------------------------

async def _extraction_factice(monkeypatch, lieu_nom, lieu_type):
    """Force le retour du modèle, pour éprouver le seul garde-fou."""
    async def fake_extract(titre, description=None, full_text=None):
        return {
            "categorie": "actualite", "gravite": 0, "lieu_nom": lieu_nom,
            "lieu_type": lieu_type, "resume_ia": "Un résumé.", "tags": [],
        }
    monkeypatch.setattr(extractor, "extract_article", fake_extract)
    return await maybe_extract({
        "source": "presse_rss", "titre": "Un fait divers", "description": "",
        "auteur": "Test", "source_url": "https://exemple.fr/article",
    })


async def test_lieu_etranger_sans_lieu_type_rabattu_sur_national(monkeypatch):
    """Le garde-fou ne se déclenchait QUE si le modèle déclarait « commune ».

    Sans ce champ, « Kiev » partait au géocodage : la BAN répondait Quiévy
    (Nord) et l'article se retrouvait épinglé en France (relevé du 11/08/2026).
    """
    result = await _extraction_factice(monkeypatch, "Kiev", None)
    assert result["lieu_nom"] == "national"


async def test_lieu_invente_sans_lieu_type_rabattu_sur_national(monkeypatch):
    result = await _extraction_factice(monkeypatch, "Locodole", "")
    assert result["lieu_nom"] == "national"


async def test_commune_reelle_sans_lieu_type_conservee(monkeypatch):
    """Le garde-fou ne doit pas coûter les lieux légitimes."""
    result = await _extraction_factice(monkeypatch, "Gravelines", None)
    assert result["lieu_nom"] == "Gravelines"


async def test_departement_sans_lieu_type_conserve(monkeypatch):
    result = await _extraction_factice(monkeypatch, "Morbihan", None)
    assert result["lieu_nom"] == "Morbihan"


# --- Gravité des faits étrangers ----------------------------------------

async def test_fait_etranger_ne_declenche_pas_le_canal_d_alerte(monkeypatch):
    """La gravité ≥ 2 déclenche les notifications push (push.py) et la section
    « Alertes » du brief. Les règles l'attribuaient au seul mot-clé de
    catégorie : « Séisme en Colombie » sortait en gravité 3, soit une alerte
    rouge sur le téléphone d'un lecteur français (relevé du 11/08/2026).
    """
    monkeypatch.setattr(extractor.settings, "MISTRAL_API_KEY", "clé-de-test")
    result = await maybe_extract({
        "source": "presse_rss",
        # Titre réel du 11/08/2026, complet : c'est lui qui sortait en gravité 3.
        "titre": "Séisme en Colombie : au moins 181 morts, Washington débloque une aide",
        "description": "", "auteur": "Test",
        "source_url": "https://exemple.fr/monde/seisme-colombie",
    })
    assert result["categorie"] == "seisme"      # la catégorie reste juste
    assert result["gravite"] < 2                # mais hors du canal d'alerte
    assert result["lieu_nom"] == "national"


async def test_fait_francais_conserve_sa_gravite():
    """Le plafond ne doit pas désarmer les alertes françaises légitimes."""
    result = await maybe_extract({
        "source": "presse_rss",
        "titre": "Séisme ressenti dans les Pyrénées-Atlantiques, plusieurs blessés",
        "description": "", "auteur": "Test",
        "source_url": "https://exemple.fr/seisme-pyrenees",
    })
    assert result["gravite"] >= 2


@pytest.mark.parametrize("titre", [
    "Séisme de magnitude 7 au Chili",
    "Inondations meurtrières au Pérou",
    "Explosion au Bangladesh : 30 morts",
    "Coup d'État au Mali",
    "Séisme au Népal : des centaines de victimes",
    "Manifestations en Pologne contre la réforme",
])
def test_pays_etrangers_detectes(titre):
    """La liste d'origine ignorait presque toute l'Amérique latine, l'Europe de
    l'Est, l'Afrique et l'Asie du Sud-Est : 26 pays passaient pour français."""
    from app.pipeline.extractor import _looks_french
    assert _looks_french(titre, "") is False


@pytest.mark.parametrize("titre", [
    "Trois blessés dans une collision à Colmar",
    "Vigilance orange canicule sur 19 départements",
    "Incendie en forêt de Fontainebleau",
    # Pièges : homonymes français de noms de pays ou de villes.
    "Chili con carne : la recette inratable",
    "Concert au jardin du Luxembourg à Paris",
    "L'AS Monaco s'impose face à Nice",
    "La ville de Vienne, en Isère, rénove ses thermes",
    "Le Niger, affluent de la Loire, en crue à Nevers",
])
def test_titres_francais_non_signales_comme_etrangers(titre):
    """Élargir le filtre ne doit pas rejeter la matière française vers
    l'extraction par règles, bien plus grossière."""
    from app.pipeline.extractor import _looks_french
    assert _looks_french(titre, "") is True
