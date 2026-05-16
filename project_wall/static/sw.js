// ProjectWall service worker — installable PWA shell + offline fallback.
// Strategy:
//   * shell assets  -> cache-first (instant load, works offline)
//   * /api/* + ws    -> network-first, fall back to last cached response
const CACHE = 'projectwall-v1';
const SHELL = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.webmanifest',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // WebSocket log stream — never intercept.
  if (url.pathname.endsWith('/logs/ws')) return;

  // API: network-first, cache fallback so the dashboard still renders offline.
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(request, copy));
          return resp;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Shell: cache-first.
  event.respondWith(
    caches.match(request).then((hit) => hit || fetch(request))
  );
});
