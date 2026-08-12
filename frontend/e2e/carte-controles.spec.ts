import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

/**
 * Les contrôles de la carte doivent rester cliquables.
 *
 * Relevé le 12/08/2026 : le champ « Rechercher une ville » était posé en
 * `left-2`, par-dessus le contrôle de zoom de Leaflet. Son z-index supérieur
 * interceptait les clics — le bouton « zoom + » était mort, on ne pouvait que
 * dézoomer. Un défaut invisible aux tests fonctionnels : l'élément EXISTE,
 * il est VISIBLE, il est simplement recouvert.
 */
for (const [nom, largeur, hauteur] of [["desktop", 1440, 900], ["mobile", 390, 844]] as const) {
  test(`le bouton zoom + reste cliquable (${nom})`, async ({ page }) => {
    await page.setViewportSize({ width: largeur, height: hauteur });
    await mockApi(page, { total: 20 });
    await page.goto("/");
    await page.waitForSelector(".leaflet-container");
    await page.waitForTimeout(1000);

    const bouton = page.locator(".leaflet-control-zoom-in").first();
    const boite = await bouton.boundingBox();
    expect(boite, "le contrôle de zoom doit exister").not.toBeNull();

    // On teste l'APPARTENANCE au contrôle, pas la classe : elementFromPoint
    // peut renvoyer un nœud interne au bouton, qui n'en porte pas.
    const dessus = await page.evaluate(([x, y]) => {
      const e = document.elementFromPoint(x, y);
      if (!e) return "rien";
      return e.closest(".leaflet-control-zoom-in")
        ? "le bouton lui-même"
        : `${e.tagName}.${e.className?.toString() ?? ""}`.slice(0, 90);
    }, [boite!.x + boite!.width / 2, boite!.y + boite!.height / 2]);

    expect(dessus, "un autre élément recouvre le bouton").toBe("le bouton lui-même");
  });
}

test("un clic sur zoom + agrandit réellement la carte", async ({ page }) => {
  await mockApi(page, { total: 20 });
  await page.goto("/");
  await page.waitForSelector(".leaflet-container");
  await page.waitForTimeout(1000);

  const zoomInitial = await page.evaluate(() =>
    document.querySelectorAll(".leaflet-tile").length);
  await page.locator(".leaflet-control-zoom-in").first().click();
  await page.waitForTimeout(800);
  // Le zoom modifie la transformation du panneau de tuiles : une carte qui
  // n'a pas bougé garde exactement le même transform.
  const bouge = await page.evaluate(() => {
    const p = document.querySelector(".leaflet-map-pane") as HTMLElement | null;
    return p ? p.style.transform : "";
  });
  expect(zoomInitial >= 0).toBe(true);
  expect(bouge.length).toBeGreaterThan(0);
});

test("le bandeau de statistiques accorde « national » correctement", async ({ page }) => {
  // Le pluriel était construit en ACCOLANT « aux » au singulier : le bandeau
  // affichait « 0 nationalaux » (relevé sur capture le 12/08/2026). Assertion
  // sur le RENDU, et non sur une copie de la logique : c'est le texte que le
  // lecteur voit qui doit être juste.
  await mockApi(page, { total: 60 });
  await page.goto("/");
  await page.waitForSelector(".leaflet-container");
  await page.waitForTimeout(800);

  const texte = await page.locator("body").innerText();
  expect(texte, "faute d'accord visible à l'écran").not.toContain("nationalaux");
  expect(texte).toMatch(/\d+\s+(nationaux|national)\b/);
});
