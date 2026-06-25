"""Déduplication des articles : regroupe les reprises d'une même dépêche.

Beaucoup de médias reprennent les mêmes dépêches (AFP, Reuters…) : un même fait
arrive alors via plusieurs flux RSS avec des titres quasi identiques. On calcule
une empreinte déterministe à partir de l'ensemble des mots significatifs du titre.
Deux titres partageant le même jeu de mots significatifs reçoivent la même
empreinte, ce qui permet à l'interface de n'afficher qu'une fois le fait, avec le
nombre de sources qui le relaient.

Propriétés :
- **Déterministe et sans état** : aucune comparaison croisée en base, aucun seuil
  de similarité flou. La même entrée donne toujours la même empreinte.
- **Conservateur** : on préfère sous-grouper (laisser deux reprises séparées) que
  de fusionner à tort deux faits distincts. Les titres trop courts ne sont pas
  regroupés (empreinte None) car le risque de collision y est trop élevé.

Limite assumée : deux formulations réellement différentes d'un même fait
(« Fusillade dans le XVIe » vs « Un mort par balles à Paris ») ne seront pas
regroupées. C'est un compromis volontaire en faveur de la précision.
"""
import hashlib
import re
import unicodedata

# Mots-outils français/anglais sans valeur discriminante : retirés avant de
# calculer l'empreinte pour que « Le maire de Lyon démissionne » et
# « Démission du maire de Lyon » convergent vers la même empreinte.
_STOPWORDS = frozenset(
    {
        "le", "la", "les", "un", "une", "des", "de", "du", "d", "l", "et", "ou",
        "a", "à", "au", "aux", "en", "dans", "sur", "sous", "pour", "par", "avec",
        "sans", "se", "sa", "son", "ses", "ce", "cet", "cette", "ces", "qui",
        "que", "quoi", "dont", "où", "est", "sont", "ete", "etre", "ont", "ne",
        "pas", "plus", "ses", "leur", "leurs", "il", "elle", "ils", "elles", "on",
        "nous", "vous", "y", "the", "of", "to", "in", "on", "for", "and", "is",
        "at", "as", "by", "an",
    }
)

# Un token significatif : lettres (accents inclus via NFD plus bas) ou chiffres.
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# En-deçà de ce nombre de mots significatifs distincts, un titre est trop court
# pour clusteriser de façon fiable (trop de collisions). On renvoie None.
_MIN_TOKENS = 4

# Longueur minimale d'un token retenu (élimine « le », « un » résiduels, initiales).
_MIN_TOKEN_LEN = 3


def _normalize(text: str) -> str:
    """Minuscule, sans accents, ASCII — pour comparer des titres robustement."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _significant_tokens(titre: str) -> list[str]:
    norm = _normalize(titre)
    return [
        t
        for t in _TOKEN_RE.findall(norm)
        if len(t) >= _MIN_TOKEN_LEN and t not in _STOPWORDS
    ]


def title_fingerprint(titre: str | None) -> str | None:
    """Empreinte déterministe d'un titre, ou None s'il est trop court/vide.

    Deux titres au même jeu de mots significatifs → même empreinte (16 hex).
    """
    if not titre:
        return None
    tokens = sorted(set(_significant_tokens(titre)))
    if len(tokens) < _MIN_TOKENS:
        return None
    key = " ".join(tokens)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
