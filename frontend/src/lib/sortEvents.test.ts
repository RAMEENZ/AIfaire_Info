import { describe, expect, it } from "vitest";
import { SORT_OPTIONS, sortComparator } from "./sortEvents";
import { Event } from "./types";

const NOW = new Date("2026-07-02T12:00:00Z").getTime();

function ev(id: string, gravite: number, hoursAgo: number): Event {
  return {
    id,
    gravite,
    date_publication: new Date(NOW - hoursAgo * 3_600_000).toISOString(),
  } as Event;
}

describe("sortComparator", () => {
  const vieilleAlerte = ev("vieille-alerte", 3, 96); // gravité 3, il y a 4 jours
  const infoFraiche = ev("info-fraiche", 0, 1);      // gravité 0, il y a 1 h
  const alerteFraiche = ev("alerte-fraiche", 2, 2);  // gravité 2, il y a 2 h

  it("gravite (défaut) : gravité décroissante puis récence — comportement historique", () => {
    const out = [infoFraiche, vieilleAlerte, alerteFraiche].sort(sortComparator("gravite", NOW));
    expect(out.map((e) => e.id)).toEqual(["vieille-alerte", "alerte-fraiche", "info-fraiche"]);
  });

  it("recent : ordre purement chronologique", () => {
    const out = [vieilleAlerte, infoFraiche, alerteFraiche].sort(sortComparator("recent", NOW));
    expect(out.map((e) => e.id)).toEqual(["info-fraiche", "alerte-fraiche", "vieille-alerte"]);
  });

  it("pertinence : une vieille alerte ne squatte plus le haut du fil", () => {
    // Scores : alerte-fraiche ≈ 2 - 0.08 = 1.92 ; vieille-alerte = 3 - 4 = -1 ;
    // info-fraiche ≈ 0 - 0.04 = -0.04 → l'alerte fraîche passe devant.
    const out = [vieilleAlerte, infoFraiche, alerteFraiche].sort(sortComparator("pertinence", NOW));
    expect(out[0].id).toBe("alerte-fraiche");
    expect(out.indexOf(vieilleAlerte)).toBeGreaterThan(out.indexOf(infoFraiche));
  });

  it("pertinence : à gravité égale, le plus récent gagne", () => {
    const a = ev("a", 1, 10);
    const b = ev("b", 1, 5);
    const out = [a, b].sort(sortComparator("pertinence", NOW));
    expect(out.map((e) => e.id)).toEqual(["b", "a"]);
  });

  it("expose les trois modes dans SORT_OPTIONS", () => {
    expect(SORT_OPTIONS.map((o) => o.value)).toEqual(["gravite", "recent", "pertinence"]);
  });
});
