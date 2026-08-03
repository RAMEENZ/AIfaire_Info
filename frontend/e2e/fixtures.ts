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
    // Répartis sur toute la France métropolitaine, et non massés sur une seule
    // commune : au zoom national, des événements distants de quelques
    // centaines de mètres formeraient une grappe unique et aucun marqueur
    // individuel ne serait cliquable. Moduli premiers entre eux (6 × 7) pour
    // 42 positions distinctes avant répétition.
    lieu_lat: 43.5 + (i % 6) * 1.1,
    lieu_lon: -1.5 + (i % 7) * 1.3,
    lieu_niveau: "commune",
    lieu_confiance_geo: 0.9,
    resume_ia: `Résumé de l'événement ${i}. `.repeat(3),
    tags: ["test"],
    cluster_id: null,
    score_confiance: 1,
    created_at: new Date(now.getTime() - i * 3_600_000).toISOString(),
  };
}

/**
 * Version allégée servie par /events/map : le vrai endpoint omet le résumé et
 * les tags pour diviser la charge utile. La simulation DOIT omettre les mêmes
 * champs — quand elle renvoyait l'événement complet, les tests validaient une
 * bulle de carte que la production n'a jamais affichée (régression de 08/2026 :
 * cliquer un marqueur ne donnait qu'un titre).
 */
export function makeMapEvent(i: number) {
  const {
    resume_ia: _resume,
    tags: _tags,
    score_confiance: _score,
    created_at: _created,
    date_evenement: _dateEvt,
    lieu_confiance_geo: _confiance,
    ...allege
  } = makeEvent(i);
  return allege;
}

export interface MockOptions {
  /** Nombre total d'événements côté « serveur » simulé. */
  total?: number;
  /** Brief renvoyé par /api/brief (null = aucun brief disponible). */
  briefContent?: string | null;
  /** Fait échouer GET /events/{id} (test du repli de la bulle). */
  failEventDetail?: boolean;
}

/** Journal des requêtes /api/events, pour vérifier la pagination. */
export interface ApiCalls {
  events: { offset: number; limit: number; q: string | null }[];
  map: number;
  /** Identifiants demandés via GET /events/{id} (fiches ouvertes sur la carte). */
  detail: string[];
}

export async function mockApi(page: Page, options: MockOptions = {}): Promise<ApiCalls> {
  const total = options.total ?? 250;
  const calls: ApiCalls = { events: [], map: 0, detail: [] };

  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const json = (body: unknown) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

    // Le flux SSE ne se simule pas : on le coupe, le sondage suffit aux tests.
    if (url.pathname.includes("/events/stream")) return route.abort();

    if (url.pathname.endsWith("/events/map")) {
      calls.map += 1;
      return json({
        events: Array.from({ length: Math.min(total, 300) }, (_, i) => makeMapEvent(i)),
        total: Math.min(total, 300),
        generated_at: now.toISOString(),
      });
    }

    // Fiche complète, demandée à l'ouverture d'une bulle sur la carte.
    const detail = /\/events\/(evt-\d+)$/.exec(url.pathname);
    if (detail) {
      calls.detail.push(detail[1]);
      if (options.failEventDetail) return route.fulfill({ status: 500, body: "boom" });
      return json(makeEvent(Number(detail[1].slice(4))));
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
