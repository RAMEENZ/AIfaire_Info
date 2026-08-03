import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

/**
 * Bulles de la carte.
 *
 * /events/map n'envoie ni résumé ni tags (charge utile divisée). La bulle doit
 * donc compléter la fiche à l'ouverture, sinon cliquer un marqueur ne rapporte
 * que le titre — déjà lisible sur la carte. Seules les vigilances météo y
 * échappaient, leur titre portant toute l'information.
 */

type Page = import("@playwright/test").Page;

/**
 * Fait apparaître des marqueurs individuels.
 *
 * Au zoom national, les événements sont regroupés en grappes (`faire-cluster`,
 * déclustérisées au zoom 12). Cliquer une grappe zoome sur son étendue ; on
 * répète jusqu'à obtenir des marqueurs unitaires.
 */
async function declusteriser(page: Page) {
  const marqueurs = page.locator(".faire-marker");
  for (let i = 0; i < 10 && (await marqueurs.count()) === 0; i++) {
    const grappe = page.locator(".faire-cluster").first();
    if ((await grappe.count()) === 0) break;
    await grappe.click();
    await page.waitForTimeout(400); // animation de zoom Leaflet
  }
  await expect(marqueurs.first()).toBeVisible();
}

/** Ouvre la bulle du premier marqueur et retourne son conteneur. */
async function ouvrirPremiereBulle(page: Page) {
  await declusteriser(page);
  await page.locator(".faire-marker").first().click();
  const bulle = page.locator(".leaflet-popup-content");
  await expect(bulle).toBeVisible();
  return bulle;
}

test("cliquer un marqueur affiche le résumé de l'article", async ({ page }) => {
  const calls = await mockApi(page, { total: 30 });
  await page.goto("/");

  const bulle = await ouvrirPremiereBulle(page);

  // Le résumé n'est pas dans la réponse de la carte : il doit être allé le
  // chercher. C'est la régression que ce test verrouille.
  await expect(bulle.getByText(/Résumé de l'événement/)).toBeVisible();
  await expect(bulle.getByText("résumé automatique")).toBeVisible();
  // Une bulle ouverte = une fiche demandée, pas davantage.
  await expect.poll(() => calls.detail.length).toBe(1);
});

test("la bulle porte le titre, le lieu et un lien vers l'article", async ({ page }) => {
  await mockApi(page, { total: 30 });
  await page.goto("/");

  const bulle = await ouvrirPremiereBulle(page);

  const lien = bulle.getByRole("link").first();
  await expect(lien).toHaveAttribute("href", /example\.com\/article-/);
  await expect(lien).toHaveAttribute("target", "_blank");
  await expect(bulle.getByText(/Ville \d+/)).toBeVisible();
});

test("aucune fiche n'est préchargée au rendu de la carte", async ({ page }) => {
  // 300 marqueurs : si la carte allait chercher chaque résumé d'avance,
  // l'allègement de /events/map ne servirait plus à rien — on paierait 300
  // requêtes au lieu d'une charge utile double.
  const calls = await mockApi(page, { total: 300 });
  await page.goto("/");
  await expect(page.locator(".leaflet-container")).toBeVisible();
  await expect(page.locator(".leaflet-marker-icon").first()).toBeVisible();
  await expect(page.locator("article").first()).toBeVisible();

  expect(calls.map).toBeGreaterThan(0);
  expect(calls.detail).toEqual([]);
});

test("une même bulle rouverte ne redemande pas la fiche", async ({ page }) => {
  const calls = await mockApi(page, { total: 30 });
  await page.goto("/");

  const bulle = await ouvrirPremiereBulle(page);
  await expect(bulle.getByText(/Résumé de l'événement/)).toBeVisible();
  const apresPremiere = calls.detail.length;

  await page.keyboard.press("Escape");
  await ouvrirPremiereBulle(page);
  await expect(page.locator(".leaflet-popup-content").getByText(/Résumé de l'événement/)).toBeVisible();

  expect(calls.detail.length).toBe(apresPremiere);
});

test("si la fiche échoue, la bulle le dit et propose de réessayer", async ({ page }) => {
  await mockApi(page, { total: 30, failEventDetail: true });
  await page.goto("/");

  const bulle = await ouvrirPremiereBulle(page);

  // Le titre reste lisible : l'échec du complément ne vide pas la bulle.
  await expect(bulle.getByRole("link").first()).toBeVisible();
  await expect(bulle.getByText("Résumé indisponible.")).toBeVisible();
  await expect(bulle.getByRole("button", { name: "Réessayer" })).toBeVisible();
});
