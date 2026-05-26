/**
 * Financial OS — Service Worker
 * Cache-first strategy so the app works offline once installed.
 */

const CACHE = 'financial-os-v1';
const PRECACHE = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  // API calls — network first, fall back to cache
  if (req.url.includes('/api/')) {
    e.respondWith(
      fetch(req).then((r) => {
        const clone = r.clone();
        caches.open(CACHE).then((c) => c.put(req, clone));
        return r;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // Everything else — cache first
  e.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((r) => {
        if (r.ok && r.type === 'basic') {
          const clone = r.clone();
          caches.open(CACHE).then((c) => c.put(req, clone));
        }
        return r;
      });
    })
  );
});
