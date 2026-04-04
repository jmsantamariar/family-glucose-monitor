/**
 * Service Worker — Family Glucose Monitor PWA
 *
 * Strategy: app-shell caching.
 *   - On install, pre-cache the three app-shell pages.
 *   - On fetch, try the network first; fall back to the cache when offline.
 *   - Cache is versioned so that a new deployment purges stale entries.
 */

const CACHE_NAME = "fgm-shell-v1";

/** Pages that form the app shell and should work offline. */
const APP_SHELL = ["/", "/login", "/setup"];

// ── Install: pre-cache the app shell ────────────────────────────────────────
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: remove caches from previous versions ──────────────────────────
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// ── Fetch: network-first, fall back to cache ─────────────────────────────────
self.addEventListener("fetch", (event) => {
  // Only intercept same-origin GET requests for navigations (HTML pages).
  // API calls and external resources (Chart.js CDN) are always fetched live.
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  const isSameOrigin = url.origin === self.location.origin;
  const isNavigation = request.mode === "navigate";

  if (!isSameOrigin || !isNavigation) return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        // Refresh the cached copy on every successful navigation response.
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      })
      .catch(() =>
        // Network failed — serve whatever is in the cache.
        caches.match(request).then((cached) => {
          if (cached) return cached;
          return new Response(
            `<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Sin conexión — Glucosa</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #0d1117; color: #e2e8f0;
           display: flex; align-items: center; justify-content: center;
           min-height: 100vh; margin: 0; }
    .box { text-align: center; padding: 2rem; }
    h1 { font-size: 2rem; margin-bottom: 1rem; }
    p  { color: #a0aec0; margin-bottom: 1.5rem; }
    button { background: #2b6cb0; color: #fff; border: none; padding: .75rem 2rem;
             border-radius: 8px; font-size: 1rem; cursor: pointer; }
    button:hover { background: #2c5282; }
  </style>
</head>
<body>
  <div class="box">
    <h1>📶 Sin conexión</h1>
    <p>No se pudo contactar el servidor. Comprueba tu red e inténtalo de nuevo.</p>
    <button onclick="location.reload()">Reintentar</button>
  </div>
</body>
</html>`,
            {
              status: 503,
              headers: { "Content-Type": "text/html; charset=utf-8" },
            }
          );
        })
      )
  );
});
