/**
 * Removes any service worker and cache an older version of Bede installed.
 *
 * Bede used to register `/sw.js`, which cached the app's pages under one
 * fixed name and served them cache-first, so a tablet could keep running an
 * old release after an update. It never installed on the family Docker
 * deployment at all (nginx refused /manifest.json, which its install step
 * fetched), so the worker bought families nothing and could only ever cause a
 * stale app where it did install. It is retired: the app registers nothing,
 * and this clears what an earlier version left behind. `public/sw.js` is the
 * other half, for a browser that checks the old worker for an update before
 * this page ever runs.
 *
 * Best-effort and silent. Nothing here can fail a page load, and nothing is
 * reloaded, so a lesson already open is never interrupted.
 */
export async function retireServiceWorker(
  nav: Navigator | undefined = typeof navigator === 'undefined' ? undefined : navigator,
  cacheStorage: CacheStorage | undefined = typeof caches === 'undefined' ? undefined : caches,
): Promise<number> {
  let removed = 0
  try {
    const regs = (await nav?.serviceWorker?.getRegistrations?.()) ?? []
    for (const reg of regs) {
      if (await reg.unregister().catch(() => false)) removed++
    }
  } catch {
    // An origin where service workers are unavailable has nothing to retire.
  }
  try {
    const keys = (await cacheStorage?.keys()) ?? []
    // Only caches the old worker created. Every name it ever used began with
    // "bede-" (bede-v2, then bede-v3).
    await Promise.all(keys.filter((k) => k.startsWith('bede-')).map((k) => cacheStorage!.delete(k)))
  } catch {
    // Cache Storage can be unavailable (a private window, a locked-down
    // webview). There is then nothing to clear.
  }
  return removed
}
