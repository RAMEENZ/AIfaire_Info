/**
 * Accès à localStorage qui ne peut pas faire tomber la page.
 *
 * Les ÉCRITURES étaient déjà protégées un peu partout ; les lectures ne
 * l'étaient pas. Or `getItem` lève, et pas seulement `setItem` : Safari en
 * navigation privée stricte, une politique d'entreprise, ou un navigateur
 * réglé pour bloquer les données de site font échouer le simple accès à
 * `window.localStorage`. Ces lectures se font dans des effets React — une
 * exception y remonte jusqu'à la frontière d'erreur, et l'utilisateur voit la
 * page d'erreur au lieu de la carte, pour une préférence d'affichage.
 *
 * Le repli est toujours silencieux : perdre un thème mémorisé n'est pas un
 * incident, le signaler à l'utilisateur en serait un.
 */

export function lireStockage(cle: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(cle);
  } catch {
    return null;
  }
}

export function ecrireStockage(cle: string, valeur: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(cle, valeur);
  } catch {
    /* quota plein, mode privé, stockage bloqué : préférence non persistée */
  }
}

export function effacerStockage(cle: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(cle);
  } catch {
    /* idem : rien à rattraper */
  }
}
