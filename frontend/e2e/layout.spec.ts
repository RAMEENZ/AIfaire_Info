import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

/**
 * L'en-tête ne doit jamais évincer le contenu, à AUCUNE largeur.
 *
 * Les tests couvraient le mobile (390 px) et le bureau large ; l'intervalle
 * n'était vérifié nulle part. Or c'est là que la mise en page cassait : à
 * 1100 px, l'en-tête occupait 799 px d'une fenêtre de 900, ne laissant que
 * 72 px à la carte et au fil (relevé du 03/08/2026). Les filtres étaient le
 * seul élément flexible de l'en-tête, absorbaient toute la compression, et
 * leurs seize pastilles s'empilaient une par ligne.
 *
 * Le défaut n'était pas monotone — 1100 px était pire que 1024 et que 1215 —
 * donc tester deux largeurs ne suffit pas : on balaie l'intervalle.
 */

const LARGEURS = [390, 640, 768, 820, 900, 1024, 1100, 1215, 1366, 1600, 1920];
const HAUTEUR = 900;

// Bornes larges : on veut attraper l'effondrement, pas figer le pixel près.
const EN_TETE_MAX = 220;
const PART_CONTENU_MIN = 0.55;

for (const largeur of LARGEURS) {
  test(`à ${largeur} px, l'en-tête laisse la place au contenu`, async ({ page }) => {
    await mockApi(page, { total: 60 });
    await page.setViewportSize({ width: largeur, height: HAUTEUR });
    await page.goto("/");
    await expect(page.locator("main")).toBeVisible();

    const mesures = await page.evaluate(() => {
      const header = document.querySelector("header");
      const main = document.querySelector("main");
      return {
        enTete: Math.round(header?.getBoundingClientRect().height ?? 0),
        contenu: Math.round(main?.getBoundingClientRect().height ?? 0),
        deborde:
          document.documentElement.scrollWidth > document.documentElement.clientWidth,
      };
    });

    expect(
      mesures.enTete,
      `en-tête de ${mesures.enTete} px à ${largeur} px de large`
    ).toBeLessThanOrEqual(EN_TETE_MAX);

    expect(
      mesures.contenu / HAUTEUR,
      `carte + fil réduits à ${mesures.contenu} px à ${largeur} px de large`
    ).toBeGreaterThanOrEqual(PART_CONTENU_MIN);

    // Aucune largeur ne doit provoquer de défilement horizontal du document.
    expect(mesures.deborde, `débordement horizontal à ${largeur} px`).toBe(false);
  });
}

test("les filtres restent utilisables : les pastilles ne s'empilent pas en colonne", async ({ page }) => {
  // Le symptôme visible de l'effondrement : une colonne d'une pastille par
  // ligne. On le mesure par le nombre de rangées qu'occupent les catégories.
  await mockApi(page, { total: 60 });
  await page.setViewportSize({ width: 1100, height: HAUTEUR });
  await page.goto("/");
  await expect(page.locator("main")).toBeVisible();

  const rangees = await page.evaluate(() => {
    const boutons = Array.from(document.querySelectorAll("header button"));
    const hauts = new Set(boutons.map((b) => Math.round(b.getBoundingClientRect().top)));
    return hauts.size;
  });

  expect(rangees, `${rangees} rangées de contrôles dans l'en-tête`).toBeLessThanOrEqual(6);
});
