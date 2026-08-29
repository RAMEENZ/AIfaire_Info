import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchEventDetail } from "@/lib/api";

/**
 * Le cache des fiches n'avait aucune borne. L'application étant une PWA qu'on
 * laisse ouverte, parcourir la carte pendant une journée y accumulait une
 * fiche par marqueur cliqué, résumé compris, sans jamais rien évincer.
 */
describe("cache des fiches événement", () => {
  let appels = 0;

  beforeEach(() => {
    appels = 0;
    vi.stubGlobal("fetch", async (url: string) => {
      appels += 1;
      const id = String(url).split("/").pop();
      return {
        ok: true,
        json: async () => ({ id, titre: `Événement ${id}` }),
      } as Response;
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("évite un second appel réseau pour la même fiche", async () => {
    await fetchEventDetail("evt-cache-1");
    await fetchEventDetail("evt-cache-1");
    expect(appels).toBe(1);
  });

  it("évince les plus anciennes au-delà du plafond", async () => {
    // Un identifiant distinct par test : le cache est un état de module,
    // partagé avec le test précédent.
    const premier = "evt-evince-0";
    await fetchEventDetail(premier);

    // Largement au-delà du plafond (200) : la première fiche doit être sortie.
    for (let i = 1; i <= 250; i++) await fetchEventDetail(`evt-evince-${i}`);

    const avant = appels;
    await fetchEventDetail(premier);
    // Un nouvel appel réseau prouve l'éviction. Sans borne, la fiche serait
    // encore là et le compteur n'aurait pas bougé.
    expect(appels).toBe(avant + 1);
  });

  it("garde les fiches récentes", async () => {
    const recent = "evt-recent";
    await fetchEventDetail(recent);
    const avant = appels;
    await fetchEventDetail(recent);
    expect(appels).toBe(avant);
  });
});
