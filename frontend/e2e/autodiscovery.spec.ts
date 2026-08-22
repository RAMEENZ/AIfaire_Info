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

/**
 * Chaque partage — WhatsApp, Slack, Mastodon, Discord — n'affichait qu'un
 * rectangle vide, faute d'image Open Graph.
 */
test("la carte de partage est déclarée, en PNG et en URL absolue", async ({ page }) => {
  await page.goto("/");

  const image = page.locator('meta[property="og:image"]');
  await expect(image).toHaveCount(1);

  const src = await image.getAttribute("content");
  // Le piège : sans `metadataBase`, Next retombe sur http://localhost:3000/…
  // Les robots d'aperçu iraient chercher l'image sur LEUR machine, et la
  // carte resterait vide — un défaut invisible depuis un navigateur, puisque
  // la page s'affiche parfaitement.
  //
  // Le serveur de test tourne avec NEXT_PUBLIC_SITE_URL=http://127.0.0.1:3000
  // (playwright.config.ts) : une base absente redonnerait « localhost », un
  // hôte DIFFÉRENT, et l'assertion ci-dessous tomberait.
  expect(src).toMatch(/^https?:\/\//);
  expect(src).toContain("127.0.0.1:3000");

  // PNG obligatoire : Facebook, WhatsApp, Slack et X ignorent le SVG.
  await expect(page.locator('meta[property="og:image:type"]')).toHaveAttribute(
    "content",
    "image/png"
  );
  await expect(page.locator('meta[property="og:image:width"]')).toHaveAttribute(
    "content",
    "1200"
  );

  // Et l'image doit réellement se télécharger.
  const reponse = await page.request.get(src!);
  expect(reponse.status()).toBe(200);
  expect(reponse.headers()["content-type"]).toContain("image/png");
});

test("robots.txt ouvre les pages, écarte l'API et annonce le plan", async ({ page }) => {
  const r = await page.request.get("/robots.txt");
  expect(r.status()).toBe(200);
  const texte = await r.text();
  expect(texte).toContain("Allow: /");
  // Les réponses JSON n'ont rien à faire dans un index de recherche, et les
  // explorer consommerait la limite de débit pour rien.
  expect(texte).toContain("Disallow: /api/");
  expect(texte).toMatch(/Sitemap: https?:\/\/.+\/sitemap\.xml/);
});

test("le plan du site ne liste que les pages stables", async ({ page }) => {
  const r = await page.request.get("/sitemap.xml");
  expect(r.status()).toBe(200);
  const xml = await r.text();
  expect(xml).toContain("/stats");
  expect(xml).toContain("/tendances");
  // Les pages événement sont purgées au bout de 36 h à 30 jours : les lister
  // produirait un plan majoritairement composé de 404.
  expect(xml).not.toContain("/event/");
});
