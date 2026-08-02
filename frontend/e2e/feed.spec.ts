import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

/** Pagination du fil, recherche côté serveur et source dédiée de la carte. */

test("la première page demande 200 événements et la carte a sa propre source", async ({ page }) => {
  const calls = await mockApi(page, { total: 250 });
  await page.goto("/");
  await expect(page.locator("article").first()).toBeVisible();

  expect(calls.events[0]).toMatchObject({ offset: 0, limit: 200 });
  // La carte ne doit pas dépendre de la pagination du fil.
  expect(calls.map).toBeGreaterThan(0);
});

test("« charger plus » demande la page suivante au serveur", async ({ page }) => {
  const calls = await mockApi(page, { total: 250 });
  await page.goto("/");
  await expect(page.locator("article").first()).toBeVisible();

  // `dispatchEvent` plutôt que `click` : le bouton siège en fin d'une liste
  // de 200 cartes qui se re-rend à chaque activation, ce qui rend le clic par
  // pointeur instable (l'élément bouge entre le défilement et le clic).
  // L'atteignabilité réelle du bouton est vérifiée séparément, ici on teste
  // l'enchaînement des requêtes.
  for (let i = 0; i < 6; i++) {
    const local = page.getByRole("button", { name: /Charger \d+ de plus/ });
    if ((await local.count()) === 0) break;
    await local.dispatchEvent("click");
  }

  const server = page.getByRole("button", { name: /Charger plus d'événements/ });
  await expect(server).toBeVisible();
  await server.dispatchEvent("click");

  await expect
    .poll(() => calls.events.some((c) => c.offset === 200))
    .toBe(true);
});

test("la recherche est transmise au serveur", async ({ page }) => {
  const calls = await mockApi(page, { total: 250 });
  await page.goto("/");
  await expect(page.locator("article").first()).toBeVisible();

  await page.locator('input[type="search"]').fill("incendie gard");

  // Anti-rebond de 400 ms côté composant.
  await expect
    .poll(() => calls.events.some((c) => c.q === "incendie gard"), { timeout: 5000 })
    .toBe(true);

  // Une recherche repart toujours de la première page.
  const searchCall = calls.events.find((c) => c.q === "incendie gard");
  expect(searchCall?.offset).toBe(0);
});

test("le fil se remplit et affiche des cartes lisibles", async ({ page }) => {
  await mockApi(page, { total: 30 });
  await page.goto("/");
  const cards = page.locator("article");
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThan(3);
});
