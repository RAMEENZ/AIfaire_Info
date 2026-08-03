"""Tests pour sanitize_markdown (nettoyage Markdown des textes LLM).

Charge directement app/pipeline/sanitize.py via importlib pour éviter
de déclencher l'import chain de l'app (DB, settings, etc.).
"""
import importlib.util
import pathlib

_p = pathlib.Path(__file__).resolve().parents[1] / "app" / "pipeline" / "sanitize.py"
_spec = importlib.util.spec_from_file_location("sanitize", _p)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
_sanitize_brief = _mod.sanitize_markdown  # type: ignore[attr-defined]


def test_removes_markdown_headings():
    result = _sanitize_brief("### Titre\nTexte normal")
    assert "###" not in result
    assert "Titre" in result


def test_removes_bold():
    result = _sanitize_brief("**Alerte rouge** en cours")
    assert "**" not in result
    assert "Alerte rouge" in result


def test_removes_italic():
    result = _sanitize_brief("*vigilance* active")
    assert "vigilance" in result
    assert "*" not in result


def test_removes_horizontal_rule():
    result = _sanitize_brief("Avant\n---\nAprès")
    assert "---" not in result
    assert "Avant" in result
    assert "Après" in result


def test_removes_bullet_list_markers():
    result = _sanitize_brief("- Premier point\n- Second point")
    assert "- " not in result
    assert "Premier point" in result


def test_removes_technical_tags():
    result = _sanitize_brief("[METEO g3] Vigilance orange")
    assert "[METEO g3]" not in result
    assert "Vigilance orange" in result

    result2 = _sanitize_brief("[ORDRE_PUBLIC g2] Incident")
    assert "[ORDRE_PUBLIC g2]" not in result2
    assert "Incident" in result2


def test_collapses_multiple_blank_lines():
    result = _sanitize_brief("A\n\n\n\n\nB")
    assert "\n\n\n" not in result
    assert "A" in result and "B" in result


def test_plain_text_passes_through_unchanged():
    text = "Alertes & vigilances\n\nAucune alerte majeure aujourd'hui.\n\nActualité générale\n\nFait divers important."
    assert _sanitize_brief(text) == text


def test_mixed_real_world_input():
    raw = (
        "### **Alertes & vigilances**\n"
        "**[METEO g3] (France)** Vigilance rouge canicule.\n"
        "---\n"
        "### **Actualité générale**\n"
        "**[ORDRE_PUBLIC g2] (Paris)** Fusillade dans le XVIe.\n"
    )
    result = _sanitize_brief(raw)
    assert "###" not in result
    assert "**" not in result
    assert "---" not in result
    assert "[METEO g3]" not in result
    assert "[ORDRE_PUBLIC g2]" not in result
    assert "Vigilance rouge canicule" in result
    assert "Fusillade dans le XVIe" in result


# ── truncate_clean ──────────────────────────────────────────────────────────

def test_truncate_clean_ne_coupe_jamais_un_mot():
    from app.pipeline.sanitize import truncate_clean

    # Cas réel remonté par l'exploitation : la coupe brute à 180 caractères
    # rendait « La pénurie nationale att ».
    texte = (
        "Le département du Tarn-et-Garonne, comme d'autres, peine à recruter des "
        "maîtres-nageurs sauveteurs pour surveiller les bassins et bases de loisirs "
        "cet été. La pénurie nationale atteint un niveau inédit."
    )
    court = truncate_clean(texte, 180)
    assert not court.startswith(texte[:180])  # la coupe brute est écartée
    assert court.endswith("…")
    assert "att…" not in court
    assert court[:-1].split()[-1] in texte.split()


def test_truncate_clean_prefere_la_phrase_complete():
    from app.pipeline.sanitize import truncate_clean

    texte = (
        "Le département peine à recruter des maîtres-nageurs sauveteurs. "
        "La pénurie nationale atteint un niveau inédit cette année encore."
    )
    court = truncate_clean(texte, 100, prefer_sentence=True)
    assert court == "Le département peine à recruter des maîtres-nageurs sauveteurs."
    assert not court.endswith("…")


def test_truncate_clean_retombe_sur_le_mot_si_la_phrase_est_trop_longue():
    from app.pipeline.sanitize import truncate_clean

    # Première phrase bien au-delà du budget : la garder reviendrait à ne rien
    # tronquer. On coupe au mot, avec l'ellipse qui signale la coupe.
    texte = "a" * 40 + " " + "b" * 40 + " " + "c" * 40 + ". Fin."
    court = truncate_clean(texte, 60, prefer_sentence=True)
    assert court.endswith("…")
    assert len(court) <= 61


def test_last_complete_sentence_isole_la_derniere_phrase_entiere():
    from app.pipeline.sanitize import last_complete_sentence

    coupe = ("Le département peine à recruter des maîtres-nageurs. "
             "La pénurie nationale att")
    assert last_complete_sentence(coupe) == (
        "Le département peine à recruter des maîtres-nageurs."
    )


def test_last_complete_sentence_rend_vide_sans_phrase_complete():
    from app.pipeline.sanitize import last_complete_sentence

    assert last_complete_sentence("La pénurie nationale att") == ""


def test_last_complete_sentence_ne_coupe_pas_sur_une_abreviation_collee():
    """« 3.500 » n'est pas une fin de phrase : le point doit être suivi d'un
    blanc ou de la fin du texte."""
    from app.pipeline.sanitize import last_complete_sentence

    assert last_complete_sentence("Un budget de 3.500 euros voté hier") == ""
