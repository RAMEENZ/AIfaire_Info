/**
 * Lecture et écriture de l'état de la vue dans l'URL.
 *
 * Ce qui est affiché doit tenir dans le lien : catégories, gravité, fenêtre,
 * département et recherche. Les deux derniers en étaient absents — « la carte
 * du Finistère filtrée sur les crues » n'était pas un lien qu'on pouvait
 * envoyer, alors même que les trois premiers l'étaient déjà.
 *
 * Ces fonctions vivent ici et non dans `app/page.tsx` : Next interdit à un
 * module de page d'exporter autre chose que ses entrées réservées, et de la
 * logique pure se teste mieux à part.
 */
import { ALL_CATEGORIES } from "@/lib/constants";
import { DEPT_CODE_TO_NAME } from "@/lib/departments";
import { Categorie, EventFilters } from "@/lib/types";

/** Fenêtres proposées par l'interface. Toute autre valeur est ignorée. */
const FENETRES = [24, 48, 168, 720];
const FENETRE_DEFAUT = 48;

/** Longueur maximale d'une recherche relue depuis l'URL. */
const MAX_RECHERCHE = 200;

export interface EtatURL {
  filters: EventFilters;
  dept: string | null;
  q: string;
}

export function lireFiltres(search: string): EventFilters {
  const p = new URLSearchParams(search);
  const cats = p.get("cats");
  const categories: Categorie[] = cats
    ? (cats.split(",").filter((c) => ALL_CATEGORIES.includes(c as Categorie)) as Categorie[])
    : ALL_CATEGORIES;
  const gravite_min = Math.max(0, Math.min(3, parseInt(p.get("g") ?? "0", 10) || 0));
  const brute = parseInt(p.get("h") ?? String(FENETRE_DEFAUT), 10);
  const depuis_heures = FENETRES.includes(brute) ? brute : FENETRE_DEFAUT;
  return { categories, gravite_min, depuis_heures };
}

/**
 * Département lu dans l'URL, ou null.
 *
 * Un code inconnu — lien tronqué, faute de frappe — est ignoré : appliquer un
 * filtre départemental invalide donnerait une carte vide sans rien expliquer.
 */
export function lireDept(search: string): string | null {
  const dept = new URLSearchParams(search).get("dept");
  return dept && DEPT_CODE_TO_NAME[dept] ? dept : null;
}

export function lireRecherche(search: string): string {
  return (new URLSearchParams(search).get("q") ?? "").slice(0, MAX_RECHERCHE);
}

export function lireEtat(search: string): EtatURL {
  return { filters: lireFiltres(search), dept: lireDept(search), q: lireRecherche(search) };
}

/**
 * Chaîne de requête correspondant à l'état courant.
 *
 * Les valeurs par défaut sont omises : une URL nue vaut mieux qu'une URL
 * chargée de paramètres qui ne changent rien, et c'est elle qu'on partage.
 */
/**
 * URL du flux Atom correspondant aux filtres affichés.
 *
 * Le flux savait déjà filtrer par catégorie, gravité et département, mais rien
 * dans l'interface ne le proposait : la fonctionnalité existait sans usage
 * possible. Le lien reprend donc l'état courant, pour qu'on s'abonne à ce
 * qu'on regarde.
 *
 * La recherche plein texte n'est PAS reprise : `/feed.rss` ne l'accepte pas
 * (cf. events.py), et la passer donnerait un flux silencieusement plus large
 * que la vue — pire qu'un abonnement refusé.
 */
export function urlFlux(base: string, { filters, dept }: Omit<EtatURL, "q">): string {
  const p = new URLSearchParams();
  if (filters.categories.length !== ALL_CATEGORIES.length) {
    // Le backend attend des `categories` répétées, pas une liste séparée par
    // des virgules : un seul paramètre « a,b » serait rejeté en 422.
    for (const c of filters.categories) p.append("categories", c);
  }
  if (filters.gravite_min > 0) p.set("gravite_min", String(filters.gravite_min));
  if (filters.depuis_heures !== FENETRE_DEFAUT) p.set("depuis_heures", String(filters.depuis_heures));
  if (dept) p.set("dept", dept);
  const qs = p.toString();
  return qs ? `${base}/feed.rss?${qs}` : `${base}/feed.rss`;
}

export function serialiserEtat({ filters, dept, q }: EtatURL): string {
  const p = new URLSearchParams();
  if (filters.categories.length !== ALL_CATEGORIES.length) {
    p.set("cats", filters.categories.join(","));
  }
  if (filters.gravite_min > 0) p.set("g", String(filters.gravite_min));
  if (filters.depuis_heures !== FENETRE_DEFAUT) p.set("h", String(filters.depuis_heures));
  if (dept) p.set("dept", dept);
  if (q) p.set("q", q);
  return p.toString();
}
