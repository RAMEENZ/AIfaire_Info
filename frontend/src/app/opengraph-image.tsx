import { ImageResponse } from "next/og";

/**
 * Carte de partage (Open Graph / Twitter).
 *
 * Sans elle, tout partage du site — WhatsApp, Slack, Mastodon, Discord —
 * n'affichait qu'un rectangle vide, pour un site dont l'usage même est d'être
 * partagé. Le format doit être matriciel : Facebook, WhatsApp, Slack et X
 * ignorent les SVG, une simple copie de l'icône du site n'aurait donc rien
 * donné.
 *
 * Généré au build par `next/og` (satori), sans dépendance supplémentaire —
 * mais la police intégrée n'a QU'UNE graisse : `fontWeight` y est sans effet.
 * La hiérarchie ne peut donc venir que de la taille, de la couleur et de
 * l'espacement. Charger une police variable imposerait un fichier de plus au
 * dépôt et un aléa de build ; le jeu n'en vaut pas la chandelle pour une
 * image de partage.
 */
// L'image est identique à chaque requête : la déclarer statique la fige au
// build. Sans cette ligne, `output: export` (build APK) refuse la route, qui
// lui apparaît comme un gestionnaire dynamique à exécuter côté serveur.
export const dynamic = "force-static";
export const alt = "(ai)Faire Info — actualités et alertes géolocalisées en France";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          position: "relative",
          // Même bleu que le thème et l'icône (#1d4ed8), en dégradé pour ne
          // pas rendre un aplat de 1200×630 parfaitement plat.
          background: "linear-gradient(135deg, #172554 0%, #1d4ed8 60%, #3b82f6 100%)",
          color: "white",
          fontFamily: "sans-serif",
          overflow: "hidden",
        }}
      >
        {/* Disque décoratif, écho de l'icône du site. Débordant du cadre :
            il occupe la moitié droite restée vide sans concurrencer le texte. */}
        <div
          style={{
            position: "absolute",
            right: -170,
            top: -110,
            width: 620,
            height: 620,
            borderRadius: "50%",
            background: "rgba(255,255,255,0.07)",
          }}
        />
        <div
          style={{
            position: "absolute",
            right: -60,
            bottom: -260,
            width: 480,
            height: 480,
            borderRadius: "50%",
            background: "rgba(255,255,255,0.05)",
          }}
        />

        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            padding: "0 90px",
            // Pas de `zIndex` : Satori, qui rend cette image, ne le gère pas et
            // le signale à chaque build depuis Next 16 (« `z-index` is currently
            // not supported »). Il empile dans l'ordre du document, et ce bloc
            // est déclaré APRÈS les deux cercles décoratifs — il passe donc
            // au-dessus sans qu'on ait à le demander. Rendu vérifié.
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline" }}>
            {/* Le « (ai) » reste subordonné par la TAILLE, comme dans le
                logotype de l'application — jamais par un contraste affaibli :
                c'est la faute qui avait fait échouer la CI d'accessibilité. */}
            <span style={{ fontSize: 68, color: "#93c5fd" }}>(ai)</span>
            <span style={{ fontSize: 140, letterSpacing: "-0.035em" }}>Faire</span>
            <span style={{ fontSize: 68, marginLeft: 20, color: "#dbeafe" }}>Info</span>
          </div>

          {/* Filet blanc : sépare le nom de la accroche, et compense
              l'absence de contraste de graisse. */}
          <div
            style={{
              display: "flex",
              width: 128,
              height: 6,
              borderRadius: 3,
              background: "rgba(255,255,255,0.85)",
              margin: "34px 0 30px 0",
            }}
          />

          <div style={{ display: "flex", fontSize: 42, color: "#eff6ff" }}>
            Actualités et alertes géolocalisées en France
          </div>

          <div style={{ display: "flex", fontSize: 28, marginTop: 22, color: "#bfdbfe" }}>
            Météo · Crues · Séismes · Transports · Presse locale
          </div>
        </div>
      </div>
    ),
    size
  );
}
