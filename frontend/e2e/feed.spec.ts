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

test("le bouton Actualiser ne casse pas le fil", async ({ page }) => {
  // `mutate` de SWR prend les DONNÉES en premier argument : branché tel quel
  // sur onClick, il recevait l'événement de clic et rangeait un MouseEvent à la
  // place de la réponse de l'API. Le rendu cassait au premier accès à
  // `.events` — « can't access property "length", P.events is undefined »
  // (signalé le 11/08/2026).
  const erreurs: string[] = [];
  page.on("pageerror", (e) => erreurs.push(e.message));

  const calls = await mockApi(page, { total: 30 });
  await page.goto("/");
  await expect(page.locator("article").first()).toBeVisible();

  const avant = calls.events.length;
  await page.getByRole("button", { name: /Actualiser/i }).click();

  // Une vraie requête est repartie…
  await expect.poll(() => calls.events.length).toBeGreaterThan(avant);
  // …le fil est toujours là, et rien n'a explosé.
  await expect(page.locator("article").first()).toBeVisible();
  expect(erreurs).toEqual([]);

  // Le compteur de l'en-tête ne doit jamais afficher « undefined » : c'est ce
  // que donnait un `total` absent. (SWR revalide dans la foulée, si bien que ce
  // test seul ne distingue pas le correctif de fond des garde-fous défensifs —
  // c'est le test suivant, sur une réponse malformée, qui épingle la cause.)
  const entete = await page.locator("header").innerText();
  expect(entete).not.toContain("undefined");
  expect(entete).not.toContain("NaN");
  await expect(page.locator("header")).toContainText(/\d+ événements/);
});

test("une réponse sans champ « events » est rejetée au lieu de casser le rendu", async ({ page }) => {
  const erreurs: string[] = [];
  page.on("pageerror", (e) => erreurs.push(e.message));

  await mockApi(page, { total: 30 });
  await page.goto("/");
  await expect(page.locator("article").first()).toBeVisible();

  // Un intermédiaire renvoie un 200 au corps inattendu.
  await page.route("**/api/events?*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: '{"detail":"oops"}' })
  );
  await page.getByRole("button", { name: /Actualiser/i }).click();
  await page.waitForTimeout(1000);

  // SWR conserve les données précédentes : le fil reste affiché, pas d'erreur.
  await expect(page.locator("article").first()).toBeVisible();
  expect(erreurs).toEqual([]);
});
