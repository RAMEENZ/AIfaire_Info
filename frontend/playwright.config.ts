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
    command: "npm run start",
    url: "http://127.0.0.1:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
