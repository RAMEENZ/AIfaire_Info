// Modes de tri du fil d'actualités. "gravite" est le comportement historique
// (défaut) ; "pertinence" pondère la gravité par la récence pour qu'une alerte
// ancienne ne squatte pas indéfiniment le haut du fil (même formule que le
// paramètre API sort=pertinence : la gravité perd ~1 point par jour écoulé).
import { Event } from "./types";

export type SortMode = "gravite" | "recent" | "pertinence";

export const SORT_OPTIONS: { value: SortMode; label: string }[] = [
  { value: "gravite", label: "Gravité" },
  { value: "recent", label: "Récents" },
  { value: "pertinence", label: "Pertinence" },
];

const MS_PER_DAY = 86_400_000;

// Horodatage borné à `now` : les événements datés dans le futur (vigilances J1
// « pour demain ») sont triés comme publiés à l'instant — sans borne, ils
// squattent la tête du mode « Récents » en permanence et reçoivent même un
// bonus en « Pertinence » (âge négatif → score gonflé).
function ts(e: Event, now: number): number {
  const t = new Date(e.date_publication).getTime();
  return Number.isNaN(t) ? 0 : Math.min(t, now);
}

/** Comparateur pour Array.prototype.sort selon le mode choisi.
 * `now` est injectable pour les tests (défaut : Date.now()). */
export function sortComparator(mode: SortMode, now: number = Date.now()) {
  if (mode === "recent") {
    // Départage par gravité : les événements futurs, tous ramenés à `now`,
    // sont à égalité de date — le plus grave d'abord.
    return (a: Event, b: Event) => ts(b, now) - ts(a, now) || b.gravite - a.gravite;
  }
  if (mode === "pertinence") {
    const score = (e: Event) => e.gravite - (now - ts(e, now)) / MS_PER_DAY;
    return (a: Event, b: Event) => score(b) - score(a) || ts(b, now) - ts(a, now);
  }
  // "gravite" — comportement historique : gravité décroissante puis récence.
  return (a: Event, b: Event) => b.gravite - a.gravite || ts(b, now) - ts(a, now);
}
