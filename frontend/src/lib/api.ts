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

  const query = buildQuery({
    bbox: bbox ?? undefined,
    categories: categories && categories.length > 0 ? categories.join(",") : undefined,
    gravite_min,
    niveau,
    depuis,
    limit,
    national_only,
  });

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
