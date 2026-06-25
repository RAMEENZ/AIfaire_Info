export type Categorie =
  | "meteo"
  | "crue"
  | "seisme"
  | "energie"
  | "sante"
  | "transport"
  | "ordre_public"
  | "actualite"
  | "incendie"
  | "nucleaire"
  | "pollution"
  | "cyber";

export type LieuNiveau = "commune" | "departement" | "region" | "national";

export type ConnectorStatusValue = "ok" | "warning" | "error";

export interface Event {
  id: string;
  source: string;
  source_url: string;
  titre: string;
  auteur: string | null;
  date_publication: string;
  date_evenement: string | null;
  categorie: Categorie;
  gravite: number;
  lieu_nom: string | null;
  lieu_code_insee: string | null;
  lieu_lat: number | null;
  lieu_lon: number | null;
  lieu_niveau: LieuNiveau;
  lieu_confiance_geo: number;
  resume_ia: string | null;
  tags: string[];
  cluster_id: string | null;
  score_confiance: number;
  created_at: string;
}

export interface ConnectorStatus {
  name: string;
  last_run: string | null;
  last_error: string | null;
  last_count: number | null;
  last_success: string | null;
  consecutive_failures: number;
  status: ConnectorStatusValue;
}

export interface EventsResponse {
  events: Event[];
  total: number;
  generated_at: string;
}

export interface HealthResponse {
  connectors: ConnectorStatus[];
  next_ingest_at: string | null;
  checked_at: string;
}

export interface EventFilters {
  categories: Categorie[];
  gravite_min: number;
  depuis_heures: number;
  avant?: Date;
}
