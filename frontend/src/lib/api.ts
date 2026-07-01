import { API_BASE_URL } from "./constants";
import { Categorie, EventsResponse, HealthResponse } from "./types";

interface FetchEventsParams {
  bbox?: string | null;
  categories?: Categorie[];
  gravite_min?: number;
  niveau?: string;
  depuis?: string;
  avant?: string;
  limit?: number;
  national_only?: boolean;
}

function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const str = search.toString();
  return str ? `?${str}` : "";
}

export async function fetchEvents(params: FetchEventsParams = {}): Promise<EventsResponse> {
  const { bbox, categories, gravite_min, niveau, depuis, avant, limit, national_only } = params;

  // FastAPI list params must be repeated (?categories=a&categories=b), not comma-joined
  const search = new URLSearchParams();
  if (bbox) search.set("bbox", bbox);
  if (categories && categories.length > 0) {
    categories.forEach((c) => search.append("categories", c));
  }
  if (gravite_min !== undefined) search.set("gravite_min", String(gravite_min));
  if (niveau) search.set("niveau", niveau);
  if (depuis) search.set("depuis", depuis);
  if (avant) search.set("avant", avant);
  if (limit !== undefined) search.set("limit", String(limit));
  if (national_only !== undefined) search.set("national_only", String(national_only));
  const query = search.toString() ? `?${search.toString()}` : "";

  const response = await fetch(`${API_BASE_URL}/events${query}`, {
    next: { revalidate: 0 },
  });

  if (!response.ok) {
    throw new Error(`Erreur API /events : ${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<EventsResponse>;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`, {
    next: { revalidate: 0 },
  });

  if (!response.ok) {
    throw new Error(`Erreur API /health : ${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<HealthResponse>;
}

export async function triggerIngest(): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE_URL}/ingest/run`, { method: "POST" });
  if (!response.ok) {
    // 401 = INGEST_API_KEY requis (non transmis par le front public),
    // 503 = endpoint verrouillé en prod sans clé. Message explicite pour la console.
    throw new Error(`Erreur ingestion : ${response.status} ${response.statusText}`);
  }
  return response.json();
}

export interface TrendItem {
  categorie: string;
  recent_count: number;
  daily_avg_per_2h: number;
  ratio: number;
}

export interface StatsData {
  total_events: number;
  by_source: Record<string, number>;
  by_categorie: Record<string, number>;
  localized: number;
  national: number;
  oldest_event: string | null;
  newest_event: string | null;
}

export async function fetchTrends(): Promise<{ trends: TrendItem[]; generated_at: string }> {
  const response = await fetch(`${API_BASE_URL}/trends`, { next: { revalidate: 0 } });
  if (!response.ok) throw new Error(`Erreur API /trends : ${response.status}`);
  return response.json();
}

export async function fetchStats(): Promise<StatsData> {
  const response = await fetch(`${API_BASE_URL}/stats`, { next: { revalidate: 0 } });
  if (!response.ok) throw new Error(`Erreur API /stats : ${response.status}`);
  return response.json();
}

export const eventsKey = (params: FetchEventsParams) =>
  ["events", params] as const;

export const healthKey = () => ["health"] as const;

export interface TimelineBucket {
  time: string;
  count: number;
  max_gravite: number;
}

export async function fetchTimeline(params: {
  depuis?: string;
  avant?: string;
  categories?: Categorie[];
  gravite_min?: number;
  bucket?: "hour" | "day";
}): Promise<{ since: string; until: string; bucket: string; buckets: TimelineBucket[] }> {
  const search = new URLSearchParams();
  if (params.depuis) search.set("depuis", params.depuis);
  if (params.avant) search.set("avant", params.avant);
  if (params.categories?.length) params.categories.forEach((c) => search.append("categories", c));
  if (params.gravite_min !== undefined) search.set("gravite_min", String(params.gravite_min));
  if (params.bucket) search.set("bucket", params.bucket);
  const query = search.toString() ? `?${search}` : "";
  const response = await fetch(`${API_BASE_URL}/events/timeline${query}`, { next: { revalidate: 0 } });
  if (!response.ok) throw new Error(`Erreur API /events/timeline : ${response.status}`);
  return response.json();
}
