/**
 * Fabrique les images sources de l'application Android à partir de l'unique
 * fichier de marque du dépôt, `frontend/public/icon.svg`.
 *
 * Le site n'a qu'une icône SVG : suffisant pour un navigateur, mais Android
 * veut des matrices, à plusieurs densités, et une icône adaptative découpée en
 * deux calques (fond + avant-plan) que le lanceur recadre en cercle, en
 * « squircle » ou en goutte selon le constructeur. Dessiner ces images à la
 * main les aurait fait diverger de la marque à la première retouche ; on les
 * dérive.
 *
 * Sortie : mobile/assets/*.png, que `@capacitor/assets` décline ensuite en
 * mipmaps et drawables (voir build-apk.sh).
 */
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const ici = dirname(fileURLToPath(import.meta.url));
const racine = join(ici, "..");
const source = join(racine, "..", "frontend", "public", "icon.svg");
const sortie = join(racine, "assets");

// Bleu de la marque (theme_color du manifeste web) et fond sombre de l'app.
const BLEU = "#1d4ed8";
const SOMBRE = "#111827";

/**
 * L'avant-plan d'une icône adaptative n'occupe que le carré central : le
 * lanceur peut rogner jusqu'à ~33 % de chaque bord, et anime l'icône en la
 * décalant. Le glyphe est donc réduit à 60 % du canevas, marge comprise —
 * sans quoi la barre du « F » serait tranchée sur les lanceurs qui rognent
 * le plus.
 */
const GLYPHE = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <path d="M20 14h24v5H26v8h16v5H26v16h-6V14z" fill="white"/>
</svg>`;

async function png(entree, taille) {
  return sharp(Buffer.from(entree)).resize(taille, taille).png().toBuffer();
}

/** Image pleine : un aplat de couleur avec le logo centré à `ratio` du côté. */
async function composee(taille, fond, logo, ratio) {
  const cote = Math.round(taille * ratio);
  return sharp({
    create: { width: taille, height: taille, channels: 4, background: fond },
  })
    .composite([{ input: await png(logo, cote), gravity: "centre" }])
    .png()
    .toBuffer();
}

const icone = await sharp(source).resize(1024, 1024).png().toBuffer();

await mkdir(sortie, { recursive: true });
const fichiers = {
  // Icône « classique » (Android < 8 et boutique) : le disque bleu complet.
  "icon-only.png": icone,
  // Calques de l'icône adaptative (Android 8+).
  "icon-background.png": await composee(1024, BLEU, `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>`, 1),
  "icon-foreground.png": await composee(1024, { r: 0, g: 0, b: 0, alpha: 0 }, GLYPHE, 0.6),
  // Écrans de démarrage. Carrés et surdimensionnés : Capacitor y découpe le
  // format de chaque appareil, du téléphone en portrait à la tablette.
  "splash.png": await composee(2732, "#ffffff", await sharp(source).png().toBuffer(), 0.2),
  "splash-dark.png": await composee(2732, SOMBRE, await sharp(source).png().toBuffer(), 0.2),
};

for (const [nom, donnees] of Object.entries(fichiers)) {
  await writeFile(join(sortie, nom), donnees);
  console.log(`écrit assets/${nom}`);
}

// --- Déclinaison en ressources Android -------------------------------------
//
// `@capacitor/assets` produit mipmaps, drawables et écrans de démarrage, puis
// écrit une icône adaptative dont le CALQUE DE FOND est une image encartée de
// 16,7 %. Un fond encarté laisse les coins transparents : sur les lanceurs qui
// découpent au-delà du cercle de 72 dp — carré arrondi de Samsung, « squircle »
// de Pixel — l'icône apparaît bordée de vide. Le fond d'une icône adaptative
// doit couvrir les 108 dp entiers ; seul l'avant-plan se garde une marge.
//
// On repasse donc derrière l'outil pour poser un aplat de couleur en fond.
// Le faire ici, et non à la main dans le projet Android, garde la correction
// en vigueur après chaque régénération.
import { spawnSync } from "node:child_process";

const args = [
  "@capacitor/assets", "generate", "--android",
  "--iconBackgroundColor", BLEU, "--iconBackgroundColorDark", BLEU,
  "--splashBackgroundColor", "#ffffff", "--splashBackgroundColorDark", SOMBRE,
];
const res = spawnSync("npx", args, { cwd: racine, stdio: ["ignore", "pipe", "inherit"] });
if (res.status !== 0) process.exit(res.status ?? 1);
console.log(String(res.stdout).trim().split("\n").slice(-3).join("\n"));

const res_ = join(racine, "android", "app", "src", "main", "res");
await writeFile(
  join(res_, "values", "ic_launcher_background.xml"),
  `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">${BLEU}</color>\n</resources>\n`
);
const adaptative = `<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background" />
    <foreground>
        <inset android:drawable="@mipmap/ic_launcher_foreground" android:inset="16.7%" />
    </foreground>
</adaptive-icon>
`;
for (const nom of ["ic_launcher.xml", "ic_launcher_round.xml"]) {
  await writeFile(join(res_, "mipmap-anydpi-v26", nom), adaptative);
  console.log(`corrigé res/mipmap-anydpi-v26/${nom} (fond plein)`);
}
