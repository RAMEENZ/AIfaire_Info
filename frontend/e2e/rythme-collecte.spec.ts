import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

/**
 * Le rythme de collecte doit être lisible DEPUIS L'INTERFACE.
 *
 * Origine : le propriétaire du site a dû demander à quelles heures tournait la
 * collecte, et ce que faisait le bouton « Actualiser ». L'information existait
 * — côté serveur pour la première, dans le code pour la seconde — mais nulle
 * part où un utilisateur puisse la lire.
 *
 * Ces tests portent sur le RENDU, pas sur `libelleRythme` (couvert par
 * src/lib/rythme.test.ts). Une fonction juste mais débranchée laisserait les
 * tests unitaires au vert : c'est le branchement qu'on vérifie ici.
 */

function indicateur(page: import("@playwright/test").Page) {
  return page.getByRole("button", { name: /Prochaine mise à jour/ });
}

test.describe("sur grand écran", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
  });

  test("le rythme complet est accessible depuis « Prochaine MàJ »", async ({ page }) => {
    const bouton = indicateur(page);
    await expect(bouton).toBeVisible();

    // Fermé au départ : l'information ne s'impose pas, elle se demande.
    await expect(bouton).toHaveAttribute("aria-expanded", "false");
    await bouton.click();
    await expect(bouton).toHaveAttribute("aria-expanded", "true");

    const infobulle = page.getByText(/Collecte complète à 7h, 12h et 19h/);
    await expect(infobulle).toBeVisible();
    await expect(infobulle).toContainText("Paris");
    await expect(infobulle).toContainText("toutes les heures");
  });

  test("le nom accessible porte le rythme, pour les lecteurs d'écran", async ({ page }) => {
    // Un `title` sur un <span> n'est ni focusable ni annoncé de façon fiable.
    await expect(indicateur(page)).toHaveAccessibleName(/7h, 12h et 19h/);
  });

  test("le bouton Actualiser ne prétend plus relancer la collecte", async ({ page }) => {
    const bouton = page.getByRole("button", { name: "Actualiser" });
    const title = await bouton.getAttribute("title");
    // « Actualiser les données » laissait croire à une nouvelle collecte.
    expect(title).toContain("ne relance pas la collecte");
  });
});

test.describe("sur mobile", () => {
  test.use({ viewport: { width: 390, height: 664 }, hasTouch: true, isMobile: true });

  test("le rythme reste atteignable là où il disparaissait", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");

    // L'indicateur était en `hidden md:inline` : présent dans le DOM mais
    // `display: none` sous 768 px. `toBeVisible` distingue les deux.
    const bouton = indicateur(page);
    await expect(bouton).toBeVisible();

    // Et le détail doit s'ouvrir au TAP : c'est ce qu'un `title` natif ne
    // ferait pas, faute de survol sur écran tactile.
    await bouton.tap();
    await expect(page.getByText(/Collecte complète à 7h, 12h et 19h/)).toBeVisible();
  });
});
