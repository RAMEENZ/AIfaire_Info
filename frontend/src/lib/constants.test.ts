import { afterEach, describe, expect, it } from "vitest";
import {
  ALL_CATEGORIES,
  CATEGORY_CONFIG,
  SOURCE_LABELS,
  permalienEvenement,
} from "./constants";

// Noms canoniques des connecteurs backend (app/pipeline/ingestor.py::CONNECTORS).
// À garder synchronisé si un connecteur est ajouté/retiré côté backend.
const BACKEND_CONNECTOR_NAMES = [
  "meteo_france", "vigicrues", "renass", "presse_rss", "sncf",
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

describe("permalienEvenement", () => {
  const initial = process.env.NEXT_PUBLIC_SITE_URL;
  afterEach(() => {
    if (initial === undefined) delete process.env.NEXT_PUBLIC_SITE_URL;
    else process.env.NEXT_PUBLIC_SITE_URL = initial;
  });

  it("bâtit le lien sur l'origine publique configurée", () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://exemple.fr";
    expect(permalienEvenement("abc")).toBe("https://exemple.fr/event/abc");
  });

  it("tolère une barre oblique finale sans la doubler", () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://exemple.fr/";
    expect(permalienEvenement("abc")).toBe("https://exemple.fr/event/abc");
  });

  // Sans origine configurée (next dev), on retombe sur celle du navigateur —
  // jsdom sert http://localhost:3000. C'est le cas où l'origine courante EST
  // la bonne ; dans l'APK elle ne l'est pas, d'où la variable de build.
  it("retombe sur l'origine courante quand rien n'est configuré", () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    expect(permalienEvenement("abc")).toBe(`${window.location.origin}/event/abc`);
  });
});
