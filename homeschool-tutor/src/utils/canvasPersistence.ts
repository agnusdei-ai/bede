/**
 * Keeps a child's drawing alive across a trip back to Bede, without keeping
 * it a moment longer than the session it belongs to.
 *
 * Before this, HandwritingCanvas mounted only while `showCanvas` was true
 * (SocraticChat.tsx), so every stroke lived in a ref inside a component that
 * unmounted the instant the child pressed Cancel or Done. Switching back to
 * the chat to read Bede's next question and returning to the page threw the
 * work away with no warning - the same class of silent loss this codebase
 * already refuses elsewhere (see utils/logoutNotice.ts on automated logouts
 * saying nothing).
 *
 * Three deliberate properties, in order of how much they matter:
 *
 * 1. **sessionStorage, never the server.** A drawing is the child's own
 *    work-in-progress, not an assessment of them - nothing here is a claim
 *    about the child, so nothing here belongs in the database (the same
 *    distinction CLAUDE.md draws between MasteryProfile and
 *    SkillActivityLog). sessionStorage is per-tab and dies with the tab, so
 *    the page survives a reload and a hundred switches to Bede, and survives
 *    nothing else. No new endpoint, no encrypted column, no retention
 *    question for a parent to answer. A drawing the child deliberately SENDS
 *    to Bede is a separate thing and still travels as it always did.
 *
 * 2. **A stated budget, enforced rather than hoped for.** BUDGET_BYTES caps
 *    what one session may hold. Reaching it is not silently absorbed: the
 *    page stops being kept, the stored copy is dropped, and the caller is
 *    told so it can tell the child while the drawing is still on screen and
 *    still saveable to their device. A cap that quietly truncates would be
 *    the "blank must not look like a low mark" failure in another costume -
 *    a child would find half a drawing and no explanation.
 *
 * 3. **One page at a time, per identity.** pruneOtherPages() drops any page
 *    stored under a different student on the same device, so the budget is a
 *    real ceiling on the tab rather than a per-student allowance that adds
 *    up. Starting a fresh page clears the stored copy outright.
 */

// 2 MB. Comfortably inside every browser's ~5 MB per-origin sessionStorage
// allowance (which this app otherwise barely touches - sessionStore.ts
// persists four small auth fields), and far more drawing than a single
// session produces: a stroke point costs roughly 18 bytes in the flat
// encoding below, so this holds on the order of 100,000 of them, which is
// twenty-odd minutes of unbroken pen-down motion at a tablet's event rate.
export const CANVAS_BUDGET_BYTES = 2 * 1024 * 1024

// Where "this page is nearly full" is worth mentioning quietly, well before
// the point where anything is at risk.
export const CANVAS_WARN_RATIO = 0.8

// Bumping this abandons every page stored under the old shape rather than
// trying to migrate it - a half-restored drawing is worse than a fresh page.
export const CANVAS_STORAGE_VERSION = 1
const KEY_PREFIX = `bede-canvas-v${CANVAS_STORAGE_VERSION}:`

// Coordinates are rounded before storage. The canvas is 816x1056 physical
// units (HandwritingCanvas.tsx's CANVAS_WIDTH/HEIGHT), so a tenth of a unit
// is far below what a screen or a printer can resolve, and rounding roughly
// halves what a long stroke costs - i.e. it buys real drawing headroom
// inside the budget above, at no visible cost.
const COORD_DECIMALS = 1
const PRESSURE_DECIMALS = 2

export type PersistedTool = 'pen' | 'pencil' | 'eraser'
const TOOLS: readonly string[] = ['pen', 'pencil', 'eraser']

export interface PersistedPoint {
  x: number
  y: number
  pressure: number
}

export interface PersistedStroke {
  points: PersistedPoint[]
  width: number
  color: string
  tool: PersistedTool
}

export interface PersistedPage {
  strokes: PersistedStroke[]
  paperStyle: string
  paperColor: string
}

export interface StoredPage extends PersistedPage {
  v: number
  savedAt: number
}

export type SaveResult =
  | { ok: true; bytes: number; nearlyFull: boolean }
  // 'over-budget': the drawing itself outgrew CANVAS_BUDGET_BYTES.
  // 'unavailable': the browser refused the write (quota, private mode, a
  // locked-down webview). Different causes, same consequence for the child -
  // this page will not be waiting when they come back - so both are reported
  // rather than swallowed, and the stored copy is dropped either way so what
  // is kept never disagrees with what they were told.
  | { ok: false; reason: 'over-budget' | 'unavailable'; bytes: number }

export function canvasStorageKey(identity: string): string {
  return `${KEY_PREFIX}${identity}`
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
 * than as a list of {x, y, pressure} objects. The keys are the expensive
 * part of a point at this volume (they cost more than the coordinates
 * themselves), and dropping them roughly halves what a drawing costs, which
 * is drawing headroom for the child inside the same stated budget. Every
 * other key here stays spelled out: there are only a handful per stroke, so
 * shortening them would buy nothing and cost readability.
 */
export function serializePage(page: PersistedPage): string {
  const stored = {
    v: CANVAS_STORAGE_VERSION,
    savedAt: Date.now(),
    paperStyle: page.paperStyle,
    paperColor: page.paperColor,
    strokes: page.strokes.map((stroke) => {
      const pts: number[] = []
      for (const p of stroke.points) {
        pts.push(round(p.x, COORD_DECIMALS), round(p.y, COORD_DECIMALS), round(p.pressure, PRESSURE_DECIMALS))
      }
      return { width: round(stroke.width, COORD_DECIMALS), color: stroke.color, tool: stroke.tool, pts }
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

  const strokes: PersistedStroke[] = []
  for (const candidate of page.strokes) {
    if (typeof candidate !== 'object' || candidate === null) return null
    const stroke = candidate as Record<string, unknown>
    if (typeof stroke.width !== 'number' || !Number.isFinite(stroke.width)) return null
    if (typeof stroke.color !== 'string') return null
    if (typeof stroke.tool !== 'string' || !TOOLS.includes(stroke.tool)) return null
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
    strokes.push({
      points,
      width: stroke.width,
      color: stroke.color,
      tool: stroke.tool as PersistedTool,
    })
  }

  return {
    v: CANVAS_STORAGE_VERSION,
    savedAt: typeof page.savedAt === 'number' ? page.savedAt : 0,
    paperStyle: page.paperStyle,
    paperColor: page.paperColor,
    strokes,
  }
}

export function loadPage(identity: string): StoredPage | null {
  const store = storage()
  if (!store) return null
  try {
    return parsePage(store.getItem(canvasStorageKey(identity)))
  } catch {
    return null
  }
}

export function clearPage(identity: string): void {
  const store = storage()
  if (!store) return
  try {
    store.removeItem(canvasStorageKey(identity))
  } catch {
    /* nothing to do - a page we cannot remove is one we also cannot read */
  }
}

/**
 * Drops any page belonging to a different student on this device, so
 * CANVAS_BUDGET_BYTES is a ceiling on the whole session rather than a
 * per-student allowance that accumulates behind the parent's back.
 */
export function pruneOtherPages(identity: string): void {
  const store = storage()
  if (!store) return
  const keep = canvasStorageKey(identity)
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

export function savePage(identity: string, page: PersistedPage): SaveResult {
  const json = serializePage(page)
  const bytes = byteLength(json)

  if (bytes > CANVAS_BUDGET_BYTES) {
    // Deliberately drop the stored copy rather than leaving an older,
    // smaller snapshot behind: the child is about to be told this page is
    // not being kept, and a partial page reappearing later would make that
    // message a lie in the confusing direction.
    clearPage(identity)
    return { ok: false, reason: 'over-budget', bytes }
  }

  const store = storage()
  if (!store) return { ok: false, reason: 'unavailable', bytes }
  try {
    store.setItem(canvasStorageKey(identity), json)
  } catch {
    clearPage(identity)
    return { ok: false, reason: 'unavailable', bytes }
  }
  return { ok: true, bytes, nearlyFull: bytes >= CANVAS_BUDGET_BYTES * CANVAS_WARN_RATIO }
}
