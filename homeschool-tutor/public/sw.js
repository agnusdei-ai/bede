const CACHE_NAME = 'bede-v3'
const STATIC_ASSETS = ['/', '/index.html', '/manifest.json']
const API_PREFIXES = ['/api/', '/auth/', '/tutor/', '/narration/', '/pod/', '/voice/', '/transcripts/', '/catalog/']

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  )
  self.skipWaiting()
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  )
  self.clients.claim()
})

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url)
  const isApi = API_PREFIXES.some((p) => url.pathname.startsWith(p))

  // API calls are never answered by the service worker. A failed fetch must
  // reach the app as a real network error: streamTutorChat retries a turn
  // that never got through (#794) and every other caller shows its own
  // message. Answering with a sample 200 here made a one-second network
  // drop lose the child's turn silently (#755, defect D-1).
  if (isApi) return
  // Only GETs are cached; anything else goes straight to the network.
  if (e.request.method !== 'GET') return
  // Cache-first for static assets
  e.respondWith(
    caches.match(e.request).then((cached) => cached || fetch(e.request).then((res) => {
      if (res.ok) {
        const clone = res.clone()
        caches.open(CACHE_NAME).then((c) => c.put(e.request, clone))
      }
      return res
    }))
  )
})
