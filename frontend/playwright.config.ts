import { defineConfig, devices } from "@playwright/test";

/**
 * Tests de bout en bout de l'interface. Les appels /api/ sont simulés
 * (voir e2e/fixtures.ts) : aucun backend, aucune base — rapide et
 * déterministe, y compris en CI.
 *
 * Chromium est préinstallé dans l'image de développement
 * (PLAYWRIGHT_BROWSERS_PATH) ; en CI, `npx playwright install chromium`
 * s'en charge.
 */
// Certains environnements (image de dev, runners d'entreprise) fournissent
// déjà un Chromium et interdisent le téléchargement : CHROMIUM_PATH permet de
// le désigner. En CI publique, `npx playwright install chromium` suffit et la
// variable reste vide.
const chromiumPath = process.env.CHROMIUM_PATH;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    // Service worker neutralisé pendant les tests. `page.route()` n'intercepte
    // PAS les requêtes émises par un service worker : dès que celui-ci prend
    // la main (skipWaiting + clients.claim, donc en quelques centaines de
    // millisecondes), les appels d'API lui passent par-dessus et la simulation
    // d'e2e/fixtures.ts cesse de s'appliquer. Les tests qui agissent APRÈS le
    // chargement initial — « charger plus », recherche, Actualiser, clic sur un
    // marqueur — tombaient alors en timeout, sans rapport avec ce qu'ils
    // vérifient.
    //
    // La suite n'en couvrait pas moins qu'avant : elle ne tenait que parce que
    // l'API y est CROSS-ORIGIN (NEXT_PUBLIC_API_BASE_URL non défini au build →
    // http://localhost:8000/api, quand la page est servie sur 127.0.0.1:3000),
    // cas que le worker laissait sortir. En production l'API est same-origin
    // sous /api : le worker l'intercepte, et l'a toujours fait. Ce chemin-là
    // n'a donc jamais été exercé ici, et ce réglage ne retire aucune
    // couverture — il rend seulement la simulation déterministe.
    serviceWorkers: "block",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        ...(chromiumPath ? { launchOptions: { executablePath: chromiumPath } } : {}),
      },
    },
  ],
  // Sert le build de production : c'est lui qui part en déploiement.
  webServer: {
    // NEXT_PUBLIC_SITE_URL est inlinée au BUILD, pas au démarrage : elle est
    // ici pour le cas où le serveur reconstruit, et surtout pour documenter
    // la valeur qu'attend e2e/autodiscovery.spec.ts. La CI construit avec la
    // même (cf. .github/workflows/ci.yml).
    command: "npm run start",
    env: { NEXT_PUBLIC_SITE_URL: "http://127.0.0.1:3000" },
    url: "http://127.0.0.1:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
