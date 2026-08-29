import { describe, expect, it } from "vitest";

import { ALL_CATEGORIES } from "@/lib/constants";
import { lireDept, lireEtat, lireFiltres, lireRecherche, serialiserEtat, urlFlux } from "@/lib/urlEtat";

describe("lecture de l'URL", () => {
  it("relit le département et la recherche", () => {
    expect(lireDept("?dept=29")).toBe("29");
    expect(lireRecherche("?q=incendie+Gard")).toBe("incendie Gard");
  });

  it("ignore un département inconnu plutôt que de vider la carte", () => {
    // Lien tronqué, faute de frappe : appliquer « 999 » donnerait une carte
    // vide sans rien expliquer à qui reçoit le lien.
    expect(lireDept("?dept=999")).toBeNull();
    expect(lireDept("?dept=")).toBeNull();
    expect(lireDept("")).toBeNull();
  });

  it("accepte la Corse, dont les codes ne sont pas numériques", () => {
    expect(lireDept("?dept=2A")).toBe("2A");
    expect(lireDept("?dept=2B")).toBe("2B");
  });

  it("borne la longueur de la recherche", () => {
    expect(lireRecherche(`?q=${"a".repeat(500)}`)).toHaveLength(200);
  });

  it("retombe sur la fenêtre par défaut si la valeur n'est pas proposée", () => {
    expect(lireFiltres("?h=999").depuis_heures).toBe(48);
    expect(lireFiltres("?h=abc").depuis_heures).toBe(48);
    expect(lireFiltres("?h=168").depuis_heures).toBe(168);
  });

  it("borne la gravité dans 0-3", () => {
    expect(lireFiltres("?g=9").gravite_min).toBe(3);
    expect(lireFiltres("?g=-4").gravite_min).toBe(0);
  });

  it("écarte les catégories inconnues sans rejeter les autres", () => {
    const cats = lireFiltres(`?cats=${ALL_CATEGORIES[0]},licorne`).categories;
    expect(cats).toEqual([ALL_CATEGORIES[0]]);
  });
});

describe("écriture de l'URL", () => {
  const parDefaut = { categories: ALL_CATEGORIES, gravite_min: 0, depuis_heures: 48 };

  it("n'écrit rien quand rien ne s'écarte des valeurs par défaut", () => {
    // C'est cette URL nue qu'on partage : la charger de paramètres inutiles
    // la rendrait illisible sans rien changer à l'affichage.
    expect(serialiserEtat({ filters: parDefaut, dept: null, q: "" })).toBe("");
  });

  it("porte le département et la recherche", () => {
    const qs = serialiserEtat({ filters: parDefaut, dept: "29", q: "crue" });
    expect(qs).toContain("dept=29");
    expect(qs).toContain("q=crue");
  });

  it("fait l'aller-retour sans rien perdre", () => {
    // La propriété qui compte vraiment : ce qui est affiché doit tenir dans le
    // lien, et le lien doit redonner exactement la même vue.
    const etat = {
      filters: { categories: [ALL_CATEGORIES[1]], gravite_min: 2, depuis_heures: 168 },
      dept: "2A",
      q: "séisme Pyrénées",
    };
    expect(lireEtat(`?${serialiserEtat(etat)}`)).toEqual(etat);
  });

  it("échappe les caractères spéciaux d'une recherche", () => {
    const qs = serialiserEtat({ filters: parDefaut, dept: null, q: "gaz & électricité" });
    expect(qs).not.toContain(" ");
    expect(lireRecherche(`?${qs}`)).toBe("gaz & électricité");
  });
});

describe("lien d'abonnement au flux", () => {
  const parDefaut = { categories: ALL_CATEGORIES, gravite_min: 0, depuis_heures: 48 };

  it("ne pose aucun paramètre quand rien n'est filtré", () => {
    expect(urlFlux("/api", { filters: parDefaut, dept: null })).toBe("/api/feed.rss");
  });

  it("répète `categories` au lieu de les joindre par des virgules", () => {
    // FastAPI attend Query(None) sur une liste : « categories=a,b » serait
    // reçu comme UNE catégorie nommée « a,b » et rejeté en 422.
    const url = urlFlux("/api", {
      filters: { ...parDefaut, categories: [ALL_CATEGORIES[0], ALL_CATEGORIES[1]] },
      dept: null,
    });
    expect(url).toContain(`categories=${ALL_CATEGORIES[0]}`);
    expect(url).toContain(`categories=${ALL_CATEGORIES[1]}`);
    expect(url).not.toContain("%2C");
  });

  it("emploie les noms de paramètres du backend, pas ceux de l'URL de la page", () => {
    // La page sérialise « g » et « h » ; /feed.rss attend « gravite_min » et
    // « depuis_heures ». Confondre les deux donnerait un flux sans filtre.
    const url = urlFlux("/api", {
      filters: { ...parDefaut, gravite_min: 2, depuis_heures: 168 },
      dept: "29",
    });
    expect(url).toContain("gravite_min=2");
    expect(url).toContain("depuis_heures=168");
    expect(url).toContain("dept=29");
    expect(url).not.toMatch(/[?&]g=/);
    expect(url).not.toMatch(/[?&]h=/);
  });

  it("reste dans les bornes acceptées par le backend", () => {
    // /feed.rss borne depuis_heures à 720 (events.py) : c'est aussi la
    // fenêtre maximale proposée par l'interface, les deux ne doivent pas
    // diverger sans qu'on s'en aperçoive.
    const url = urlFlux("/api", { filters: { ...parDefaut, depuis_heures: 720 }, dept: null });
    expect(url).toContain("depuis_heures=720");
  });
});
