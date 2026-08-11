import { API_BASE_URL } from "./constants";
import { Categorie, Event, EventsResponse, HealthResponse } from "./types";

interface FetchEventsParams {
  bbox?: string | null;
  categories?: Categorie[];
  gravite_min?: number;
  niveau?: string;
  depuis?: string;
  avant?: string;
  limit?: number;
  offset?: number;
  national_only?: boolean;
  /** Recherche côté serveur : porte sur toute la base, pas seulement sur
   *  les événements déjà chargés. */
  q?: string;
}

export async function fetchEvents(params: FetchEventsParams = {}): Promise<EventsResponse> {
  const { bbox, categories, gravite_min, niveau, depuis, avant, limit, offset, national_only, q } = params;

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
  if (offset) search.set("offset", String(offset));
  if (q) search.set("q", q);
  if (national_only !== undefined) search.set("national_only", String(national_only));
  const query = search.toString() ? `?${search.toString()}` : "";

  const response = await fetch(`${API_BASE_URL}/events${query}`, {
    next: { revalidate: 0 },
  });

  if (!response.ok) {
    throw new Error(`Erreur API /events : ${response.status} ${response.statusText}`);
  }

  // Une réponse 200 au corps inattendu (page d'erreur d'un intermédiaire,
  // réponse de repli d'un service worker) passait pour des données valides et
  // ne cassait qu'au premier accès à `.events`, loin d'ici. On échoue au point
  // d'entrée : SWR conserve alors les données précédentes et affiche l'erreur.
  const data = (await response.json()) as unknown;
  if (!data || !Array.isArray((data as EventsResponse).events)) {
    throw new Error("Réponse /events inattendue : champ « events » absent");
  }
  return data as EventsResponse;
}

/** Réponse allégée de /events/map : les champs absents sont complétés par des
 * valeurs neutres pour rester compatible avec le type Event. */
type MapEventRaw = Omit<Event, "resume_ia" | "tags" | "score_confiance" | "created_at" | "date_evenement" | "lieu_confiance_geo">;

/**
 * Marqueurs de la carte, chargés indépendamment de la pagination du fil :
 * la carte doit rester complète même quand le fil n'affiche que sa première
 * page. Charge utile réduite (pas de résumé IA) ; le détail complet est
 * récupéré au clic via la fiche événement.
 */
export async function fetchMapEvents(params: {
  categories?: Categorie[];
  gravite_min?: number;
  depuis?: string;
}): Promise<Event[]> {
  const search = new URLSearchParams();
  params.categories?.forEach((c) => search.append("categories", c));
  if (params.gravite_min !== undefined) search.set("gravite_min", String(params.gravite_min));
  if (params.depuis) search.set("depuis", params.depuis);
  const query = search.toString() ? `?${search}` : "";

  const response = await fetch(`${API_BASE_URL}/events/map${query}`, { next: { revalidate: 0 } });
  if (!response.ok) throw new Error(`Erreur API /events/map : ${response.status}`);
  const data = (await response.json()) as unknown;
  // Même durcissement que fetchEvents : une réponse 200 au corps inattendu
  // (page d'erreur d'un intermédiaire, repli d'un service worker) cassait plus
  // loin, au premier .map(), loin de sa cause.
  if (!data || !Array.isArray((data as { events?: unknown }).events)) {
    throw new Error("Réponse /events/map inattendue : champ « events » absent");
  }
  return (data as { events: MapEventRaw[] }).events.map((e) => ({
    ...e,
    date_evenement: null,
    lieu_confiance_geo: 1,
    resume_ia: null,
    tags: [],
    score_confiance: 1,
    created_at: e.date_publication,
  }));
}

// Fiches déjà récupérées, gardées d'un rendu à l'autre : les marqueurs sont
// remontés à chaque rafraîchissement de la carte, sans ce cache la même fiche
// serait redemandée à chaque réouverture de la bulle.
const eventDetailCache = new Map<string, Event>();

/**
 * Fiche complète d'un événement (résumé IA, tags, champs de confiance).
 *
 * Nécessaire pour les marqueurs de la carte : `/events/map` omet le résumé
 * pour alléger la charge utile, et la bulle serait sinon réduite à son titre.
 */
export async function fetchEventDetail(id: string): Promise<Event> {
  const connu = eventDetailCache.get(id);
  if (connu) return connu;

  const response = await fetch(`${API_BASE_URL}/events/${id}`, { next: { revalidate: 0 } });
  if (!response.ok) throw new Error(`Erreur API /events/${id} : ${response.status}`);
  const event = (await response.json()) as Event;
  eventDetailCache.set(id, event);
  return event;
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
