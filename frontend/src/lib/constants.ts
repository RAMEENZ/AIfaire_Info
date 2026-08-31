import { Categorie } from "./types";

export const CATEGORY_CONFIG: Record<
  Categorie,
  { label: string; color: string; icon: string; letter: string }
> = {
  meteo: { label: "Météo", color: "#3B82F6", icon: "⛈", letter: "M" },
  crue: { label: "Crue", color: "#06B6D4", icon: "🌊", letter: "C" },
  // Violet clair volontairement : #8B5CF6 tombait pile au point de bascule
  // (4,19 avec le texte sombre, 4,23 avec le blanc) — les deux sous le seuil
  // WCAG AA de 4,5 pour du texte de 12 px. Le violet foncé étant déjà pris par
  // « Nucléaire », on éclaircit : 6,5 avec le texte sombre, et les deux
  // catégories restent distinguables au premier coup d'œil.
  seisme: { label: "Séisme", color: "#A78BFA", icon: "🌍", letter: "S" },
  energie: { label: "Énergie", color: "#F59E0B", icon: "⚡", letter: "E" },
  sante: { label: "Santé", color: "#10B981", icon: "🏥", letter: "Sa" },
  transport: { label: "Transport", color: "#6B7280", icon: "🚆", letter: "T" },
  ordre_public: { label: "Ordre public", color: "#EF4444", icon: "🚨", letter: "O" },
  actualite: { label: "Actualité", color: "#1F2937", icon: "📰", letter: "A" },
  incendie:    { label: "Incendie",   color: "#DC2626", icon: "🔥", letter: "I"  },
  nucleaire:   { label: "Nucléaire",  color: "#7C3AED", icon: "☢️", letter: "N"  },
  pollution:   { label: "Pollution",  color: "#65A30D", icon: "🌫", letter: "P"  },
  cyber:       { label: "Cyber",      color: "#0EA5E9", icon: "🔐", letter: "Cy" },
  sport:       { label: "Sport",      color: "#DB2777", icon: "⚽", letter: "Sp" },
  economie:    { label: "Économie",   color: "#0D9488", icon: "💶", letter: "Éc" },
  politique:   { label: "Politique",  color: "#4338CA", icon: "🏛️", letter: "Po" },
  culture:     { label: "Culture",    color: "#C026D3", icon: "🎭", letter: "Cu" },
};

export const GRAVITE_CONFIG: Record<
  number,
  { label: string; color: string }
> = {
  0: { label: "Information", color: "#6B7280" },
  1: { label: "Vigilance", color: "#F59E0B" },
  2: { label: "Alerte", color: "#F97316" },
  3: { label: "Urgence", color: "#EF4444" },
};

/**
 * Couleur de texte lisible sur un fond donné (noir ou blanc selon la
 * luminance relative, formule WCAG). Les couleurs vives de catégorie et de
 * gravité — ambre, orange — offrent un contraste insuffisant avec du blanc
 * (2,1:1 pour l'ambre alors que 4,5:1 est requis) : le calcul garantit la
 * lisibilité quelles que soient les couleurs, y compris futures.
 */
export function readableTextColor(hexBackground: string): string {
  const hex = hexBackground.replace("#", "");
  const full = hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex;
  const channel = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  const r = channel(parseInt(full.slice(0, 2), 16));
  const g = channel(parseInt(full.slice(2, 4), 16));
  const b = channel(parseInt(full.slice(4, 6), 16));
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  // Contraste avec le blanc vs avec le quasi-noir : on garde le meilleur.
  const contrastWhite = 1.05 / (luminance + 0.05);
  const contrastBlack = (luminance + 0.05) / 0.05;
  return contrastWhite >= contrastBlack ? "#FFFFFF" : "#111827";
}

export const SOURCE_LABELS: Record<string, string> = {
  meteo_france: "Météo-France",
  vigicrues: "Vigicrues",
  renass: "RéNaSS",
  presse_rss: "Presse",
  sncf: "SNCF",
  bison_fute: "Bison Futé",
  incendies: "Incendies",
  cert_fr: "CERT-FR",
  irsn: "IRSN/ASN",
  air_quality: "Atmo France",
  opensky: "OpenSky",
  bluesky: "BlueSky",
  wikipedia_fr: "Wikinews FR",
  spf: "Santé Publique France",
};

export const ALL_CATEGORIES: Categorie[] = [
  "meteo",
  "crue",
  "seisme",
  "energie",
  "sante",
  "transport",
  "ordre_public",
  "actualite",
  "incendie",
  "nucleaire",
  "pollution",
  "cyber",
  "sport",
  "economie",
  "politique",
  "culture",
];

export const FRANCE_CENTER: [number, number] = [46.5, 2.5];
export const FRANCE_DEFAULT_ZOOM = 6;
export const FRANCE_BOUNDS: [[number, number], [number, number]] = [
  [41.0, -5.5],
  [51.5, 10.0],
];

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

/**
 * Origine publique du site, racine des permaliens partagés.
 *
 * `window.location.origin` ne suffit plus depuis que le front est aussi
 * empaqueté en application Android (Capacitor) : la WebView y sert les
 * fichiers depuis `https://localhost`, adresse qui n'existe que dans le
 * téléphone. Un lien copié depuis l'application aurait été inouvrable par son
 * destinataire — silencieusement, puisqu'il a l'air d'une URL valide.
 *
 * NEXT_PUBLIC_SITE_URL est fournie au build (docker-compose pour le web,
 * build-apk.sh pour l'APK). Sans elle — le cas du `next dev` sur un port
 * quelconque — on retombe sur l'origine courante, qui est alors la bonne.
 */
export function permalienBase(): string {
  const configuree = process.env.NEXT_PUBLIC_SITE_URL;
  if (configuree) return configuree.replace(/\/+$/, "");
  return typeof window !== "undefined" ? window.location.origin : "";
}

/** Permalien partageable vers la page d'un événement. */
export function permalienEvenement(id: string): string {
  return `${permalienBase()}/event/${id}`;
}

// Sondage complet du fil. Le flux SSE (/events/stream) pousse déjà les
// nouveautés en direct : ce sondage n'est qu'un filet de sécurité, il n'a pas
// besoin d'être fréquent. Passé de 5 à 15 min — sur mobile, chaque cycle
// coûtait une réponse de ~120 Ko compressés.
export const REFRESH_INTERVAL = 900_000;

// Taille d'une page du fil. Le chargement historique de 500 événements pesait
// 451 Ko de JSON (mesuré en production). Cette même requête alimente aussi les
// marqueurs de la carte : trop réduire la page viderait la carte. 200 + les
// résumés tronqués côté serveur ramènent la réponse à environ un tiers, sans
// dégarnir la carte ; la suite se charge à la demande.
export const EVENTS_PAGE_SIZE = 200;

/**
 * Neutralise une valeur destinée à un fichier CSV.
 *
 * Un tableur traite comme une FORMULE toute cellule commençant par =, +, -, @
 * ou une tabulation : `=cmd|'/c calc'!A1` s'exécute à l'ouverture du fichier.
 * Les titres et résumés exportés proviennent de flux RSS tiers, donc de textes
 * que nous ne contrôlons pas — c'est exactement le vecteur d'une injection de
 * formule. Le guillemet simple en tête est la parade reconnue : le tableur
 * affiche le texte tel quel et n'évalue rien.
 */
export function csvSafe(valeur: string): string {
  return /^[=+\-@\t\r]/.test(valeur) ? `'${valeur}` : valeur;
}
