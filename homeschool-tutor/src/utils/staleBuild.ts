/**
 * Recovers a tablet that is still running the previous release.
 *
 * The app loads most of its pages on demand (App.tsx's `lazy()` routes), each
 * from a file whose name carries a hash of its contents. After `make update`
 * those files are replaced, so a tab opened before the update asks for a file
 * that no longer exists the next time it opens a page, and the import fails.
 * That used to reach the child as the error screen ("Something went wrong")
 * with a button back to sign-in, for a problem a single reload fixes.
 *
 * So a failed page load is told apart from a real rendering bug, and only the
 * first is recovered: the page reloads once, which fetches the new release.
 * A marker in sessionStorage stops it reloading again within
 * `RELOAD_GUARD_MS`, so a server that is genuinely missing a file shows the
 * error screen instead of reloading forever. A render error is never reloaded:
 * reloading would hide a real bug and could loop.
 */

export const RELOAD_GUARD_MS = 60_000
export const RELOAD_MARKER_KEY = 'bede-stale-build-reload'

// What each engine says when a dynamic import's file cannot be fetched.
const CHUNK_LOAD_PATTERNS = [
  /Failed to fetch dynamically imported module/i, // Chromium
  /error loading dynamically imported module/i, // Firefox
  /Importing a module script failed/i, // WebKit
  /Unable to preload CSS/i, // Vite's own CSS preload
  /ChunkLoadError|Loading chunk [\w-]+ failed/i,
]

export function isChunkLoadError(err: unknown): boolean {
  const e = err as { name?: unknown; message?: unknown } | null
  const text = `${typeof e?.name === 'string' ? e.name : ''} ${typeof e?.message === 'string' ? e.message : String(err)}`
  return CHUNK_LOAD_PATTERNS.some((re) => re.test(text))
}

function storage(): Storage | undefined {
  try {
    return typeof sessionStorage === 'undefined' ? undefined : sessionStorage
  } catch {
    return undefined
  }
}

/**
 * Reloads the page once to pick up a new release. Returns true when it
 * reloaded, false when it already did so recently (or cannot record that it
 * did, in which case reloading could loop).
 */
export function reloadOnceForNewRelease(
  reload: () => void = () => window.location.reload(),
  now: number = Date.now(),
  store: Storage | null | undefined = storage(),
): boolean {
  if (!store) return false
  try {
    const last = Number(store.getItem(RELOAD_MARKER_KEY))
    if (Number.isFinite(last) && last > 0 && now - last < RELOAD_GUARD_MS) return false
    store.setItem(RELOAD_MARKER_KEY, String(now))
  } catch {
    return false
  }
  reload()
  return true
}
