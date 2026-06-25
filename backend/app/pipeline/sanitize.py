"""Nettoyage de texte généré par LLM : supprime le formatage Markdown résiduel."""
import re

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
