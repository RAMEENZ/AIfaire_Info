import { afterEach, describe, expect, it, vi } from "vitest";

import { ecrireStockage, effacerStockage, lireStockage } from "@/lib/stockage";

/**
 * Le point qui manquait : les ÉCRITURES étaient protégées, pas les LECTURES.
 * Or `getItem` lève lui aussi — Safari en navigation privée stricte, une
 * politique d'entreprise, un navigateur réglé pour bloquer les données de
 * site. Ces lectures se font dans des effets React : l'exception y remonte
 * jusqu'à la frontière d'erreur, et l'utilisateur perd la carte pour une
 * préférence d'affichage.
 */
function stockageQuiLeve() {
  return {
    getItem() {
      throw new DOMException("The operation is insecure.", "SecurityError");
    },
    setItem() {
      throw new DOMException("The operation is insecure.", "SecurityError");
    },
    removeItem() {
      throw new DOMException("The operation is insecure.", "SecurityError");
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("stockage hostile", () => {
  it("une lecture qui lève rend null au lieu de propager", () => {
    vi.stubGlobal("window", { localStorage: stockageQuiLeve() });
    expect(lireStockage("theme")).toBeNull();
  });

  it("une écriture qui lève ne propage pas non plus", () => {
    vi.stubGlobal("window", { localStorage: stockageQuiLeve() });
    expect(() => ecrireStockage("theme", "dark")).not.toThrow();
  });

  it("une suppression qui lève ne propage pas", () => {
    vi.stubGlobal("window", { localStorage: stockageQuiLeve() });
    expect(() => effacerStockage("pinnedDept")).not.toThrow();
  });
});

describe("stockage normal", () => {
  it("relit ce qui a été écrit, puis l'oublie après suppression", () => {
    const donnees = new Map<string, string>();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (k: string) => donnees.get(k) ?? null,
        setItem: (k: string, v: string) => void donnees.set(k, v),
        removeItem: (k: string) => void donnees.delete(k),
      },
    });

    ecrireStockage("theme", "dark");
    expect(lireStockage("theme")).toBe("dark");
    effacerStockage("theme");
    expect(lireStockage("theme")).toBeNull();
  });

  it("rend null pour une clé absente", () => {
    vi.stubGlobal("window", {
      localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    });
    expect(lireStockage("jamais-ecrite")).toBeNull();
  });
});
