// Service Worker for AgentOS PWA
// Cache version auto-generated from build timestamp
const CACHE_NAME = 'agentos-' + Date.now();
const STATIC_ASSETS = ['/', '/index.html', '/manifest.json'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Don't cache API calls
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  // Stale-while-revalidate: return cached first, then update cache from network
  event.respondWith(
    caches.open(CACHE_NAME).then((cache) =>
      cache.match(event.request).then((cached) => {
        const fetchPromise = fetch(event.request)
          .then((response) => {
            if (response.ok && response.type === 'basic') {
              cache.put(event.request, response.clone());
            }
            return response;
          })
          .catch(() => cached || new Response('Offline', { status: 503 }));

        return cached || fetchPromise;
      })
    )
  );
});

// Cache message history for offline access
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'CACHE_MESSAGES') {
    caches.open(CACHE_NAME).then((cache) => {
      const key = '/api/v1/chat/history?session_id=' + event.data.session_id;
      cache.add(key);
    });
  }
});
