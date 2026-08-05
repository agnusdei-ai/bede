/**
 * The properties under test are the two that would cost a child real work:
 * a page that comes back WRONG (silently truncated, half-restored, or
 * belonging to a different student), and a page that is reported as kept
 * when it was not. Everything else here is bookkeeping.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  CANVAS_BUDGET_BYTES,
  CANVAS_WARN_RATIO,
  byteLength,
  canvasStorageKey,
  clearPage,
  loadPage,
  parsePage,
  pruneOtherPages,
  savePage,
  serializePage,
  type PersistedPage,
  type PersistedStroke,
} from './canvasPersistence'

function stroke(points: number, overrides: Partial<PersistedStroke> = {}): PersistedStroke {
  return {
    points: Array.from({ length: points }, (_, i) => ({ x: i + 0.123456, y: i * 2 + 0.987654, pressure: 0.5123 })),
    width: 3,
    color: '#1b3a6b',
    tool: 'pen',
    ...overrides,
  }
}

function page(overrides: Partial<PersistedPage> = {}): PersistedPage {
  return { strokes: [stroke(3)], paperStyle: 'graph', paperColor: '#faf8f0', ...overrides }
}

/**
 * A page whose serialized size lands in [min, max]. Binary search rather
 * than a bytes-per-point constant, so a future change to the encoding
 * retunes these cases instead of silently invalidating them.
 */
function pageOfSize(min: number, max: number): PersistedPage {
  let low = 1
  let high = max // one point is always well under a byte-per-point of 1
  let best = page({ strokes: [stroke(1)] })
  while (low <= high) {
    const mid = Math.floor((low + high) / 2)
    const candidate = page({ strokes: [stroke(mid)] })
    const bytes = byteLength(serializePage(candidate))
    if (bytes < min) {
      low = mid + 1
    } else if (bytes > max) {
      high = mid - 1
    } else {
      return candidate
    }
    best = candidate
  }
  return best
}

/** The smallest power-of-two page this helper can find that busts the cap. */
function pageOverBudget(): PersistedPage {
  let points = 1024
  for (;;) {
    const candidate = page({ strokes: [stroke(points)] })
    if (byteLength(serializePage(candidate)) > CANVAS_BUDGET_BYTES) return candidate
    points *= 2
  }
}

describe('canvas page persistence', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('round-trips a page a child would actually have drawn', () => {
    savePage('Emma', page())
    const restored = loadPage('Emma')
    expect(restored?.paperStyle).toBe('graph')
    expect(restored?.paperColor).toBe('#faf8f0')
    expect(restored?.strokes).toHaveLength(1)
    expect(restored?.strokes[0].points).toHaveLength(3)
    expect(restored?.strokes[0].tool).toBe('pen')
  })

  it('rounds coordinates without moving them anywhere a child could see', () => {
    savePage('Emma', page())
    const point = loadPage('Emma')!.strokes[0].points[0]
    // A tenth of a canvas unit at 96 units/inch is under three thousandths
    // of an inch: below what a screen or a printer resolves.
    expect(Math.abs(point.x - 0.123456)).toBeLessThan(0.05)
    expect(point.x).toBe(0.1)
    expect(point.pressure).toBe(0.51)
  })

  it('keeps each student on their own page', () => {
    savePage('Emma', page({ paperStyle: 'graph' }))
    savePage('Wren', page({ paperStyle: 'staff' }))
    expect(loadPage('Emma')?.paperStyle).toBe('graph')
    expect(loadPage('Wren')?.paperStyle).toBe('staff')
  })

  it('prunes every other student page so the budget bounds the whole session', () => {
    savePage('Emma', page())
    savePage('Wren', page())
    pruneOtherPages('Wren')
    expect(loadPage('Emma')).toBeNull()
    expect(loadPage('Wren')).not.toBeNull()
  })

  it('leaves storage this module does not own alone', () => {
    window.sessionStorage.setItem('bede-session', 'auth-state')
    savePage('Emma', page())
    pruneOtherPages('Wren')
    expect(window.sessionStorage.getItem('bede-session')).toBe('auth-state')
  })

  it('clears the page on request', () => {
    savePage('Emma', page())
    clearPage('Emma')
    expect(loadPage('Emma')).toBeNull()
  })

  describe('the budget', () => {
    it('reports a page under the cap as kept, and not nearly full', () => {
      const result = savePage('Emma', page())
      expect(result.ok).toBe(true)
      expect(result.ok && result.nearlyFull).toBe(false)
    })

    it('flags nearly full before anything is at risk', () => {
      // Sized just past the warning line but still comfortably under the cap.
      const warnLine = CANVAS_BUDGET_BYTES * CANVAS_WARN_RATIO
      const big = pageOfSize(warnLine, CANVAS_BUDGET_BYTES)
      const bytes = byteLength(serializePage(big))
      expect(bytes).toBeGreaterThanOrEqual(warnLine)
      expect(bytes).toBeLessThanOrEqual(CANVAS_BUDGET_BYTES)

      const result = savePage('Emma', big)
      expect(result.ok).toBe(true)
      expect(result.ok && result.nearlyFull).toBe(true)
      expect(loadPage('Emma')).not.toBeNull()
    })

    it('refuses a page over the cap, and says so rather than truncating it', () => {
      const result = savePage('Emma', pageOverBudget())
      expect(result.ok).toBe(false)
      expect(!result.ok && result.reason).toBe('over-budget')
      expect(result.bytes).toBeGreaterThan(CANVAS_BUDGET_BYTES)
    })

    it('drops the stored copy when the cap is passed, so nothing partial comes back', () => {
      // The child had a page kept, then drew past the cap. They are about to
      // be told this page will not be waiting for them; a smaller older
      // version reappearing later would contradict that.
      expect(savePage('Emma', page()).ok).toBe(true)
      savePage('Emma', pageOverBudget())
      expect(loadPage('Emma')).toBeNull()
    })

    it('can refuse WITHOUT dropping the stored page, which is what the final flush needs', () => {
      // On the unmount flush there is no UI left to tell the child a
      // refusal happened, so dropping the page they safely stored minutes
      // ago would be a silent, unexplained loss. The last good copy stays.
      expect(savePage('Emma', page()).ok).toBe(true)
      const before = loadPage('Emma')
      const result = savePage('Emma', pageOverBudget(), { dropStoredOnRefusal: false })
      expect(result.ok).toBe(false)
      expect(loadPage('Emma')).toEqual(before)
    })

    it('reports a browser that refuses the write instead of pretending it worked', () => {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('QuotaExceededError')
      })
      const result = savePage('Emma', page())
      expect(result.ok).toBe(false)
      expect(!result.ok && result.reason).toBe('unavailable')
    })
  })

  describe('reading back what someone else may have written', () => {
    it('treats malformed JSON as a blank page', () => {
      window.sessionStorage.setItem(canvasStorageKey('Emma'), '{not json')
      expect(loadPage('Emma')).toBeNull()
    })

    it.each([
      ['a page from a future version', { v: 99, strokes: [], paperStyle: 'graph', paperColor: '#fff' }],
      ['a missing stroke list', { v: 1, paperStyle: 'graph', paperColor: '#fff' }],
      ['a stroke with no point array', { v: 1, strokes: [{ width: 1, color: '#000', tool: 'pen' }], paperStyle: 'graph', paperColor: '#fff' }],
      ['an unknown tool', { v: 1, strokes: [{ width: 1, color: '#000', tool: 'airbrush', pts: [] }], paperStyle: 'graph', paperColor: '#fff' }],
      ['a point array truncated mid-point', { v: 1, strokes: [{ width: 1, color: '#000', tool: 'pen', pts: [1, 2, 0.5, 3, 4] }], paperStyle: 'graph', paperColor: '#fff' }],
      ['a non-finite coordinate', { v: 1, strokes: [{ width: 1, color: '#000', tool: 'pen', pts: [null, 2, 0.5] }], paperStyle: 'graph', paperColor: '#fff' }],
    ])('refuses %s rather than half-restoring it', (_what, payload) => {
      expect(parsePage(JSON.stringify(payload))).toBeNull()
    })

    it('accepts a well-formed page', () => {
      expect(parsePage(serializePage(page()))).not.toBeNull()
    })
  })
})
