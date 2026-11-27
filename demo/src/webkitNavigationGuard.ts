/**
 * Keeps WebKit 26.0 from crashing the lesson page on a second reload (#861).
 *
 * WebKit 26.0 (Safari and iOS 26.0, and Playwright 1.56.0's WebKit) does not
 * record `history.pushState` in the Navigation API: after the app's router
 * moves from `/` to `/session`, `navigation.currentEntry` still says `/`. One
 * reload then leaves `currentEntry` empty, and the next reload, or any
 * navigation at all, crashes the page's process in
 * `Navigation::initializeForNewWindow`. WebKit tracks this as bug 300402; it
 * does not happen on WebKit 26.6.
 *
 * The browser journeys hit exactly that: a child's lesson page reloads once to
 * pick up approved practice and again after the API restarts, and the second
 * reload crashed the tab. A family on an affected iPad would see the same
 * thing after reloading twice.
 *
 * A page cannot refuse a reload, so the guard removes the state that makes the
 * reload fatal. The minimal reproduction in
 * `scripts/qualification/browser_journeys/webkit_nav_repro.cjs` showed that a
 * real same-URL navigation straight after the push gives WebKit an honest
 * entry, after which any number of reloads is safe (variant H, 0 of 3
 * crashes, against 3 of 3 without it). Once a reload has happened with the
 * broken entry it is too late (variant G still crashes), so the check runs on
 * every `pushState`, before anything can reload.
 *
 * The guard acts only when the engine itself reports the mismatch, so Chrome,
 * Firefox and fixed WebKit builds never reload. On an affected engine each
 * in-app route change costs one page load; what a child has typed survives it
 * (utils/chatDraft.ts) and sign-in lives in sessionStorage. A marker stops it
 * relocating to the same address twice within `RELOCATE_GUARD_MS`, so an
 * engine that never reports a match cannot loop.
 */

export const RELOCATE_GUARD_MS = 10_000
export const RELOCATE_MARKER_KEY = 'bede-webkit-nav-relocate'

interface NavigationLike {
  currentEntry?: { url?: string | null } | null
}

/**
 * True when the Navigation API exists and its current entry does not name the
 * address the document is actually at. A missing API, an entry that agrees,
 * or an empty entry (see below) is not acted on.
 */
export function navigationEntryIsStale(win: Window = window): boolean {
  const nav = (win as Window & { navigation?: NavigationLike }).navigation
  if (!nav) return false
  // An empty entry means a reload already happened with the broken record.
  // Navigating from there crashes too (repro variant G), so it is left alone.
  const entryUrl = nav.currentEntry?.url
  if (!entryUrl) return false
  try {
    return new URL(entryUrl).href !== new URL(win.location.href).href
  } catch {
    return false
  }
}

function recentlyRelocated(win: Window, href: string, now: number): boolean {
  try {
    const raw = win.sessionStorage.getItem(RELOCATE_MARKER_KEY)
    if (!raw) return false
    const mark = JSON.parse(raw) as { href?: unknown; at?: unknown }
    return mark.href === href && typeof mark.at === 'number' && now - mark.at >= 0 && now - mark.at < RELOCATE_GUARD_MS
  } catch {
    return false
  }
}

function markRelocated(win: Window, href: string, now: number) {
  try {
    win.sessionStorage.setItem(RELOCATE_MARKER_KEY, JSON.stringify({ href, at: now }))
  } catch {
    // Storage blocked: the guard still runs, just without its loop stop.
  }
}

/**
 * Wraps `history.pushState` so that, on an engine that failed to record the
 * push, the page makes a real navigation to the same address straight away.
 * Returns a function that removes the wrapper (for tests).
 */
export function installWebkitNavigationGuard(
  win: Window = window,
  log: (line: string) => void = () => {},
): () => void {
  const history = win.history
  const original = history.pushState
  if (!(win as Window & { navigation?: unknown }).navigation || typeof original !== 'function') return () => {}

  const wrapped: History['pushState'] = function (this: History, ...args) {
    original.apply(this, args)
    if (!navigationEntryIsStale(win)) return
    const href = win.location.href
    const now = Date.now()
    if (recentlyRelocated(win, href, now)) return
    markRelocated(win, href, now)
    log('WEBKIT NAVIGATION ENTRY STALE after pushState; relocating to keep reloads safe (#861)')
    win.location.replace(href)
  }
  history.pushState = wrapped
  return () => {
    if (history.pushState === wrapped) history.pushState = original
  }
}
