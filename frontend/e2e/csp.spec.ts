import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

/**
 * La CSP de production autorise `'unsafe-eval'`, conservé « pour ne pas
 * diverger » avec le mode développement. C'est pourtant la directive qui coûte
 * le plus cher : elle rend inopérante la principale protection de la CSP
 * contre l'injection de script.
 *
 * Ce test rejoue la politique RÉELLE de nginx, privée d'`'unsafe-eval'`, et
 * échoue si l'application en a besoin. Il documente donc la raison de son
 * retrait, et signalerait une dépendance nouvelle qui le réclamerait.
 *
 * `'unsafe-inline'` est conservé : Next injecte son état d'hydratation en
 * ligne, et l'anti-FOUC du layout est lui aussi un script inline. Les retirer
 * supposerait des nonces générés par requête.
 */
const CSP_SANS_UNSAFE_EVAL =
  "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'self'; " +
  "form-action 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; " +
  "img-src 'self' data: blob: https://*.tile.openstreetmap.org; font-src 'self' data:; " +
  "connect-src 'self' https://nominatim.openstreetmap.org; " +
  "worker-src 'self' blob:; manifest-src 'self'";

test("l'application fonctionne sans 'unsafe-eval'", async ({ page }) => {
  const violations: string[] = [];
  const erreurs: string[] = [];

  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      (window as unknown as { __violations: string[] }).__violations ??= [];
      (window as unknown as { __violations: string[] }).__violations.push(
        `${e.violatedDirective} ← ${e.blockedURI}`
      );
    });
  });

  page.on("pageerror", (e) => erreurs.push(e.message));

  await mockApi(page);

  // Rejoue l'en-tête que sert nginx, privé d''unsafe-eval'.
  await page.route("**/*", async (route) => {
    const reponse = await route.fetch();
    const type = reponse.headers()["content-type"] ?? "";
    if (!type.includes("text/html")) return route.fulfill({ response: reponse });
    return route.fulfill({
      response: reponse,
      headers: { ...reponse.headers(), "content-security-policy": CSP_SANS_UNSAFE_EVAL },
    });
  });

  await page.goto("/");
  // La carte est le composant le plus susceptible d'avoir besoin d'eval :
  // on attend son montage effectif avant de conclure.
  await expect(page.locator(".leaflet-container")).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(1500);

  const relevees = await page.evaluate(
    () => (window as unknown as { __violations?: string[] }).__violations ?? []
  );
  violations.push(...relevees);

  const evalBloque = violations.filter((v) => v.includes("script-src"));
  expect(evalBloque, `violations script-src : ${evalBloque.join(" | ")}`).toEqual([]);
  expect(
    erreurs.filter((e) => /unsafe-eval|EvalError|Content Security Policy/i.test(e))
  ).toEqual([]);
});
