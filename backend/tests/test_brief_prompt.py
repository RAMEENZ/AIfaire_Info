"""Tests des prompts du brief et des utilitaires qui les alimentent.

Les prompts ne sont pas du texte décoratif : le front dépend de l'orthographe
exacte des titres de section, et le brief lui-même dépend de consignes qu'une
retouche malheureuse peut faire disparaître. Ces tests verrouillent le contrat.
"""
import re
from pathlib import Path

import pytest

from app.pipeline.brief import (
    SECTION_TITLES,
    _missing_sections,
    _periode_fr,
    _truncate_words,
    audit_brief,
    build_brief_system_prompt,
    build_brief_user_prompt,
    split_sections,
)
from app.pipeline.sanitize import sanitize_markdown

BRIEF_PROPRE = """Alertes & vigilances

Douze départements du Sud-Est sont en vigilance orange canicule jusqu'à jeudi.

Actualité générale

Un équipementier automobile supprime 120 postes sur son site de Montbéliard.
La SNCF annonce un train sur trois sur l'axe Paris-Lyon mardi.

En régions

À Colmar, la halle rénovée rouvre après six mois de travaux.
À Draguignan, un incendie de garrigue a parcouru huit hectares.
"""


# ── Fenêtre temporelle ──────────────────────────────────────────────────────

@pytest.mark.parametrize("hours,attendu", [
    (24, "les dernières 24 heures"),
    (168, "les sept derniers jours"),
    (12, "les 12 dernières heures"),
    (48, "les 2 derniers jours"),
])
def test_periode_est_lisible(hours, attendu):
    assert _periode_fr(hours) == attendu


def test_periode_jamais_exprimee_en_heures_au_dela_du_jour():
    """« les dernières 168h » poussait le modèle à écrire « aujourd'hui » pour
    des faits vieux de six jours."""
    assert "168" not in _periode_fr(168)


# ── Troncature des données ──────────────────────────────────────────────────

def test_troncature_ne_coupe_pas_au_milieu_dun_mot():
    texte = "Un plan social menace 120 emplois sur le site de Montbéliard"
    court = _truncate_words(texte, 30)
    assert court.endswith("…")
    assert len(court) <= 31
    # Le dernier mot conservé est entier.
    assert court[:-1].rstrip().split()[-1] in texte.split()


def test_troncature_laisse_le_texte_court_intact():
    assert _truncate_words("Trois blessés à Colmar", 220) == "Trois blessés à Colmar"


def test_troncature_normalise_les_blancs():
    assert _truncate_words("Deux\n  lignes   collées", 220) == "Deux lignes collées"


# ── Titres de section ───────────────────────────────────────────────────────

def test_missing_sections_detecte_un_titre_absent():
    texte = "Alertes & vigilances\n\nRien à signaler.\n\nEn régions\n\nÀ Colmar, …"
    assert _missing_sections(texte) == ["Actualité générale"]


def test_missing_sections_exige_le_titre_seul_sur_sa_ligne():
    """« Côté Actualité générale, … » n'est pas un titre : le front ne le
    reconnaîtrait pas non plus."""
    assert "Actualité générale" in _missing_sections("Côté Actualité générale, rien.")


def test_titres_survivent_au_nettoyage_markdown():
    brut = "### **Alertes & vigilances**\n\nRAS.\n\n## Actualité générale\n\nRAS.\n\nEn régions\n\nRAS."
    assert _missing_sections(sanitize_markdown(brut)) == []


def test_titres_identiques_a_ceux_attendus_par_le_front():
    """Contrat inter-services : le composant DailyBrief compare les lignes du
    brief à sa propre liste. Deux listes qui divergent = sections non stylées."""
    tsx = Path(__file__).resolve().parents[2] / "frontend/src/components/DailyBrief.tsx"
    if not tsx.exists():  # backend testé seul, hors du dépôt complet
        pytest.skip("frontend absent")
    ligne = re.search(r"const SECTION_TITLES = \[(.*?)\];", tsx.read_text(), re.S)
    assert ligne, "constante SECTION_TITLES introuvable dans DailyBrief.tsx"
    front = tuple(re.findall(r'"([^"]+)"', ligne.group(1)))
    assert front == SECTION_TITLES


# ── Prompt système ──────────────────────────────────────────────────────────

def _system(hebdo: bool = False) -> str:
    return build_brief_system_prompt("dimanche 28 juin 2026", "les dernières 24 heures", hebdo)


def test_le_prompt_dicte_les_titres_exacts():
    prompt = _system()
    for titre in SECTION_TITLES:
        assert f"\n{titre}\n" in prompt, f"{titre!r} doit figurer seul sur sa ligne"


def test_le_prompt_porte_les_garde_fous_de_qualite():
    """Chaque consigne ci-dessous corrige un défaut constaté sur des briefs
    réellement produits ; en perdre une, c'est le laisser revenir."""
    prompt = _system().lower()
    attendus = {
        "anti-répétition": "ne reparaît dans aucune autre",
        "hiérarchie": "le fait le plus important d'abord",
        "chiffres": "reprends les chiffres",
        "jours creux": "ne meuble jamais",
        "formule creuse": "il convient de noter",
        "pas d'opinion": "opinion",
        "diversité géographique": "île-de-france",
        "pas d'invention": "n'invente aucune date",
    }
    manquants = [nom for nom, extrait in attendus.items() if extrait not in prompt]
    assert not manquants, f"garde-fous perdus dans le prompt : {manquants}"


def test_le_prompt_interdit_le_markdown():
    prompt = _system()
    assert "Texte brut uniquement" in prompt
    assert "aucun dièse" in prompt


def test_la_date_et_la_periode_sont_injectees():
    prompt = _system()
    assert "dimanche 28 juin 2026" in prompt
    assert "les dernières 24 heures" in prompt


def test_le_bloc_hebdomadaire_napparait_que_pour_la_semaine():
    assert "BRIEF HEBDOMADAIRE" not in _system(hebdo=False)
    hebdo = _system(hebdo=True)
    assert "BRIEF HEBDOMADAIRE" in hebdo
    # generate_weekly_brief reconnaît un brief hebdo au mot « semaine » : le
    # prompt doit donc l'exiger, sinon la déduplication du lundi échoue.
    assert "« semaine »" in hebdo


# ── Prompt utilisateur ──────────────────────────────────────────────────────

def test_le_prompt_utilisateur_porte_les_donnees_et_les_comptes():
    user = build_brief_user_prompt(
        "- Canicule — vigilance orange : 12 départements (Drôme, Var)",
        "- (Lyon) Plan social chez un équipementier, 120 emplois",
        "- (Colmar) La halle rénovée rouvre",
        12, 1, 1, "les dernières 24 heures",
    )
    assert "ALERTES & VIGILANCES (12)" in user
    assert "ACTUALITÉ GÉNÉRALE (1)" in user
    assert "EN RÉGIONS (1)" in user
    assert "12 départements" in user
    assert "120 emplois" in user
    # Consigne de sélection : le modèle n'a pas à tout recopier.
    assert "Tu n'as pas à tout citer" in user


# ── Audit du texte produit ──────────────────────────────────────────────────

def test_decoupage_en_sections():
    sections = split_sections(BRIEF_PROPRE)
    assert list(sections) == list(SECTION_TITLES)
    assert "Colmar" in sections["En régions"]
    assert "canicule" in sections["Alertes & vigilances"]
    # Le titre lui-même ne fait pas partie du corps.
    assert "Actualité générale" not in sections["Actualité générale"]


def test_un_brief_conforme_ne_declenche_aucun_constat():
    assert audit_brief(BRIEF_PROPRE) == []


def test_audit_signale_une_formule_creuse():
    abime = BRIEF_PROPRE.replace(
        "Un équipementier", "Il convient de noter qu'un équipementier"
    )
    assert any("formule creuse" in c for c in audit_brief(abime))


def test_audit_signale_le_markdown_residuel():
    constats = audit_brief(BRIEF_PROPRE.replace("Alertes & vigilances", "## Alertes & vigilances"))
    assert any("dièse" in c for c in constats)


def test_audit_signale_une_section_manquante():
    tronque = BRIEF_PROPRE.split("En régions")[0]
    assert any("En régions" in c for c in audit_brief(tronque))


def test_audit_signale_une_redite_entre_sections():
    """Le cas que la règle « une seule fois » du prompt vise : le même fait
    raconté en section 2, puis reformulé en section 3."""
    redit = BRIEF_PROPRE.replace(
        "À Colmar, la halle rénovée rouvre après six mois de travaux.",
        "L'équipementier automobile supprime 120 postes à Montbéliard, "
        "annonce faite sur son site industriel.",
    )
    constats = audit_brief(redit)
    assert any("recoupement" in c for c in constats), constats


def test_audit_ne_crie_pas_au_recoupement_sur_des_mots_courants():
    """Deux sections peuvent partager « pendant », « plusieurs » ou « notamment »
    sans raconter la même chose : l'audit doit rester utilisable."""
    banal = (
        "Alertes & vigilances\n\nPlusieurs départements restent en vigilance pendant la nuit.\n\n"
        "Actualité générale\n\nPlusieurs communes ferment leurs écoles pendant les travaux.\n\n"
        "En régions\n\nÀ Colmar, plusieurs commerces rouvrent pendant la saison.\n"
    )
    assert not [c for c in audit_brief(banal) if "recoupement" in c]


# ── Détection des noms propres inventés ─────────────────────────────────────

def test_audit_repere_un_lieu_invente():
    """Le cas réel du 11/08/2026 : « Locodole » n'était dans aucune donnée."""
    from app.pipeline.brief import audit_brief

    brief = (
        "Alertes & vigilances\n\nRien à signaler.\n\n"
        "Actualité générale\n\nÀ Nanterre, le théâtre des Amandiers ferme.\n\n"
        "En régions\n\nÀ Locodole près de Dole, une collecte de sang a eu lieu."
    )
    matiere = (
        "- (Nanterre) Le théâtre des Amandiers ferme.\n"
        "- (Dole) Une collecte de sang a eu lieu."
    )
    constats = audit_brief(brief, matiere)
    assert any("Locodole" in c for c in constats)
    # Les noms propres réellement fournis ne doivent pas être signalés.
    assert not any("Nanterre" in c or "Amandiers" in c or "Dole" in c for c in constats)


def test_audit_sans_matiere_ne_juge_que_la_forme():
    """Sans le prompt, l'audit ne peut pas savoir ce qui a été fourni."""
    from app.pipeline.brief import audit_brief

    brief = (
        "Alertes & vigilances\n\nRien.\n\nActualité générale\n\n"
        "À Locodole, rien.\n\nEn régions\n\nRien."
    )
    assert not any("Locodole" in c for c in audit_brief(brief))


def test_audit_ignore_la_majuscule_de_debut_de_phrase():
    """« Dix-neuf départements… » ouvre une phrase : sa majuscule est syntaxique."""
    from app.pipeline.brief import audit_brief

    brief = (
        "Alertes & vigilances\n\nDix-neuf départements sont en vigilance.\n\n"
        "Actualité générale\n\nRien.\n\nEn régions\n\nRien."
    )
    constats = audit_brief(brief, "- Vigilance orange sur des départements.")
    assert not any("Dix-neuf" in c for c in constats)


def test_audit_insensible_aux_accents():
    """Un nom fourni accentué et rendu sans accent reste un nom fourni."""
    from app.pipeline.brief import audit_brief

    brief = (
        "Alertes & vigilances\n\nRien.\n\nActualité générale\n\n"
        "Un incident a eu lieu a Saint-Etienne-du-Rouvray.\n\nEn régions\n\nRien."
    )
    constats = audit_brief(brief, "- (Saint-Étienne-du-Rouvray) Un incident.")
    assert not any("Rouvray" in c for c in constats)
