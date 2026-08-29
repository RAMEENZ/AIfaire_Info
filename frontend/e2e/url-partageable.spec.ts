import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

/**
 * Une vue filtrée doit se partager telle quelle.
 *
 * Les catégories, la gravité et la fenêtre étaient déjà dans l'URL ; le
 * département et la recherche non. « La carte du Finistère filtrée sur les
 * crues » n'était donc pas un lien qu'on pouvait envoyer — celui qui le
 * recevait retombait sur la vue par défaut.
 *
 * Les tests unitaires (src/lib/urlEtat.test.ts) couvrent la sérialisation.
 * Ici on vérifie le BRANCHEMENT : lecture au chargement, et écriture quand
 * l'état change.
 */

test("un département dans l'URL est appliqué au chargement", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?dept=29");

  // Le filtre départemental s'applique côté client : le bandeau nommant le
  // département est la preuve visible que le paramètre a été LU, et pas
  // seulement conservé dans la barre d'adresse.
  await expect(page.getByText(/Finistère \(29\)/)).toBeVisible();
});

test("un département invalide est ignoré, sans carte vide", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?dept=999");

  // L'application doit fonctionner normalement plutôt que d'appliquer un
  // filtre qui ne renverrait jamais rien.
  await expect(page.getByRole("button", { name: "Actualiser" })).toBeVisible();
  // L'URL est réécrite par un effet (serialiserEtat + replaceState), pas au
  // rendu : la lire d'un coup juste après l'apparition du bouton, c'est
  // parier sur l'ordre des deux. Le pari a été perdu en CI le 29/08/2026,
  // sur un commit où rien du frontend n'avait bougé. On attend la valeur au
  // lieu de l'échantillonner — l'assertion porte sur le même fait, sans la
  // course.
  await expect.poll(() => page.url()).not.toContain("dept=999");
});

test("la recherche saisie se retrouve dans l'URL", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");

  const champ = page.getByPlaceholder(/echerch/i).first();
  await champ.fill("incendie");

  // La recherche est anti-rebondie avant d'atteindre l'URL.
  await expect(async () => {
    expect(page.url()).toContain("q=incendie");
  }).toPass({ timeout: 10_000 });
});

test("l'URL reste nue quand rien n'est filtré", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  // Pas de « ?cats=…&g=0&h=48 » qui n'apporterait rien : c'est cette URL-là
  // qu'on copie dans un message.
  await expect(async () => {
    expect(new URL(page.url()).search).toBe("");
  }).toPass({ timeout: 10_000 });
});
