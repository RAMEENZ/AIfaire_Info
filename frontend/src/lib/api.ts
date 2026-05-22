import { API_BASE_URL } from "./constants";
import { Categorie, EventsResponse, HealthResponse } from "./types";

interface FetchEventsParams {
  bbox?: string | null;
  categories?: Categorie[];
  gravite_min?: number;
  niveau?: string;
  depuis?: string;
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
  const { bbox, categories, gravite_min, niveau, depuis, limit, national_only } = params;

  // FastAPI list params must be repeated (?categories=a&categories=b), not comma-joined
  const search = new URLSearchParams();
  if (bbox) search.set("bbox", bbox);
  if (categories && categories.length > 0) {
    categories.forEach((c) => search.append("categories", c));
  }
  if (gravite_min !== undefined) search.set("gravite_min", String(gravite_min));
  if (niveau) search.set("niveau", niveau);
  if (depuis) search.set("depuis", depuis);
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

export const eventsKey = (params: FetchEventsParams) =>
  ["events", params] as const;

export const healthKey = () => ["health"] as const;
