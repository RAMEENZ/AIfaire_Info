import type { Page } from "@playwright/test";

/**
 * Jeu de données et interception d'API partagés par les tests E2E.
 * Les tests tournent sans backend : toutes les routes /api/ sont simulées,
 * ce qui les rend rapides, déterministes et exécutables en CI.
 */
const now = new Date();

export function makeEvent(i: number) {
  return {
    id: `evt-${i}`,
    source: "presse_rss",
    source_url: `https://example.com/article-${i}`,
    titre: `Événement de test ${i} au titre suffisamment long pour occuper deux lignes`,
    auteur: "Source Test",
    date_publication: new Date(now.getTime() - i * 3_600_000).toISOString(),
    date_evenement: null,
    categorie: ["meteo", "crue", "transport", "sante", "actualite"][i % 5],
    gravite: i % 4,
    lieu_nom: `Ville ${i}`,
    lieu_code_insee: `690${(i % 9) + 10}`,
    lieu_lat: 45.75 + (i % 10) * 0.01,
    lieu_lon: 4.85 + (i % 10) * 0.01,
    lieu_niveau: "commune",
    lieu_confiance_geo: 0.9,
    resume_ia: `Résumé de l'événement ${i}. `.repeat(3),
    tags: ["test"],
    cluster_id: null,
    score_confiance: 1,
    created_at: new Date(now.getTime() - i * 3_600_000).toISOString(),
  };
}

export interface MockOptions {
  /** Nombre total d'événements côté « serveur » simulé. */
  total?: number;
  /** Brief renvoyé par /api/brief (null = aucun brief disponible). */
  briefContent?: string | null;
}

/** Journal des requêtes /api/events, pour vérifier la pagination. */
export interface ApiCalls {
  events: { offset: number; limit: number; q: string | null }[];
  map: number;
}

export async function mockApi(page: Page, options: MockOptions = {}): Promise<ApiCalls> {
  const total = options.total ?? 250;
  const calls: ApiCalls = { events: [], map: 0 };

  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const json = (body: unknown) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

    // Le flux SSE ne se simule pas : on le coupe, le sondage suffit aux tests.
    if (url.pathname.includes("/events/stream")) return route.abort();

    if (url.pathname.endsWith("/events/map")) {
      calls.map += 1;
      return json({
        events: Array.from({ length: Math.min(total, 300) }, (_, i) => makeEvent(i)),
        total: Math.min(total, 300),
        generated_at: now.toISOString(),
      });
    }

    if (url.pathname.endsWith("/events")) {
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 200);
      const q = url.searchParams.get("q");
      calls.events.push({ offset, limit, q });
      const count = Math.max(0, Math.min(limit, total - offset));
      return json({
        events: Array.from({ length: count }, (_, i) => makeEvent(offset + i)),
        total,
        generated_at: now.toISOString(),
        offset,
        has_more: offset + count < total,
      });
    }

    if (url.pathname.includes("/brief/history")) return json({ briefs: [] });
    if (url.pathname.includes("/brief")) {
      const content = options.briefContent;
      return content === null || content === undefined
        ? json({ brief: null, message: "Aucun brief disponible." })
        : json({
            date: now.toISOString(),
            content,
            event_count: 42,
            generated_at: now.toISOString(),
          });
    }
    if (url.pathname.includes("/health")) {
      return json({ connectors: [], checked_at: now.toISOString(), next_ingest_at: null });
    }
    if (url.pathname.includes("/trends")) return json({ trends: [], generated_at: now.toISOString() });
    if (url.pathname.includes("/events/timeline")) {
      return json({ since: "", until: "", bucket: "day", buckets: [] });
    }
    if (url.pathname.includes("/stats/history")) return json({ days: 90, stats: [] });
    if (url.pathname.includes("/stats")) {
      return json({
        total_events: total, by_source: {}, by_categorie: {},
        localized: total, national: 0, oldest_event: null, newest_event: null,
      });
    }
    return json({});
  });

  return calls;
}
