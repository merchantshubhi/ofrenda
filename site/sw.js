
const CACHE_NAME = "ofrenda-v1";

const APP_FILES = [
  "./",
  "./index.html",
  "./style.css",
  "./app.js",
  "./altar.js",
  "./model.js",
  "./models3d.js",
  "./viewer.js",
  "./machine-config.json",
  "./generated/machines.json",
  "./manifest.json",
  "./vendor/three.module.js",
  "./vendor/three.core.js",
  "./vendor/OrbitControls.js"
];

// Install and cache essential application files
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async cache => {
      const results = await Promise.allSettled(
        APP_FILES.map(file => cache.add(file))
      );

      const failed = results
        .map((result, index) => ({
          result,
          file: APP_FILES[index]
        }))
        .filter(item => item.result.status === "rejected");

      if (failed.length) {
        console.warn(
          "Some files could not be cached:",
          failed.map(item => item.file)
        );
      }
    })
  );

  self.skipWaiting();
});

// Remove outdated caches
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

// Handle website requests
self.addEventListener("fetch", event => {
  const request = event.request;

  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Only handle resources from this website
  if (url.origin !== self.location.origin) return;

  // Network-first for page navigation
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME)
              .then(cache => cache.put(request, copy));
          }
          return response;
        })
        .catch(async () => {
          return (
            await caches.match(request)
          ) || (
            await caches.match("./index.html")
          );
        })
    );
    return;
  }

  // Cache-first for scripts, styles, data and assets
  event.respondWith(
    caches.match(request).then(async cached => {
      if (cached) return cached;

      try {
        const response = await fetch(request);

        if (response.ok) {
          const copy = response.clone();
          const cache = await caches.open(CACHE_NAME);
          await cache.put(request, copy);
        }

        return response;
      } catch {
        return new Response(
          "This resource is unavailable offline.",
          {
            status: 503,
            headers: {
              "Content-Type": "text/plain"
            }
          }
        );
      }
    })
  );
});
