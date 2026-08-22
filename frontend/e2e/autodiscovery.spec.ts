import { expect, test } from "@playwright/test";

/**
 * Le flux Atom existait — filtrable par catégorie, gravité et département —
 * mais aucun lecteur de flux ne pouvait le découvrir depuis l'adresse du site,
 * faute de <link rel="alternate"> dans l'en-tête. C'était la fonctionnalité la
 * plus complète et la plus invisible du projet.
 */
test("l'en-tête déclare le flux Atom pour l'autodécouverte", async ({ page }) => {
  await page.goto("/");

  const lien = page.locator('link[rel="alternate"][type="application/atom+xml"]');
  await expect(lien).toHaveCount(1);

  const href = await lien.getAttribute("href");
  expect(href).toBeTruthy();
  // Chemin réel de la route (events.py), et non un /feed.atom supposé.
  expect(href).toContain("/feed.rss");

  // Un titre, sinon les lecteurs affichent l'URL brute dans leur liste.
  await expect(lien).toHaveAttribute("title", /Faire Info/);
});
