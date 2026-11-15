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
 * first is recovered, and only once the server has confirmed a new release
 * (`releaseChanged`): the page then reloads once, which fetches it. A failed
 * load is not proof of a new release on its own. A browser cancels the
 * page files it was still loading when the page navigates away (signing out,
 * following a link), and Vite reports each one as a preload failure.
 * Reloading on that alone hijacked the navigation already underway: the
 * browser journeys caught it on WebKit, where a parent opening Parent Setup
 * was sent back to a reload of the page they were leaving.
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

/** The entry script a document names: `/assets/index-<hash>.js` in a build. */
export function entryScriptOf(doc: Document): string | null {
  const el = doc.querySelector('script[type="module"][src]')
  const src = el?.getAttribute('src')
  return src ? src : null
}

/**
 * Whether the server now serves a different release from the one this page
 * is running. Fetches `/` uncached and compares the entry script its
 * `index.html` names with this document's own. False whenever it cannot tell
 * (the fetch failed or was cancelled by a navigation, either document has no
 * entry script), since a reload is only worth making when it is known to help.
 * Works on every engine, including WebKit, whose import error carries no file
 * name to check. In development both name `/src/main.tsx`, so it is always
 * false there.
 */
export async function releaseChanged(
  fetchImpl: typeof fetch = (input, init) => fetch(input, init),
  doc: Document = document,
): Promise<boolean> {
  const current = entryScriptOf(doc)
  if (!current) return false
  try {
    const res = await fetchImpl('/', { cache: 'no-store', credentials: 'same-origin' })
    if (!res.ok) return false
    const served = entryScriptOf(new DOMParser().parseFromString(await res.text(), 'text/html'))
    return served !== null && served !== current
  } catch {
    return false
  }
}

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
