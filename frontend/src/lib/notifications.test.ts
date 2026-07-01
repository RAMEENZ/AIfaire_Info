import { beforeEach, describe, expect, it } from "vitest";
import {
  AlertSettings,
  DEFAULT_ALERT_SETTINGS,
  loadAlertSettings,
  saveAlertSettings,
  shouldAlert,
} from "./notifications";
import { Event } from "./types";

function makeEvent(overrides: Partial<Event> = {}): Event {
  return {
    id: "e1",
    source: "presse_rss",
    source_url: "https://example.fr/a",
    titre: "Titre",
    auteur: null,
    date_publication: "2026-07-01T10:00:00Z",
    date_evenement: null,
    categorie: "meteo",
    gravite: 2,
    lieu_nom: "Lyon",
    lieu_code_insee: "69123",
    lieu_lat: 45.75,
    lieu_lon: 4.85,
    lieu_niveau: "commune",
    lieu_confiance_geo: 0.9,
    resume_ia: null,
    tags: [],
    cluster_id: null,
    score_confiance: 1,
    ...overrides,
  } as Event;
}

const enabled: AlertSettings = { ...DEFAULT_ALERT_SETTINGS, enabled: true, minGravite: 2 };

describe("shouldAlert", () => {
  it("n'alerte jamais si désactivé", () => {
    expect(shouldAlert(makeEvent(), DEFAULT_ALERT_SETTINGS)).toBe(false);
  });

  it("respecte le seuil de gravité", () => {
    expect(shouldAlert(makeEvent({ gravite: 1 }), enabled)).toBe(false);
    expect(shouldAlert(makeEvent({ gravite: 2 }), enabled)).toBe(true);
    expect(shouldAlert(makeEvent({ gravite: 3 }), enabled)).toBe(true);
  });

  it("filtre par catégorie quand un filtre est actif", () => {
    const s = { ...enabled, categories: ["crue"] as Event["categorie"][] };
    expect(shouldAlert(makeEvent({ categorie: "meteo" }), s)).toBe(false);
    expect(shouldAlert(makeEvent({ categorie: "crue" }), s)).toBe(true);
  });

  it("filtre par département via le code INSEE", () => {
    const s = { ...enabled, departments: ["69"] };
    expect(shouldAlert(makeEvent({ lieu_code_insee: "69123" }), s)).toBe(true);
    expect(shouldAlert(makeEvent({ lieu_code_insee: "75056" }), s)).toBe(false);
    // Événement sans localisation : pas d'alerte quand un filtre géo est actif.
    expect(shouldAlert(makeEvent({ lieu_code_insee: null }), s)).toBe(false);
  });
});

describe("loadAlertSettings / saveAlertSettings", () => {
  beforeEach(() => window.localStorage.clear());

  it("retourne les valeurs par défaut sans stockage", () => {
    expect(loadAlertSettings()).toEqual(DEFAULT_ALERT_SETTINGS);
  });

  it("relit ce qui a été sauvegardé (round-trip)", () => {
    const s: AlertSettings = { enabled: true, minGravite: 3, departments: ["13"], categories: ["seisme"] };
    saveAlertSettings(s);
    expect(loadAlertSettings()).toEqual(s);
  });

  it("tolère un JSON corrompu en retombant sur les défauts", () => {
    window.localStorage.setItem("faire-info-alerts", "{pas du json");
    expect(loadAlertSettings()).toEqual(DEFAULT_ALERT_SETTINGS);
  });
});
