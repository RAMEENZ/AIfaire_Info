import { describe, expect, it } from "vitest";

import { AlertSettings, evenementsAAlerter } from "./notifications";
import { Event } from "./types";

const REGLAGES: AlertSettings = {
  enabled: true, minGravite: 2, departments: [], categories: [],
};

function ev(id: string, gravite = 2): Event {
  return {
    id, source: "presse_rss", source_url: `https://exemple.fr/${id}`,
    titre: `Fait ${id}`, auteur: "Test", date_publication: "2026-08-11T10:00:00Z",
    date_evenement: null, categorie: "incendie", gravite,
    lieu_nom: "Colmar", lieu_code_insee: "68066", lieu_lat: 48.08, lieu_lon: 7.36,
    lieu_niveau: "commune", lieu_confiance_geo: 0.9, resume_ia: null, tags: [],
    score_confiance: 1, created_at: "2026-08-11T10:00:00Z", cluster_id: null,
  };
}

describe("evenementsAAlerter", () => {
  it("n'amorce pas la mémoire sur un lot vide", () => {
    // Le cœur du défaut : les réglages se chargent depuis localStorage AVANT
    // que le fil n'arrive. Amorcer sur cette liste vide faisait passer tout le
    // fil initial pour du nouveau — une notification par vigilance en cours.
    const { memoire, aAlerter } = evenementsAAlerter(null, [], REGLAGES);
    expect(memoire).toBeNull();
    expect(aAlerter).toEqual([]);
  });

  it("le premier lot réel amorce la mémoire sans notifier", () => {
    const { memoire, aAlerter } = evenementsAAlerter(null, [ev("a"), ev("b")], REGLAGES);
    expect(aAlerter).toEqual([]);
    expect(memoire?.size).toBe(2);
  });

  it("aucune avalanche quand le fil arrive après les réglages", () => {
    // Séquence réelle : réglages chargés (lot vide), puis première page.
    const t0 = evenementsAAlerter(null, [], REGLAGES);
    const t1 = evenementsAAlerter(t0.memoire, [ev("a"), ev("b"), ev("c")], REGLAGES);
    expect(t1.aAlerter).toEqual([]);
  });

  it("notifie ce qui arrive APRÈS l'amorçage", () => {
    const t0 = evenementsAAlerter(null, [ev("a")], REGLAGES);
    const t1 = evenementsAAlerter(t0.memoire, [ev("b"), ev("a")], REGLAGES);
    expect(t1.aAlerter.map((e) => e.id)).toEqual(["b"]);
  });

  it("ne notifie pas deux fois le même événement", () => {
    const t0 = evenementsAAlerter(null, [ev("a")], REGLAGES);
    const t1 = evenementsAAlerter(t0.memoire, [ev("b")], REGLAGES);
    const t2 = evenementsAAlerter(t1.memoire, [ev("b")], REGLAGES);
    expect(t2.aAlerter).toEqual([]);
  });

  it("respecte le seuil de gravité", () => {
    const t0 = evenementsAAlerter(null, [ev("a")], REGLAGES);
    const t1 = evenementsAAlerter(t0.memoire, [ev("b", 1), ev("c", 3)], REGLAGES);
    expect(t1.aAlerter.map((e) => e.id)).toEqual(["c"]);
  });

  it("ne mute pas la mémoire reçue", () => {
    const t0 = evenementsAAlerter(null, [ev("a")], REGLAGES);
    const avant = new Set(t0.memoire!);
    evenementsAAlerter(t0.memoire, [ev("b")], REGLAGES);
    expect(t0.memoire).toEqual(avant);
  });

  it("alertes désactivées : rien ne part, mais la mémoire suit", () => {
    const off = { ...REGLAGES, enabled: false };
    const t0 = evenementsAAlerter(null, [ev("a")], off);
    const t1 = evenementsAAlerter(t0.memoire, [ev("b")], off);
    expect(t1.aAlerter).toEqual([]);
    expect(t1.memoire?.has("b")).toBe(true);
  });
});
