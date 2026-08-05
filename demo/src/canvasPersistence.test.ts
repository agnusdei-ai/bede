/**
 * Mirrors homeschool-tutor/src/utils/canvasPersistence.test.ts, with the
 * one case this copy needs that the app's does not: a demo stroke carries
 * `isEraser` rather than a tool name.
 *
 * The properties under test are the two that would cost a visitor real
 * work: a page that comes back WRONG (truncated, half-restored, or from
 * another session), and a page reported as kept when it was not.
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
    isEraser: false,
    ...overrides,
  }
}

function page(overrides: Partial<PersistedPage> = {}): PersistedPage {
  return { strokes: [stroke(3)], paperStyle: 'graph', paperColor: '#faf8f0', ...overrides }
}

/** A page whose serialized size lands in [min, max]. */
function pageOfSize(min: number, max: number): PersistedPage {
  let low = 1
  let high = max
  let best = page({ strokes: [stroke(1)] })
  while (low <= high) {
    const mid = Math.floor((low + high) / 2)
    const candidate = page({ strokes: [stroke(mid)] })
    const bytes = byteLength(serializePage(candidate))
    if (bytes < min) low = mid + 1
    else if (bytes > max) high = mid - 1
    else return candidate
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

describe('demo canvas page persistence', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('round-trips a page a visitor would actually have drawn', () => {
    savePage('ABC123', page({ strokes: [stroke(3), stroke(2, { isEraser: true })] }))
    const restored = loadPage('ABC123')
    expect(restored?.paperStyle).toBe('graph')
    expect(restored?.strokes).toHaveLength(2)
    expect(restored?.strokes[0].isEraser).toBe(false)
    expect(restored?.strokes[1].isEraser).toBe(true)
    expect(restored?.strokes[0].points).toHaveLength(3)
  })

  it('rounds coordinates without moving them anywhere a visitor could see', () => {
    savePage('ABC123', page())
    const point = loadPage('ABC123')!.strokes[0].points[0]
    expect(point.x).toBe(0.1)
    expect(point.pressure).toBe(0.51)
  })

  it('keeps each session code on its own page', () => {
    savePage('AAA', page({ paperStyle: 'graph' }))
    savePage('BBB', page({ paperStyle: 'staff' }))
    expect(loadPage('AAA')?.paperStyle).toBe('graph')
    expect(loadPage('BBB')?.paperStyle).toBe('staff')
  })

  it('prunes pages left by an earlier code so the budget bounds the tab', () => {
    savePage('AAA', page())
    savePage('BBB', page())
    pruneOtherPages('BBB')
    expect(loadPage('AAA')).toBeNull()
    expect(loadPage('BBB')).not.toBeNull()
  })

  it('leaves the rest of the demo storage alone', () => {
    window.sessionStorage.setItem('bede-demo-auth', 'token')
    window.sessionStorage.setItem('bede-demo-chat-ABC123', 'history')
    savePage('ABC123', page())
    pruneOtherPages('ZZZ')
    expect(window.sessionStorage.getItem('bede-demo-auth')).toBe('token')
    expect(window.sessionStorage.getItem('bede-demo-chat-ABC123')).toBe('history')
  })

  it('clears the page on request, which is what logout calls', () => {
    savePage('ABC123', page())
    clearPage('ABC123')
    expect(loadPage('ABC123')).toBeNull()
  })

  describe('the budget', () => {
    it('reports a page under the cap as kept, and not nearly full', () => {
      const result = savePage('ABC123', page())
      expect(result.ok).toBe(true)
      expect(result.ok && result.nearlyFull).toBe(false)
    })

    it('flags nearly full before anything is at risk', () => {
      const warnLine = CANVAS_BUDGET_BYTES * CANVAS_WARN_RATIO
      const big = pageOfSize(warnLine, CANVAS_BUDGET_BYTES)
      const result = savePage('ABC123', big)
      expect(result.ok).toBe(true)
      expect(result.ok && result.nearlyFull).toBe(true)
      expect(loadPage('ABC123')).not.toBeNull()
    })

    it('refuses a page over the cap, and says so rather than truncating it', () => {
      const result = savePage('ABC123', pageOverBudget())
      expect(result.ok).toBe(false)
      expect(!result.ok && result.reason).toBe('over-budget')
      expect(result.bytes).toBeGreaterThan(CANVAS_BUDGET_BYTES)
    })

    it('drops the stored copy when the cap is passed, so nothing partial comes back', () => {
      expect(savePage('ABC123', page()).ok).toBe(true)
      savePage('ABC123', pageOverBudget())
      expect(loadPage('ABC123')).toBeNull()
    })

    it('can refuse WITHOUT dropping the stored page, which is what the final flush needs', () => {
      // On the unmount flush there is no UI left to tell the visitor a
      // refusal happened, so dropping the page they safely stored minutes
      // ago would be a silent, unexplained loss. The last good copy stays.
      expect(savePage('ABC123', page()).ok).toBe(true)
      const before = loadPage('ABC123')
      const result = savePage('ABC123', pageOverBudget(), { dropStoredOnRefusal: false })
      expect(result.ok).toBe(false)
      expect(loadPage('ABC123')).toEqual(before)
    })

    it('reports a browser that refuses the write instead of pretending it worked', () => {
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('QuotaExceededError')
      })
      const result = savePage('ABC123', page())
      expect(result.ok).toBe(false)
      expect(!result.ok && result.reason).toBe('unavailable')
    })
  })

  describe('reading back what someone else may have written', () => {
    it('treats malformed JSON as a blank page', () => {
      window.sessionStorage.setItem(canvasStorageKey('ABC123'), '{not json')
      expect(loadPage('ABC123')).toBeNull()
    })

    const valid = { v: 2, strokes: [], paperStyle: 'graph', paperColor: '#fff' }
    it.each([
      ['a page from a future version', { ...valid, v: 99 }],
      ['a page from the old, pre-fixed-page-space shape (v1)', { ...valid, v: 1 }],
      ['a missing stroke list', { ...valid, strokes: undefined }],
      ['a stroke with no point array', { ...valid, strokes: [{ width: 1, color: '#000', isEraser: false }] }],
      ['a stroke with no eraser flag', { ...valid, strokes: [{ width: 1, color: '#000', pts: [] }] }],
      ['a point array truncated mid-point', { ...valid, strokes: [{ width: 1, color: '#000', isEraser: false, pts: [1, 2, 0.5, 3, 4] }] }],
      ['a non-finite coordinate', { ...valid, strokes: [{ width: 1, color: '#000', isEraser: false, pts: [null, 2, 0.5] }] }],
    ])('refuses %s rather than half-restoring it', (_what, payload) => {
      expect(parsePage(JSON.stringify(payload))).toBeNull()
    })

    it('accepts a well-formed page', () => {
      expect(parsePage(serializePage(page()))).not.toBeNull()
    })
  })
})
