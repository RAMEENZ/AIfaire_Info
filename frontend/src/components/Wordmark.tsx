/**
 * Logotype « (ai)Faire Info », défini une seule fois.
 *
 * Il était recopié dans cinq fichiers — accueil, stats, tendances, page
 * événement, page 404 — ce qui garantissait qu'un changement de nom en
 * oublierait un. Le passage de « FAIRE Info » à « (ai)Faire Info » a été
 * l'occasion de le centraliser.
 *
 * Le « (ai) » porte le jeu de mots : lu d'un trait, « (ai)Faire » donne
 * « affaire ». Il est donc rendu VISIBLE mais subordonné — plus petit, plus
 * léger, dans un bleu plus clair — pour que « Faire » reste le nom que l'œil
 * retient, et que la parenthèse se découvre à la lecture.
 */

type Taille = "sm" | "md" | "lg";

const TAILLES: Record<Taille, { ai: string; faire: string; info: string }> = {
  sm: { ai: "text-xs",  faire: "text-lg",  info: "text-sm" },
  md: { ai: "text-sm",  faire: "text-xl",  info: "text-sm" },
  lg: { ai: "text-2xl", faire: "text-5xl", info: "text-xl" },
};

interface WordmarkProps {
  taille?: Taille;
  /** La page 404 n'affiche que le nom, sans le mot « Info ». */
  avecInfo?: boolean;
  /** Masque « Info » sous 640 px, là où la place manque (barre d'accueil). */
  infoResponsive?: boolean;
}

export default function Wordmark({
  taille = "md",
  avecInfo = true,
  infoResponsive = false,
}: WordmarkProps) {
  const t = TAILLES[taille];
  return (
    <span className="inline-flex items-baseline gap-1 whitespace-nowrap">
      {/* aria-hidden sur les parenthèses seules serait excessif : le lecteur
          d'écran doit entendre le nom complet, parenthèses comprises, comme
          il est écrit. */}
      {/* La subordination du « (ai) » passe par la TAILLE et la GRAISSE, pas
          par un contraste affaibli. La première version l'atténuait en
          opacité (blue-500/70), ce qui donnait #76a8f9 sur blanc : 2,4:1,
          quand WCAG AA en exige 4,5. La CI d'accessibilité l'a rattrapé sur
          les pages Statistiques et Tendances. blue-600 tient 5,2:1 tout en
          restant nettement plus clair que le blue-700 de « Faire ». */}
      <span className={`${t.ai} font-semibold text-blue-600 dark:text-blue-400 tracking-tight`}>
        (ai)
      </span>
      <span className={`${t.faire} font-black text-blue-700 dark:text-blue-300 tracking-tight`}>
        Faire
      </span>
      {avecInfo && (
        <span
          className={`${t.info} font-medium text-gray-500 dark:text-gray-400 ${
            infoResponsive ? "hidden sm:inline" : ""
          }`}
        >
          Info
        </span>
      )}
    </span>
  );
}
