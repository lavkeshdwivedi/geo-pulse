/* GeoPulse service worker.
   Goal: make the site installable + usable offline after a first visit.
   Strategy: network-first for HTML (so new editions come through), cache-first
   for static assets (styles, logos), fall back to the cached home page when
   offline. */

const CACHE = 'geopulse-v2';
const CORE = [
  '/',
  '/hi',
  '/styles.css',
  '/favicon.svg',
  '/logo.svg',
  '/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(CORE).catch(() => null))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  // Only handle GETs; let everything else fall through to the network.
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  // Skip cross-origin requests (third-party images, fonts, etc.)
  if (url.origin !== self.location.origin) return;

  // Treat the home pages as navigation — network-first, falling back to cache.
  if (req.mode === 'navigate' || (req.headers.get('accept') || '').includes('text/html')) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => null);
          return res;
        })
        .catch(() =>
          caches.match(req).then((hit) => hit || caches.match('/') || new Response('Offline.', { status: 503, headers: { 'content-type': 'text/plain' } }))
        )
    );
    return;
  }

  // For static assets, cache-first is cheap and makes repeat visits feel snappy.
  event.respondWith(
    caches.match(req).then((hit) => {
      if (hit) return hit;
      return fetch(req)
        .then((res) => {
          if (res && res.status === 200 && res.type === 'basic') {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => null);
          }
          return res;
        })
        .catch(() => hit);
    })
  );
});
