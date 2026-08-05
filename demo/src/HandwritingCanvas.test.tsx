/**
 * canvasPersistence.test.ts proves the store keeps and refuses the right
 * things. This covers what it cannot: that the component READS it at mount
 * and WRITES it on the way out, and the demo-specific part - that a page
 * drawn in one window comes back correctly in a differently shaped one,
 * since this canvas's coordinates are on-screen pixels rather than the
 * app's fixed page space.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from './i18n'
import HandwritingCanvas from './HandwritingCanvas'
import { canvasStorageKey, loadPage, savePage } from './canvasPersistence'

// jsdom has no 2D context and lays nothing out. Everything this component
// asks of a context is a draw call nothing here inspects, and the size is
// what the restore rescale reads, so both are stubbed.
const SPACE = { w: 800, h: 600 }

function stubCanvas(space = SPACE) {
  const ctx = new Proxy(
    {},
    {
      get: (target: Record<string, unknown>, prop: string) => {
        if (!(prop in target)) target[prop] = vi.fn()
        return target[prop]
      },
      set: (target: Record<string, unknown>, prop: string, value: unknown) => {
        target[prop] = value
        return true
      },
    },
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx as unknown as CanvasRenderingContext2D)
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/png;base64,stub')
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(space.w)
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(space.h)
}

function storedPage(space = SPACE) {
  return {
    strokes: [
      {
        points: [
          { x: 100, y: 200, pressure: 0.5 },
          { x: 300, y: 400, pressure: 0.5 },
        ],
        width: 4,
        color: '#1b3a6b',
        isEraser: false,
      },
    ],
    paperStyle: 'staff',
    paperColor: '#2e3a44',
    space,
  }
}

beforeEach(() => {
  window.sessionStorage.clear()
  stubCanvas()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  i18n.changeLanguage('en')
})

describe('demo HandwritingCanvas page persistence', () => {
  it('comes back to the page the visitor left, paper and all', () => {
    savePage('ABC123', storedPage())
    render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" />)

    // An enabled Undo is this component saying "I have their strokes".
    expect(screen.getByRole('button', { name: /undo/i }).hasAttribute('disabled')).toBe(false)
    expect(screen.getByRole('button', { name: 'Staff' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('keeps the page when the visitor leaves for the chat', () => {
    savePage('ABC123', storedPage())
    const { unmount } = render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" />)

    unmount()
    const kept = loadPage('ABC123')
    expect(kept?.strokes).toHaveLength(1)
    expect(kept?.paperStyle).toBe('staff')
    // Recorded from the canvas as it is now, not from whatever the page was
    // drawn at, so the next restore rescales from the right starting point.
    expect(kept?.space).toEqual(SPACE)
  })

  it('writes nothing at all for a page that was never drawn on', () => {
    // "New page clears the stored drawing" is a promise made publicly, on
    // site/privacy/index.html. An empty page written on the way out would
    // put the key straight back and make that wording untrue.
    const { unmount } = render(
      <HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" subject="mathematics" />,
    )
    unmount()
    expect(window.sessionStorage.getItem(canvasStorageKey('ABC123'))).toBeNull()
  })

  it('leaves nothing behind after a fresh page, even on the way out', () => {
    savePage('ABC123', storedPage())
    const { unmount } = render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" />)

    fireEvent.click(screen.getByRole('button', { name: /new page/i }))
    fireEvent.click(screen.getByRole('button', { name: /start a fresh page/i }))
    unmount()
    expect(window.sessionStorage.getItem(canvasStorageKey('ABC123'))).toBeNull()
  })

  it('keeps nothing at all without a session code', () => {
    const { unmount } = render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} />)
    unmount()
    expect(window.sessionStorage.length).toBe(0)
  })

  it('rescales a page drawn in a bigger window down into this one', () => {
    // Drawn at 800x600, reopened at 400x300: everything should halve, so
    // the drawing keeps its proportions and still fits on the page.
    savePage('ABC123', storedPage({ w: 800, h: 600 }))
    vi.restoreAllMocks()
    stubCanvas({ w: 400, h: 300 })

    const { unmount } = render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" />)
    unmount()

    const kept = loadPage('ABC123')!
    expect(kept.space).toEqual({ w: 400, h: 300 })
    expect(kept.strokes[0].points[0]).toMatchObject({ x: 50, y: 100 })
    expect(kept.strokes[0].points[1]).toMatchObject({ x: 150, y: 200 })
    expect(kept.strokes[0].width).toBe(2)
  })

  it('scales by the smaller ratio, so a reshaped window never distorts or overflows', () => {
    // 800x600 reopened at 800x300: scaling x and y independently would
    // squash the handwriting. Scaling both by 0.5 keeps it readable and on
    // the page.
    savePage('ABC123', storedPage({ w: 800, h: 600 }))
    vi.restoreAllMocks()
    stubCanvas({ w: 800, h: 300 })

    const { unmount } = render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" />)
    unmount()

    const points = loadPage('ABC123')!.strokes[0].points
    expect(points[0]).toMatchObject({ x: 50, y: 100 })
    expect(points[1]).toMatchObject({ x: 150, y: 200 })
  })

  it('leaves a page alone when the window has not changed', () => {
    savePage('ABC123', storedPage())
    const { unmount } = render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" />)
    unmount()

    const points = loadPage('ABC123')!.strokes[0].points
    expect(points[0]).toMatchObject({ x: 100, y: 200 })
    expect(points[1]).toMatchObject({ x: 300, y: 400 })
  })

  it('asks before throwing away a page with work on it', () => {
    savePage('ABC123', storedPage())
    render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" />)

    fireEvent.click(screen.getByRole('button', { name: /new page/i }))
    expect(screen.getByText(/start a fresh page\? this one will be gone/i)).toBeTruthy()
    expect(screen.getByRole('button', { name: /save it first/i })).toBeTruthy()
    expect(loadPage('ABC123')).not.toBeNull()

    fireEvent.click(screen.getByText('Never mind'))
    expect(loadPage('ABC123')).not.toBeNull()
  })

  it('forgets the page for good once the visitor starts a fresh one', () => {
    savePage('ABC123', storedPage())
    const { unmount } = render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" />)

    fireEvent.click(screen.getByRole('button', { name: /new page/i }))
    fireEvent.click(screen.getByRole('button', { name: /start a fresh page/i }))
    expect(loadPage('ABC123')?.strokes ?? []).toHaveLength(0)

    // And the unmount flush must not resurrect what was just put away.
    unmount()
    expect(loadPage('ABC123')?.strokes ?? []).toHaveLength(0)
  })

  it('starts a fresh page with no question when there is nothing to lose', () => {
    render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" />)
    fireEvent.click(screen.getByRole('button', { name: /new page/i }))
    expect(screen.queryByText(/this one will be gone/i)).toBeNull()
  })

  describe('when a page cannot be kept', () => {
    // Both cases need the debounced save to actually run, so these drive
    // the timers rather than waiting on them.
    function renderWithRefusedWrites() {
      savePage('ABC123', storedPage())
      vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('QuotaExceededError')
      })
      const rendered = render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" />)
      act(() => { vi.advanceTimersByTime(1_000) })
      return rendered
    }

    beforeEach(() => { vi.useFakeTimers() })
    afterEach(() => { vi.useRealTimers() })

    it('says so, in words, rather than failing quietly', () => {
      renderWithRefusedWrites()
      expect(screen.getByText(/can't keep this page on this device/i)).toBeTruthy()
    })

    it('brings the warning back when the visitor answers "Never mind"', () => {
      // The bug this pins: the refusal and the "start fresh?" question used
      // to share one piece of state, so dismissing the question also
      // dismissed the warning - leaving the visitor with an empty bar, no
      // saving happening, and no way to find that out.
      renderWithRefusedWrites()
      fireEvent.click(screen.getByRole('button', { name: /new page/i }))
      expect(screen.getByText(/start a fresh page\? this one will be gone/i)).toBeTruthy()

      fireEvent.click(screen.getByText('Never mind'))
      expect(screen.getByText(/can't keep this page on this device/i)).toBeTruthy()
    })

    it('stops warning once a fresh page is started', () => {
      renderWithRefusedWrites()
      fireEvent.click(screen.getByRole('button', { name: /new page/i }))
      fireEvent.click(screen.getByRole('button', { name: /start a fresh page/i }))
      expect(screen.queryByText(/can't keep this page/i)).toBeNull()
    })
  })

  it('saves during continuous drawing instead of deferring it forever', () => {
    // Every change restarts the 600ms debounce, so without a ceiling a
    // visitor who never pauses is never saved - and never warned about the
    // budget either, since the warning comes from a save.
    vi.useFakeTimers()
    try {
      savePage('ABC123', storedPage())
      render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" />)
      const setItem = vi.spyOn(Storage.prototype, 'setItem')

      // Ten changes, 400ms apart: never a 600ms gap, four seconds of work.
      for (let i = 0; i < 10; i++) {
        fireEvent.click(screen.getAllByRole('button', { name: /paper$/i })[i % 2])
        act(() => { vi.advanceTimersByTime(400) })
      }
      expect(setItem).toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('tells a Spanish-speaking visitor the same things in Spanish', async () => {
    await i18n.changeLanguage('es')
    savePage('ABC123', storedPage())
    render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="ABC123" />)

    fireEvent.click(screen.getByRole('button', { name: /hoja nueva/i }))
    expect(screen.getByText(/¿empezamos una hoja nueva\?/i)).toBeTruthy()
  })
})
