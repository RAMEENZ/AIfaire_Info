import { Categorie } from "./types";

export const CATEGORY_CONFIG: Record<
  Categorie,
  { label: string; color: string; icon: string; letter: string }
> = {
  meteo: { label: "Météo", color: "#3B82F6", icon: "⛈", letter: "M" },
  crue: { label: "Crue", color: "#06B6D4", icon: "🌊", letter: "C" },
  seisme: { label: "Séisme", color: "#8B5CF6", icon: "🌍", letter: "S" },
  energie: { label: "Énergie", color: "#F59E0B", icon: "⚡", letter: "E" },
  sante: { label: "Santé", color: "#10B981", icon: "🏥", letter: "Sa" },
  transport: { label: "Transport", color: "#6B7280", icon: "🚆", letter: "T" },
  ordre_public: { label: "Ordre public", color: "#EF4444", icon: "🚨", letter: "O" },
  actualite: { label: "Actualité", color: "#1F2937", icon: "📰", letter: "A" },
  incendie:    { label: "Incendie",   color: "#DC2626", icon: "🔥", letter: "I"  },
  nucleaire:   { label: "Nucléaire",  color: "#7C3AED", icon: "☢️", letter: "N"  },
  pollution:   { label: "Pollution",  color: "#65A30D", icon: "🌫", letter: "P"  },
  cyber:       { label: "Cyber",      color: "#0EA5E9", icon: "🔐", letter: "Cy" },
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

export const SOURCE_LABELS: Record<string, string> = {
  meteo_france: "Météo-France",
  vigicrues: "Vigicrues",
  renass: "RéNaSS",
  enedis: "Enedis",
  presse_rss: "Presse",
  sncf: "SNCF",
  bison_fute: "Bison Futé",
  incendies: "Incendies",
  cert_fr: "CERT-FR",
  irsn: "IRSN/ASN",
  air_quality: "Atmo France",
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
];

export const FRANCE_CENTER: [number, number] = [46.5, 2.5];
export const FRANCE_DEFAULT_ZOOM = 6;
export const FRANCE_BOUNDS: [[number, number], [number, number]] = [
  [41.0, -5.5],
  [51.5, 10.0],
];

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

export const REFRESH_INTERVAL = 300_000;
