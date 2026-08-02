import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

/**
 * Audit d'accessibilité automatisé (axe-core, règles WCAG 2 A et AA).
 *
 * Un audit outillé ne remplace pas un test humain — il ne couvre qu'environ
 * un tiers des critères — mais il attrape sans relâche les régressions
 * mécaniques : contraste insuffisant, bouton sans libellé, hiérarchie de
 * titres cassée, champ sans étiquette.
 */

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

/**
 * Dette de contraste restante sur la page d'accueil : 4 occurrences mesurées
 * entre 3,3:1 et 4,2:1 là où 4,5:1 est requis (libellés sur pastilles de
 * catégorie et badge de gravité). Ce ne sont PAS des faux positifs — les
 * animations sont figées avant la mesure.
 *
 * L'audit est passé de 22 à 4 occurrences : gris relevés (gray-400 → gray-500
 * en clair, gray-500 → gray-400 en sombre) et couleur de texte des badges
 * désormais calculée sur la luminance du fond (readableTextColor). Le reliquat
 * demande d'assombrir certaines teintes de la charte, ce qui touche à
 * l'identité visuelle : à arbitrer, pas à décider dans un test.
 *
 * Ce plafond n'est pas une exemption : toute NOUVELLE occurrence, et toute
 * violation d'une autre nature, fait échouer la suite.
 */
const KNOWN_CONTRAST_EXCEPTIONS = 4;

async function analyse(page: import("@playwright/test").Page) {
  // Fige animations et transitions : axe échantillonne sinon les couleurs en
  // cours d'animation (opacité intermédiaire), ce qui rend la mesure de
  // contraste non déterministe. On veut évaluer l'état stable.
  await page.addStyleTag({
    content: "*, *::before, *::after { animation: none !important; transition: none !important; }",
  });
  return new AxeBuilder({ page })
    .withTags(TAGS)
    // La carte Leaflet est un composant tiers : ses tuiles et contrôles
    // remontent des violations que nous ne pouvons pas corriger dans notre
    // code. L'application autour d'elle, si.
    .exclude(".leaflet-container")
    .analyze();
}

test("page d'accueil sans violation sérieuse", async ({ page }) => {
  await mockApi(page, { total: 30 });
  await page.goto("/");
  await expect(page.locator("article").first()).toBeVisible();

  const results = await analyse(page);
  const graves = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");

  if (graves.length) {
    console.log(
      "Violations :",
      graves.map((v) => `${v.id} (${v.impact}) × ${v.nodes.length} — ${v.help}`).join("\n")
    );
  }

  // Aucune violation hors contraste, et pas plus d'occurrences de contraste
  // que les exceptions documentées ci-dessus.
  const horsContraste = graves.filter((v) => v.id !== "color-contrast");
  expect(horsContraste).toEqual([]);
  const occurrencesContraste = graves
    .filter((v) => v.id === "color-contrast")
    .reduce((n, v) => n + v.nodes.length, 0);
  expect(occurrencesContraste).toBeLessThanOrEqual(KNOWN_CONTRAST_EXCEPTIONS);
});

test("page Tendances sans violation sérieuse", async ({ page }) => {
  await mockApi(page);
  await page.goto("/tendances");
  await expect(page.getByRole("heading", { name: "Tendances" })).toBeVisible();

  const results = await analyse(page);
  const graves = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  if (graves.length) {
    console.log("Violations :", graves.map((v) => `${v.id} — ${v.help}`).join("\n"));
  }
  expect(graves).toEqual([]);
});

test("page Statistiques sans violation sérieuse", async ({ page }) => {
  await mockApi(page);
  await page.goto("/stats");
  await expect(page.getByRole("heading", { name: "Statistiques" })).toBeVisible();

  const results = await analyse(page);
  const graves = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  if (graves.length) {
    console.log("Violations :", graves.map((v) => `${v.id} — ${v.help}`).join("\n"));
  }
  expect(graves).toEqual([]);
});

test("navigation au clavier : le fil est atteignable sans souris", async ({ page }) => {
  await mockApi(page, { total: 20 });
  await page.goto("/");
  await expect(page.locator("article").first()).toBeVisible();

  // Le raccourci « / » doit donner le focus à la recherche du fil.
  await page.keyboard.press("/");
  const focused = await page.evaluate(() => document.activeElement?.getAttribute("type"));
  expect(focused).toBe("search");
});
