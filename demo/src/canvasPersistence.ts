/**
 * Keeps a demo visitor's drawing alive across a trip back to the chat, and
 * no longer. The demo's counterpart to `homeschool-tutor`'s module of the
 * same name (PR #402), mirrored rather than shared for the same reason
 * `holdGesture.ts` and `gradeTimer.ts` are: the demo is a separate Vite app
 * with its own bundle and its own, deliberately smaller, canvas.
 *
 * Three differences from the app's copy, all of them because this is the
 * demo:
 *
 * 1. **Keyed by the demo session code**, matching `bede-demo-chat-<code>`
 *    in `App.tsx`. A demo visitor has no student identity, and the code is
 *    the one thing that is stable for the length of a session.
 * 2. **A smaller stroke shape** - this canvas has pen and eraser, no
 *    pencil, so a stroke carries `isEraser` rather than a tool name. It is
 *    stored as written; nothing here tries to anticipate the app's shape.
 * 3. **Every key it writes is listed publicly.** `site/privacy/index.html`
 *    enumerates every piece of browser storage this domain uses, by name.
 *    Adding a key here without adding a row there would make that page
 *    wrong, which is the one thing it exists not to be.
 *
 * What does NOT differ is the part that matters: this is sessionStorage on
 * the visitor's own device. Nothing here is sent to the server, and the
 * demo's consent screen promise that the conversation is never stored is
 * untouched - a drawing in a browser tab is the same category as the chat
 * history `App.tsx` already keeps there so a reload does not lose it.
 */

// 2 MB, the same ceiling the app uses, for the same reasons: far more than
// a session produces (~100k stroke points in the flat encoding below), and
// small enough that it can never crowd a visitor's browser.
export const CANVAS_BUDGET_BYTES = 2 * 1024 * 1024

// Where "nearly full" is worth mentioning quietly, well before anything is
// at risk.
export const CANVAS_WARN_RATIO = 0.8

// Bumping this abandons every page stored under the old shape rather than
// migrating it - a half-restored drawing is worse than a fresh page.
export const CANVAS_STORAGE_VERSION = 1
const KEY_PREFIX = `bede-demo-canvas-v${CANVAS_STORAGE_VERSION}:`

// Coordinates are rounded before storage. A tenth of a CSS pixel is below
// what any screen resolves, and rounding roughly halves what a long stroke
// costs, which is drawing headroom inside the budget above.
const COORD_DECIMALS = 1
const PRESSURE_DECIMALS = 2

export interface PersistedPoint {
  x: number
  y: number
  pressure: number
}

export interface PersistedStroke {
  points: PersistedPoint[]
  width: number
  color: string
  isEraser: boolean
}

export interface PersistedPage {
  strokes: PersistedStroke[]
  paperStyle: string
  paperColor: string
  // The on-screen size, in CSS pixels, that these stroke coordinates are
  // expressed in. The app's canvas draws into a FIXED 816x1056 page space
  // (PR #402), so its copy of this module needs no such field; this one
  // still sizes its backing store to whatever the canvas element happens
  // to occupy, so a page restored into a differently-shaped window would
  // land in the wrong place without it. HandwritingCanvas rescales on
  // restore rather than discarding the page or replaying it crooked.
  space: { w: number; h: number }
}

export interface StoredPage extends PersistedPage {
  v: number
  savedAt: number
}

export type SaveResult =
  | { ok: true; bytes: number; nearlyFull: boolean }
  // 'over-budget': the drawing outgrew CANVAS_BUDGET_BYTES. 'unavailable':
  // the browser refused the write (quota, private mode, a locked-down
  // webview). Different causes, same consequence for the visitor - this
  // page will not be waiting when they come back - so both are reported
  // rather than swallowed, and (unless the caller opts out - see
  // SaveOptions) the stored copy is dropped either way, so what is kept
  // never disagrees with what the visitor was told.
  | { ok: false; reason: 'over-budget' | 'unavailable'; bytes: number }

export function canvasStorageKey(code: string): string {
  return `${KEY_PREFIX}${code}`
}

function storage(): Storage | null {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

/** UTF-8 byte length, so the budget means bytes rather than characters. */
export function byteLength(value: string): number {
  if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(value).length
  return value.length
}

function round(value: number, decimals: number): number {
  const f = 10 ** decimals
  return Math.round(value * f) / f
}

/**
 * Points are stored FLAT - [x, y, pressure, x, y, pressure, ...] - rather
 * than as a list of objects: at this volume the repeated keys cost more
 * than the coordinates themselves, and dropping them roughly halves what a
 * drawing costs. Every other key stays spelled out; there are only a
 * handful per stroke, so shortening them would buy nothing.
 */
export function serializePage(page: PersistedPage): string {
  const stored = {
    v: CANVAS_STORAGE_VERSION,
    savedAt: Date.now(),
    paperStyle: page.paperStyle,
    paperColor: page.paperColor,
    space: { w: round(page.space.w, COORD_DECIMALS), h: round(page.space.h, COORD_DECIMALS) },
    strokes: page.strokes.map((stroke) => {
      const pts: number[] = []
      for (const p of stroke.points) {
        pts.push(round(p.x, COORD_DECIMALS), round(p.y, COORD_DECIMALS), round(p.pressure, PRESSURE_DECIMALS))
      }
      return { width: round(stroke.width, COORD_DECIMALS), color: stroke.color, isEraser: stroke.isEraser, pts }
    }),
  }
  return JSON.stringify(stored)
}

/**
 * Validates rather than trusts. sessionStorage is editable in devtools and
 * survives a reload, so a malformed or half-written page must produce a
 * clean blank sheet, never a crash inside the draw loop.
 */
export function parsePage(raw: string | null): StoredPage | null {
  if (!raw) return null
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    return null
  }
  if (typeof data !== 'object' || data === null) return null
  const page = data as Record<string, unknown>
  if (page.v !== CANVAS_STORAGE_VERSION) return null
  if (typeof page.paperStyle !== 'string' || typeof page.paperColor !== 'string') return null
  if (!Array.isArray(page.strokes)) return null
  const space = page.space as { w?: unknown; h?: unknown } | undefined
  if (typeof space !== 'object' || space === null) return null
  const { w, h } = space
  // A zero or negative space would make the restore rescale divide by zero
  // and put every stroke at NaN, i.e. an invisible page with no explanation.
  if (typeof w !== 'number' || !Number.isFinite(w) || w <= 0) return null
  if (typeof h !== 'number' || !Number.isFinite(h) || h <= 0) return null

  const strokes: PersistedStroke[] = []
  for (const candidate of page.strokes) {
    if (typeof candidate !== 'object' || candidate === null) return null
    const stroke = candidate as Record<string, unknown>
    if (typeof stroke.width !== 'number' || !Number.isFinite(stroke.width)) return null
    if (typeof stroke.color !== 'string') return null
    if (typeof stroke.isEraser !== 'boolean') return null
    if (!Array.isArray(stroke.pts)) return null
    if (stroke.pts.length % 3 !== 0) return null
    const points: PersistedPoint[] = []
    for (let i = 0; i < stroke.pts.length; i += 3) {
      const [x, y, pressure] = [stroke.pts[i], stroke.pts[i + 1], stroke.pts[i + 2]]
      if (typeof x !== 'number' || !Number.isFinite(x)) return null
      if (typeof y !== 'number' || !Number.isFinite(y)) return null
      if (typeof pressure !== 'number' || !Number.isFinite(pressure)) return null
      points.push({ x, y, pressure })
    }
    strokes.push({ points, width: stroke.width, color: stroke.color, isEraser: stroke.isEraser })
  }

  return {
    v: CANVAS_STORAGE_VERSION,
    savedAt: typeof page.savedAt === 'number' ? page.savedAt : 0,
    paperStyle: page.paperStyle,
    paperColor: page.paperColor,
    space: { w, h },
    strokes,
  }
}

export function loadPage(code: string): StoredPage | null {
  const store = storage()
  if (!store) return null
  try {
    return parsePage(store.getItem(canvasStorageKey(code)))
  } catch {
    return null
  }
}

export function clearPage(code: string): void {
  const store = storage()
  if (!store) return
  try {
    store.removeItem(canvasStorageKey(code))
  } catch {
    /* a page we cannot remove is one we also cannot read */
  }
}

/**
 * Drops any page left behind by an earlier demo code in this same tab, so
 * the budget bounds the session rather than accumulating one page per code
 * a visitor happens to go through. `App.tsx`'s own logout path clears the
 * current code's page directly; this covers the rest.
 */
export function pruneOtherPages(code: string): void {
  const store = storage()
  if (!store) return
  const keep = canvasStorageKey(code)
  try {
    const doomed: string[] = []
    for (let i = 0; i < store.length; i++) {
      const key = store.key(i)
      if (key && key.startsWith(KEY_PREFIX) && key !== keep) doomed.push(key)
    }
    for (const key of doomed) store.removeItem(key)
  } catch {
    /* best effort */
  }
}

export interface SaveOptions {
  /**
   * Whether a refusal should also drop whatever is already stored.
   *
   * True (the default) is what an ordinary save wants: the visitor is about
   * to be TOLD this page is not being kept, and an older, smaller version
   * reappearing later would make that message a lie in the confusing
   * direction.
   *
   * The unmount flush passes false, because on that path there is no
   * longer any UI to tell them with - the component is going away. Dropping
   * the stored page there would silently destroy work that was safely
   * stored minutes ago, with nothing on screen to explain it. Keeping the
   * last good copy is the lesser of the two, and the only one that does not
   * punish someone for pressing Done at the wrong moment.
   */
  dropStoredOnRefusal?: boolean
}

export function savePage(code: string, page: PersistedPage, options: SaveOptions = {}): SaveResult {
  const { dropStoredOnRefusal = true } = options
  const json = serializePage(page)
  const bytes = byteLength(json)

  if (bytes > CANVAS_BUDGET_BYTES) {
    if (dropStoredOnRefusal) clearPage(code)
    return { ok: false, reason: 'over-budget', bytes }
  }

  const store = storage()
  if (!store) return { ok: false, reason: 'unavailable', bytes }
  try {
    store.setItem(canvasStorageKey(code), json)
  } catch {
    if (dropStoredOnRefusal) clearPage(code)
    return { ok: false, reason: 'unavailable', bytes }
  }
  return { ok: true, bytes, nearlyFull: bytes >= CANVAS_BUDGET_BYTES * CANVAS_WARN_RATIO }
}
