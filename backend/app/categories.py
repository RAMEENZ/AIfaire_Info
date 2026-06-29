"""Taxonomie des catégories d'événements — source unique de vérité (backend).

Toute la logique backend (validation API, prompts d'extraction, classification
par règles) consomme cette liste. Pour AJOUTER une catégorie : ajoute-la ici,
ajoute ses mots-clés dans extractor.CATEGORY_KEYWORDS si pertinent, puis miroir
la config visuelle côté frontend dans frontend/src/lib/constants.ts
(CATEGORY_CONFIG + ALL_CATEGORIES) et le type frontend/src/lib/types.ts.
"""
from __future__ import annotations

# L'ordre fixe l'ordre d'affichage des filtres côté frontend (qui le reflète).
CATEGORIES: tuple[str, ...] = (
    "meteo", "crue", "seisme", "energie", "sante", "transport",
    "ordre_public", "actualite", "incendie", "nucleaire", "pollution", "cyber",
    "sport", "economie", "politique", "culture",
)

CATEGORY_SET: frozenset[str] = frozenset(CATEGORIES)

# Catégorie de repli quand l'extraction ne renvoie rien d'exploitable.
DEFAULT_CATEGORY = "actualite"

# Énumérations prêtes à injecter dans les prompts LLM (évite la re-duplication
# de la liste dans extractor.py).
CATEGORIES_QUOTED = ", ".join(f'"{c}"' for c in CATEGORIES)  # "meteo", "crue", …
CATEGORIES_PLAIN = ", ".join(CATEGORIES)                      # meteo, crue, …
