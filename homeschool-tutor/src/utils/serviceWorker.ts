/**
 * Removes the service worker and caches an older version of Bede installed,
 * and nothing else on the origin.
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
/** The script the old version registered. Only a registration running this
 *  exact script on this origin is Bede's; anything else on the origin is left
 *  alone. */
export const BEDE_WORKER_PATH = '/sw.js'

/** Whether a registration is the worker Bede installed: any of its installing,
 *  waiting or active workers runs `/sw.js` from this page's own origin. */
export function isBedeWorker(reg: ServiceWorkerRegistration, origin: string = location.origin): boolean {
  return [reg.installing, reg.waiting, reg.active].some((w) => {
    if (!w?.scriptURL) return false
    try {
      const url = new URL(w.scriptURL)
      return url.origin === origin && url.pathname === BEDE_WORKER_PATH
    } catch {
      return false
    }
  })
}

export async function retireServiceWorker(
  nav: Navigator | undefined = typeof navigator === 'undefined' ? undefined : navigator,
  cacheStorage: CacheStorage | undefined = typeof caches === 'undefined' ? undefined : caches,
): Promise<number> {
  let removed = 0
  try {
    const regs = (await nav?.serviceWorker?.getRegistrations?.()) ?? []
    for (const reg of regs) {
      // Only Bede's own worker. Unregistering every worker on the origin
      // would remove one some other page or tool installed there.
      if (!isBedeWorker(reg)) continue
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
