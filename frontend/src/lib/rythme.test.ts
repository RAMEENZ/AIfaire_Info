import { describe, expect, it } from "vitest";

import { libelleRythme } from "@/lib/rythme";

/**
 * Le libellé du rythme se construit à partir de ce que renvoie /api/health.
 * Les cas qui comptent sont ceux où le serveur ne dit PAS ce qu'on espère :
 * une version antérieure du backend, un scheduler arrêté, un fuseau exotique.
 * Dans ces cas il vaut mieux ne rien afficher qu'affirmer un rythme inventé.
 */
describe("libelleRythme", () => {
  it("énumère les heures en français, avec « et » avant la dernière", () => {
    const texte = libelleRythme([7, 12, 19], "Europe/Paris", false);
    expect(texte).toBe("Collecte complète à 7h, 12h et 19h (Paris).");
  });

  it("mentionne le relevé horaire des alertes quand il est actif", () => {
    const texte = libelleRythme([7, 12, 19], "Europe/Paris", true);
    expect(texte).toContain("toutes les heures");
    expect(texte).toContain("nuit comprise");
  });

  it("trie les heures : le serveur ne garantit pas l'ordre", () => {
    expect(libelleRythme([19, 7, 12], "Europe/Paris", false)).toBe(
      "Collecte complète à 7h, 12h et 19h (Paris)."
    );
  });

  it("accorde la phrase à une heure unique, sans « et » orphelin", () => {
    expect(libelleRythme([6], "Europe/Paris", false)).toBe("Collecte complète à 6h (Paris).");
  });

  it("ne renvoie rien si le serveur ne fournit pas les heures", () => {
    // Backend plus ancien : le champ est absent. Mieux vaut pas d'infobulle
    // qu'une infobulle qui invente « 7h, 12h et 19h ».
    expect(libelleRythme(undefined, "Europe/Paris", true)).toBe("");
    expect(libelleRythme([], "Europe/Paris", true)).toBe("");
  });

  it("se passe du fuseau plutôt que d'afficher une parenthèse vide", () => {
    expect(libelleRythme([7], undefined, false)).toBe("Collecte complète à 7h.");
  });

  it("rend lisible un fuseau à underscore", () => {
    // "America/New_York" ne doit pas s'afficher tel quel dans une phrase.
    expect(libelleRythme([7], "America/New_York", false)).toContain("(New York)");
  });
});
