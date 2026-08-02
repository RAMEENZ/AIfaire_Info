import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

/**
 * Régressions d'interface mobile réellement survenues en juillet 2026 :
 *  - le fil réduit à une fente de 129 px (barres empilées au-dessus) ;
 *  - le brief déplié impossible à faire défiler ;
 *  - Stats / Tendances / RSS inaccessibles faute de menu sur petit écran.
 * Un typecheck et des tests unitaires ne voient rien de tout cela : seul un
 * rendu réel le montre.
 */

test.use({ viewport: { width: 390, height: 664 }, hasTouch: true, isMobile: true });

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: /Actualités/ }).first().click();
});

test("le fil occupe une part utile de l'écran et défile", async ({ page }) => {
  const list = page.locator("div.overflow-y-auto").filter({ has: page.locator("article") }).first();
  await expect(list).toBeVisible();

  const metrics = await list.evaluate((el) => ({
    clientH: el.clientHeight,
    scrollH: el.scrollHeight,
    viewportH: window.innerHeight,
  }));

  // Seuil délibérément bas : on veut détecter l'écrasement (129 px sur 664,
  // soit 19 %), pas figer une maquette au pixel près.
  expect(metrics.clientH / metrics.viewportH).toBeGreaterThan(0.35);
  expect(metrics.scrollH).toBeGreaterThan(metrics.clientH);

  // Le défilement doit effectivement déplacer le contenu.
  await list.evaluate((el) => el.scrollTo({ top: 300 }));
  expect(await list.evaluate((el) => el.scrollTop)).toBeGreaterThan(100);
});

test("les barres timeline et stats ne mangent pas l'écran mobile", async ({ page }) => {
  // Elles restent dans le DOM (desktop) mais ne doivent occuper aucune
  // hauteur sur mobile.
  const hidden = page.locator("aside > div.hidden");
  if (await hidden.count()) {
    const h = await hidden.first().evaluate((el) => el.getBoundingClientRect().height);
    expect(h).toBe(0);
  }
});

test("le menu mobile donne accès aux pages secondaires", async ({ page }) => {
  await page.getByRole("button", { name: /Plus d'options/i }).click();
  await expect(page.getByRole("link", { name: /Statistiques/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Tendances/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Flux RSS/ })).toBeVisible();
});

test("le brief déplié est défilable", async ({ page }) => {
  await mockApi(page, { briefContent: Array.from({ length: 40 }, (_, i) => `Ligne ${i} du brief.`).join("\n") });
  await page.reload();
  await page.getByRole("button", { name: /Actualités/ }).first().click();

  await page.getByRole("button", { name: /Brief du/ }).click();
  const panel = page.locator("div.overflow-y-auto").filter({ hasText: "Ligne 0 du brief." }).first();
  await expect(panel).toBeVisible();

  const m = await panel.evaluate((el) => ({ c: el.clientHeight, s: el.scrollHeight }));
  // Le panneau doit être borné (et non déborder hors de la colonne) et
  // défiler si le contenu dépasse.
  expect(m.c).toBeGreaterThan(0);
  expect(m.s).toBeGreaterThan(m.c);
});

test("le zoom utilisateur reste autorisé (accessibilité)", async ({ page }) => {
  const viewport = await page.locator('meta[name="viewport"]').getAttribute("content");
  expect(viewport).not.toMatch(/maximum-scale\s*=\s*1/);
  expect(viewport).not.toMatch(/user-scalable\s*=\s*no/);
});
