"""Nettoyage de texte généré par LLM : formatage Markdown résiduel et coupes."""
import re

_FIN_DE_PHRASE = re.compile(r"[.!?…](?=\s|$)")

_HR_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_TAG_RE = re.compile(r"\[[A-ZÀ-Ÿ_]+\s+g\d\]\s*")
_BOLD_RE = re.compile(r"(\*\*|__)(.+?)\1")
_ITALIC_RE = re.compile(r"(?<!\w)([*_])(?!\s)(.+?)(?<!\s)\1(?!\w)")


def sanitize_markdown(text: str) -> str:
    """Retire le formatage Markdown résiduel d'un texte généré par LLM.

    Traite aussi bien les briefs multi-paragraphes que les résumés courts.
    """
    if not text:
        return text
    out_lines: list[str] = []
    for raw in text.splitlines():
        if _HR_RE.match(raw):
            continue
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", raw)
        line = re.sub(r"^\s{0,3}[-*+]\s+", "", line)
        line = _TAG_RE.sub("", line)
        line = _BOLD_RE.sub(r"\2", line)
        line = _ITALIC_RE.sub(r"\2", line)
        line = line.replace("**", "").replace("__", "")
        out_lines.append(line.rstrip())
    cleaned = "\n".join(out_lines)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def last_complete_sentence(text: str) -> str:
    """Le texte ramené à sa dernière phrase complète, `''` s'il n'en contient
    aucune. Sert à rattraper un texte tranché en cours de phrase."""
    text = " ".join(text.split())
    fins = [m.end() for m in _FIN_DE_PHRASE.finditer(text)]
    return text[: fins[-1]].strip() if fins else ""


def truncate_clean(text: str, limit: int, *, prefer_sentence: bool = False) -> str:
    """Tronque un texte sans jamais couper au milieu d'un mot.

    Une coupe brute par tranche de caractères (`text[:500]`) laisse des moignons
    du genre « La pénurie nationale att » : illisible pour un lecteur, et
    trompeur pour un modèle à qui l'on soumettrait ce texte ensuite.

    `prefer_sentence` privilégie la dernière phrase complète, et ne rend alors
    aucun signe de troncature — le texte se termine normalement. On n'y recourt
    que si cette phrase conserve au moins la moitié du budget, faute de quoi on
    retombe sur la coupe au mot, marquée par une ellipse.
    """
    text = " ".join(text.split())
    if len(text) <= limit:
        return text

    if prefer_sentence:
        fins = [m.end() for m in _FIN_DE_PHRASE.finditer(text[:limit])]
        if fins and fins[-1] >= limit // 2:
            return text[: fins[-1]].strip()

    coupe = text[:limit].rsplit(" ", 1)[0]
    return (coupe or text[:limit]).rstrip(" ,;:–-") + "…"
