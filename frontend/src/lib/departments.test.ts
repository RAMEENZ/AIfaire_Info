import { describe, expect, it } from "vitest";
import { deptCodeFromInsee } from "./departments";

describe("deptCodeFromInsee", () => {
  it("extrait un département métropolitain", () => {
    expect(deptCodeFromInsee("75056")).toBe("75"); // Paris
    expect(deptCodeFromInsee("13055")).toBe("13"); // Marseille
  });

  it("gère la Corse (2A / 2B)", () => {
    expect(deptCodeFromInsee("2A004")).toBe("2A");
    expect(deptCodeFromInsee("2B033")).toBe("2B");
  });

  it("gère les DOM sur 3 chiffres (97x)", () => {
    expect(deptCodeFromInsee("97124")).toBe("971"); // Guadeloupe
    expect(deptCodeFromInsee("97411")).toBe("974"); // La Réunion
  });

  it("gère les COM du Pacifique sur 3 chiffres (98x)", () => {
    expect(deptCodeFromInsee("98818")).toBe("988"); // Nouvelle-Calédonie
    expect(deptCodeFromInsee("98735")).toBe("987"); // Polynésie
  });

  it("retourne null pour une entrée absente/invalide", () => {
    expect(deptCodeFromInsee(null)).toBeNull();
    expect(deptCodeFromInsee("")).toBeNull();
    expect(deptCodeFromInsee("X")).toBeNull();
  });
});
