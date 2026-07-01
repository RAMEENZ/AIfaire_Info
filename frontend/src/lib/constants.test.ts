import { describe, expect, it } from "vitest";
import {
  ALL_CATEGORIES,
  CATEGORY_CONFIG,
  SOURCE_LABELS,
} from "./constants";

// Noms canoniques des connecteurs backend (app/pipeline/ingestor.py::CONNECTORS).
// À garder synchronisé si un connecteur est ajouté/retiré côté backend.
const BACKEND_CONNECTOR_NAMES = [
  "meteo_france", "vigicrues", "renass", "enedis", "presse_rss", "sncf",
  "bison_fute", "incendies", "cert_fr", "irsn", "air_quality", "opensky",
  "bluesky", "wikipedia_fr", "spf",
];

describe("constants", () => {
  it("SOURCE_LABELS couvre tous les connecteurs backend (sinon pastille brute)", () => {
    const missing = BACKEND_CONNECTOR_NAMES.filter((n) => !(n in SOURCE_LABELS));
    expect(missing).toEqual([]);
  });

  it("ALL_CATEGORIES et CATEGORY_CONFIG ont exactement les mêmes clés", () => {
    expect([...ALL_CATEGORIES].sort()).toEqual(Object.keys(CATEGORY_CONFIG).sort());
  });

  it("chaque catégorie a un label, une couleur, une icône et une lettre", () => {
    for (const cat of ALL_CATEGORIES) {
      const cfg = CATEGORY_CONFIG[cat];
      expect(cfg.label).toBeTruthy();
      expect(cfg.color).toMatch(/^#[0-9A-Fa-f]{6}$/);
      expect(cfg.icon).toBeTruthy();
      expect(cfg.letter).toBeTruthy();
    }
  });
});
