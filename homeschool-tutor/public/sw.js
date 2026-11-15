// Bede no longer uses a service worker. This file exists only to remove the
// one an older version installed.
//
// The old worker cached the app's pages under one fixed name and served them
// cache-first, so a tablet could keep running an old release after
// `make update` until its cache happened to be cleared. On the family Docker
// deployment it never actually installed (nginx refused /manifest.json, which
// its install step fetched), so families lose nothing by its removal; the
// places it did run were development servers, test runs and any browser that
// reached a build some other way.
//
// A browser that still has the old worker checks this URL for an update,
// fetches this file, and installs it. On activation it deletes the caches the
// old worker created (every name it used began with "bede-") and unregisters
// itself. It deliberately has no fetch handler, so from
// the moment it takes over nothing is intercepted: every request goes to the
// network exactly as if no worker existed. It does not reload open pages, so
// a child mid-lesson is never interrupted; the next load is simply served by
// the server.
//
// See homeschool-tutor/src/utils/serviceWorker.ts (the page-side half) and
// docs/RELIABILITY.md.

self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('bede-')).map((k) => caches.delete(k))))
      .then(() => self.registration.unregister())
  )
})
