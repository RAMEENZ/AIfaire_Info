import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

/**
 * Le nom du site apparaissait en dur dans cinq fichiers, plus les métadonnées,
 * le manifeste PWA et le service worker. Un renommage en oublie forcément un :
 * ces tests couvrent chaque endroit où le lecteur peut le lire.
 */
const NOM = "(ai)Faire";

/** innerText insère un saut de ligne entre les segments du logotype (artefact
 *  d'inline-flex, l'affichage est bien sur une ligne). On compare donc sur un
 *  texte débarrassé de ses espaces. */
const compact = (t: string) => t.replace(/\s+/g, "");

test("le logotype s'affiche sur l'accueil", async ({ page }) => {
  await mockApi(page, { total: 20 });
  await page.goto("/");
  await page.waitForSelector(".leaflet-container");
  const entete = compact(await page.locator("body").first().innerText());
  expect(entete).toContain(compact(NOM));
  expect(entete).not.toContain("FAIREInfo");
});

test("l'onglet du navigateur porte le nom", async ({ page }) => {
  await mockApi(page, { total: 20 });
  await page.goto("/");
  await page.waitForTimeout(600);
  expect(await page.title()).toContain(NOM);
});

test("le titre d'onglet garde le nom quand une urgence s'affiche", async ({ page }) => {
  // document.title est réécrit dynamiquement dès qu'un événement de gravité 3
  // apparaît : le nom doit survivre à cette réécriture.
  await mockApi(page, { total: 20 });
  await page.goto("/");
  await page.waitForTimeout(1500);
  const titre = await page.title();
  expect(titre).toContain(NOM);
});

test("les pages secondaires portent le même logotype", async ({ page }) => {
  await mockApi(page, { total: 20 });
  for (const chemin of ["/stats", "/tendances"]) {
    await page.goto(chemin);
    await page.waitForTimeout(500);
    expect(compact(await page.locator("body").innerText()), chemin).toContain(compact(NOM));
  }
});

test("le manifeste PWA est à jour", async ({ page }) => {
  const r = await page.request.get("/manifest.json");
  expect(r.ok()).toBe(true);
  const m = await r.json();
  expect(m.name).toContain(NOM);
  expect(m.short_name).toContain(NOM);
});
