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

/**
 * Carte de chaleur : le greffon leaflet.heat est désormais EMPAQUETÉ avec
 * l'application (import dynamique) et non plus tiré d'unpkg à l'exécution.
 * Un import dynamique qui échoue passe la compilation et le build sans
 * broncher — seule une vérification au navigateur le révèle.
 */
test.describe("carte de chaleur", () => {
  test("le calque se monte sans requête vers un CDN tiers", async ({ page }) => {
    const externes: string[] = [];
    page.on("request", (r) => {
      const url = r.url();
      if (!url.startsWith("http://127.0.0.1") && !url.startsWith("http://localhost")) {
        externes.push(url);
      }
    });
    const erreurs: string[] = [];
    page.on("pageerror", (e) => erreurs.push(e.message));

    await mockApi(page, { total: 40 });
    await page.goto("/");
    await page.waitForSelector(".leaflet-container");

    await page.getByRole("button", { name: /heatmap/i }).click();

    // leaflet.heat dessine dans un <canvas> ajouté au panneau de calques.
    await expect(page.locator(".leaflet-pane canvas")).toBeVisible({ timeout: 10_000 });
    expect(erreurs, `erreurs JS : ${erreurs.join(" | ")}`).toEqual([]);
    expect(
      externes.filter((u) => u.includes("unpkg.com")),
      "plus aucune requête vers unpkg",
    ).toEqual([]);
  });

  test("chaque extinction retire le calque", async ({ page }) => {
    // Portée exacte : ce test couvre le basculement SYNCHRONE, une fois le
    // greffon chargé. Il ne reproduit PAS la course corrigée en même temps
    // (effet relancé avant la résolution de l'import, cleanup ne trouvant
    // rien à retirer) : vérifié par mutation, il passe sans le drapeau
    // d'annulation. Cette garde reste défensive et non couverte.
    await mockApi(page, { total: 40 });
    await page.goto("/");
    await page.waitForSelector(".leaflet-container");

    const bouton = page.getByRole("button", { name: /heatmap/i });
    for (let i = 0; i < 3; i++) {
      await bouton.click();
      await expect(page.locator(".leaflet-pane canvas")).toBeVisible({ timeout: 10_000 });
      await bouton.click();
      await expect(page.locator(".leaflet-pane canvas")).toHaveCount(0);
    }
  });
});

/**
 * Contours départementaux : servis par l'application (public/departements.geojson)
 * et non plus tirés de raw.githubusercontent.com chez chaque visiteur, sur une
 * branche `master` non épinglée.
 *
 * Trois choses seulement une vérification au navigateur peut établir : que le
 * fichier est bien servi à cette URL, qu'il est assez valide pour que Leaflet en
 * tire des tracés, et qu'aucune requête ne part encore vers GitHub. Un chemin
 * erroné passerait la compilation et le build sans broncher — le calque
 * disparaîtrait en silence, exactement comme il aurait disparu le jour où le
 * fichier amont aurait été renommé.
 */
test.describe("contours départementaux", () => {
  test("le calque vient de l'application, pas de GitHub", async ({ page }) => {
    const requetes: string[] = [];
    const reponses: string[] = [];
    page.on("request", (r) => requetes.push(r.url()));
    page.on("response", (r) => {
      const chemin = new URL(r.url()).pathname;
      if (chemin === "/departements.geojson") reponses.push(`${r.status()} ${chemin}`);
    });

    await mockApi(page, { total: 10 });
    await page.goto("/");
    await page.waitForSelector(".leaflet-container");

    // Leaflet rend chaque département en <path>. Le compte attendu est 96
    // (métropole ; l'outre-mer passe par les raccourcis DOM_TOM), mais on ne
    // fige pas ce nombre : il dépend du fichier amont, pas du code. Un seuil
    // large distingue « le calque est là » de « le calque a disparu », qui est
    // la seule chose que ce test doit surveiller. Les marqueurs sont des
    // divIcon, ils n'ajoutent aucun <path>.
    await expect
      .poll(() => page.locator(".leaflet-container path").count(), { timeout: 15_000 })
      .toBeGreaterThan(80);

    expect(
      reponses,
      "le GeoJSON est servi par l'application, en 200",
    ).toContain("200 /departements.geojson");
    expect(
      requetes.filter((u) => u.includes("githubusercontent.com")),
      "plus aucune requête vers GitHub",
    ).toEqual([]);
  });
});
