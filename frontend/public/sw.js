/* Service worker de FAIRE Info — mode hors ligne minimal et prudent.
 *
 * Principes (une app d'alertes se consulte souvent en connexion dégradée) :
 *  - Le réseau reste PRIORITAIRE partout : le cache n'est qu'un filet. Aucune
 *    donnée périmée n'est servie tant que le réseau répond.
 *  - Le HTML n'est jamais servi depuis le cache quand le réseau fonctionne :
 *    un HTML figé référencerait des chunks JS supprimés au déploiement suivant
 *    (le piège classique du service worker).
 *  - CACHE_VERSION est incrémenté à chaque évolution de ce fichier ; tous les
 *    caches d'une autre version sont supprimés à l'activation.
 *  - skipWaiting + clients.claim : une nouvelle version prend la main
 *    immédiatement, sans laisser un ancien worker piloter la page.
 */
const CACHE_VERSION = "faire-info-v1";
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;
const API_CACHE = `${CACHE_VERSION}-api`;

// Nombre de réponses d'API conservées (les dernières vues suffisent au repli).
const API_CACHE_MAX = 12;

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(RUNTIME_CACHE));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names.filter((n) => !n.startsWith(CACHE_VERSION)).map((n) => caches.delete(n))
      );
      await self.clients.claim();
    })()
  );
});

/** Borne la taille d'un cache (FIFO : les entrées les plus anciennes sautent). */
async function trimCache(cacheName, maxEntries) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  if (keys.length <= maxEntries) return;
  await Promise.all(keys.slice(0, keys.length - maxEntries).map((k) => cache.delete(k)));
}

// ── Notifications Web Push ───────────────────────────────────────────────
self.addEventListener("push", (event) => {
  if (!event.data) return;
  let payload = {};
  try {
    payload = event.data.json();
  } catch {
    payload = { title: "FAIRE Info", body: event.data.text() };
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || "FAIRE Info", {
      body: payload.body || "",
      icon: "/icon.svg",
      badge: "/icon.svg",
      // `tag` : une reprise du même fait (même cluster) remplace la
      // notification précédente au lieu d'en empiler une seconde.
      tag: payload.tag || "faire-info",
      data: { url: payload.url || "/" },
      lang: "fr",
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      // Réutilise un onglet déjà ouvert plutôt que d'en empiler un nouveau.
      for (const client of clients) {
        if ("focus" in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    })
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Seules les lectures simples sont concernées : jamais POST /ingest/run,
  // ni les flux SSE (connexion longue, incompatible avec une mise en cache).
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.includes("/events/stream")) return;

  // Assets versionnés par empreinte : immuables, cache d'abord.
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(RUNTIME_CACHE).then((c) => c.put(request, copy));
            }
            return res;
          })
      )
    );
    return;
  }

  // API : réseau d'abord, cache en repli si la requête échoue (hors ligne).
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(API_CACHE).then(async (c) => {
              await c.put(request, copy);
              trimCache(API_CACHE, API_CACHE_MAX);
            });
          }
          return res;
        })
        .catch(async () => {
          const hit = await caches.match(request);
          if (hit) {
            // En-tête de traçabilité : le client peut signaler des données
            // issues du cache plutôt que du réseau.
            const body = await hit.blob();
            const headers = new Headers(hit.headers);
            headers.set("X-From-Cache", "1");
            return new Response(body, { status: hit.status, headers });
          }
          return new Response(
            JSON.stringify({ events: [], total: 0, offline: true }),
            { status: 503, headers: { "Content-Type": "application/json" } }
          );
        })
    );
    return;
  }

  // Navigation (HTML) : réseau d'abord, dernière page connue en repli.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(RUNTIME_CACHE).then((c) => c.put("offline-shell", copy));
          }
          return res;
        })
        .catch(async () => (await caches.match("offline-shell")) || Response.error())
    );
  }
});
