import { describe, expect, it } from "vitest";

import { csvSafe } from "./constants";

describe("csvSafe", () => {
  // Les titres exportés viennent de flux RSS tiers : un tableur exécute toute
  // cellule commençant par =, +, - ou @.
  it.each(["=1+1", '=cmd|\'/c calc\'!A1', "+33612345678", "-2+3", "@SUM(A1:A9)", "\tinjection"])(
    "préfixe la formule %s", (dangereux) => {
      expect(csvSafe(dangereux).startsWith("'")).toBe(true);
    });

  it.each([
    "Trois blessés dans une collision à Colmar",
    "Vigilance orange : 19 départements",
    "L'A13 fermée de novembre 2026 à août 2027",
    "",
  ])("laisse intact le texte ordinaire %s", (sain) => {
    expect(csvSafe(sain)).toBe(sain);
  });
});
