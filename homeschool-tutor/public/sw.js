const CACHE_NAME = 'bede-v1'
const STATIC_ASSETS = ['/', '/index.html', '/agnus-dei.png', '/manifest.json']
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

  if (isApi) {
    // Network-first for API calls
    e.respondWith(
      fetch(e.request).catch(() =>
        new Response(JSON.stringify({ error: 'offline' }), {
          headers: { 'Content-Type': 'application/json' },
        })
      )
    )
  } else {
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
  }
})
