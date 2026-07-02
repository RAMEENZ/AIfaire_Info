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

function ts(e: Event): number {
  return new Date(e.date_publication).getTime();
}

/** Comparateur pour Array.prototype.sort selon le mode choisi.
 * `now` est injectable pour les tests (défaut : Date.now()). */
export function sortComparator(mode: SortMode, now: number = Date.now()) {
  if (mode === "recent") {
    return (a: Event, b: Event) => ts(b) - ts(a);
  }
  if (mode === "pertinence") {
    const score = (e: Event) => e.gravite - (now - ts(e)) / MS_PER_DAY;
    return (a: Event, b: Event) => score(b) - score(a) || ts(b) - ts(a);
  }
  // "gravite" — comportement historique : gravité décroissante puis récence.
  return (a: Event, b: Event) => b.gravite - a.gravite || ts(b) - ts(a);
}
