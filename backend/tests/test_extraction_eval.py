"""Jeu d'évaluation hors-ligne de l'extraction (catégorie + commune).

Objectif : permettre de retoucher les mots-clés, les prompts ou le modèle
sans régresser à l'aveugle. Aucun réseau, aucun LLM — on n'évalue ici que la
partie déterministe (règles par mots-clés et reconnaissance de commune), qui
est aussi le filet quand l'IA est indisponible.

Les seuils sont volontairement en dessous du score courant : ils détectent une
RÉGRESSION, ils ne bloquent pas une amélioration. Quand le score progresse
durablement, remonter le seuil (et noter la date).
"""
import asyncio

import pytest

from app.communes_db import commune_from_text
from app.pipeline.extractor import CATEGORY_KEYWORDS

# ── Corpus annoté ───────────────────────────────────────────────────────────
# Titres représentatifs de la presse régionale française. `None` = aucune
# catégorie attendue (l'article relève légitimement de « actualite »).
CAS_CATEGORIE: list[tuple[str, str | None]] = [
    # Alertes et risques
    ("Vigilance orange canicule sur le département", "meteo"),
    ("Fortes pluies attendues : épisode méditerranéen sur le Gard", "meteo"),
    ("La crue de la Loire atteint son pic à Orléans", "crue"),
    ("Séisme de magnitude 4,2 ressenti dans les Pyrénées", "seisme"),
    ("Feu de forêt : 200 hectares brûlés dans le Var", "incendie"),
    ("Panne de courant : 3 000 foyers privés d'électricité", "energie"),
    ("Alerte pollution aux particules fines sur l'agglomération", "pollution"),
    ("Cyberattaque par rançongiciel contre l'hôpital", "cyber"),
    ("Incident nucléaire de niveau 1 signalé par l'ASN", "nucleaire"),
    # Transport
    ("Grève SNCF : un train sur trois ce mardi", "transport"),
    ("Carambolage sur l'autoroute A9, trois blessés", "transport"),
    ("Travaux routiers : déviation mise en place jusqu'en mai", "transport"),
    ("La ligne de bus 12 desservira le nouveau quartier", "transport"),
    # Ordre public et chronique judiciaire
    ("Deux interpellations après un cambriolage", "ordre_public"),
    ("Procès : le prévenu condamné à deux ans de prison", "ordre_public"),
    ("Trafic de drogue démantelé, cinq gardes à vue", "ordre_public"),
    ("Manifestation des agriculteurs devant la préfecture", "ordre_public"),
    # Santé
    ("Épidémie de grippe : les urgences saturées", "sante"),
    ("Rappel de lot : listeria détectée dans des fromages", "sante"),
    # Économie
    ("L'usine annonce un plan social, 120 emplois menacés", "economie"),
    ("Redressement judiciaire pour l'entreprise familiale", "economie"),
    ("Les viticulteurs redoutent une récolte historiquement basse", "economie"),
    # Culture
    ("Le festival de musique revient pour sa dixième édition", "culture"),
    ("La médiathèque rouvre après six mois de travaux", "culture"),
    ("Brocante annuelle : 200 exposants attendus", "culture"),
    # Politique
    ("Le conseil municipal vote le budget à l'unanimité", "politique"),
    ("Remaniement : trois ministres quittent le gouvernement", "politique"),
    # Sport
    ("Ligue 1 : victoire à domicile en fin de match", "sport"),
    # Sans catégorie dédiée : « actualite » est le bon verdict
    ("Le marché hebdomadaire change d'horaires", None),
    ("Un nouveau rond-point sera inauguré samedi", None),
]

# Titres → commune attendue (None = aucune détection ne doit avoir lieu).
CAS_COMMUNE: list[tuple[str, str | None]] = [
    ("Incendie maîtrisé à Draguignan après trois heures", "Draguignan"),
    ("Un nouveau collège livré à Saint-Étienne-du-Rouvray", "Saint-Étienne-du-Rouvray"),
    ("Le maire de Colmar inaugure la halle rénovée", "Colmar"),
    ("Trafic perturbé à Bar-le-Duc ce matin", "Bar-le-Duc"),
    ("Les pompiers mobilisés à Perpignan", "Perpignan"),
    ("Marché de Noël à Strasbourg : record d'affluence", "Strasbourg"),
    # Pièges : mots courants, noms de médias, entités non communales
    ("La mer est agitée sur le port ce matin", None),
    ("Réunion publique à la mairie demain soir", None),
    ("Grève des transports en Île-de-France", None),
    ("Le conseil départemental vote son budget", None),
]


def _categorise(titre: str) -> str:
    """Réplique du classement par règles de _rule_based_extract, isolé pour
    l'évaluation (la fonction complète tente aussi un géocodage réseau)."""
    text = titre.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw.lower() in text for kw in keywords):
            return cat
    return "actualite"


# ── Seuils de non-régression (relevés le 30/07/2026) ────────────────────────
SEUIL_CATEGORIE = 0.80
SEUIL_COMMUNE = 0.80


def test_categorisation_par_regles_au_dessus_du_seuil():
    justes = 0
    erreurs = []
    for titre, attendu in CAS_CATEGORIE:
        obtenu = _categorise(titre)
        cible = attendu or "actualite"
        if obtenu == cible:
            justes += 1
        else:
            erreurs.append(f"{titre!r} → {obtenu} (attendu {cible})")
    score = justes / len(CAS_CATEGORIE)
    assert score >= SEUIL_CATEGORIE, (
        f"Catégorisation à {score:.0%} (seuil {SEUIL_CATEGORIE:.0%}).\n"
        + "\n".join(erreurs)
    )


def test_detection_commune_au_dessus_du_seuil():
    justes = 0
    erreurs = []
    for titre, attendu in CAS_COMMUNE:
        res = commune_from_text(titre)
        obtenu = res["nom"] if res else None
        # Comparaison souple sur les variantes de graphie (tirets, accents).
        ok = (obtenu is None and attendu is None) or (
            obtenu is not None
            and attendu is not None
            and obtenu.lower().replace("-", " ") == attendu.lower().replace("-", " ")
        )
        if ok:
            justes += 1
        else:
            erreurs.append(f"{titre!r} → {obtenu!r} (attendu {attendu!r})")
    score = justes / len(CAS_COMMUNE)
    assert score >= SEUIL_COMMUNE, (
        f"Détection de commune à {score:.0%} (seuil {SEUIL_COMMUNE:.0%}).\n"
        + "\n".join(erreurs)
    )


def test_aucun_faux_positif_sur_les_pieges():
    """Les faux positifs coûtent plus cher qu'une absence de détection : un
    marqueur au mauvais endroit trompe le lecteur, un événement « national »
    reste simplement hors carte. Ce test est donc strict."""
    pieges = [titre for titre, attendu in CAS_COMMUNE if attendu is None]
    fautifs = [t for t in pieges if commune_from_text(t) is not None]
    assert not fautifs, f"Faux positifs de localisation : {fautifs}"


@pytest.mark.parametrize("titre,attendu", CAS_CATEGORIE)
def test_categorie_cas_par_cas(titre, attendu):
    """Détail par cas : identifie immédiatement le titre qui régresse.
    Non bloquant en dessous du seuil global — c'est le test agrégé qui fait foi."""
    obtenu = _categorise(titre)
    if obtenu != (attendu or "actualite"):
        pytest.xfail(f"{titre!r} classé {obtenu}")


def test_evaluation_est_hors_ligne():
    """Garde-fou : le corpus doit rester exécutable sans réseau ni clé d'API,
    sinon la CI deviendrait dépendante d'un service externe."""
    # commune_from_text lit une table CSV locale ; _categorise n'est que du
    # texte. Aucune coroutine réseau ne doit être nécessaire.
    assert asyncio.iscoroutinefunction(_categorise) is False
    assert commune_from_text("Test à Colmar") is not None
