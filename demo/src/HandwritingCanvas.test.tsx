/**
 * canvasPersistence.test.ts proves the store keeps and refuses the right
 * things. This covers what it cannot: that the component READS it at mount
 * and WRITES it on the way out.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from './i18n'
import HandwritingCanvas from './HandwritingCanvas'
import { canvasStorageKey, loadPage, savePage } from './canvasPersistence'

// jsdom has no 2D context. Everything this component asks of one is a draw
// call whose output nothing here inspects, so a recording stub is enough -
// the assertions below are all about storage and what the visitor is shown.
function stubCanvas() {
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
}

function storedPage(strokes = 1) {
  return {
    strokes: Array.from({ length: strokes }, (_, i) => ({
      points: [
        { x: 100 + i, y: 200 + i, pressure: 0.5 },
        { x: 300 + i, y: 400 + i, pressure: 0.5 },
      ],
      width: 4,
      color: '#1b3a6b',
      isEraser: false,
    })),
    paperStyle: 'staff',
    paperColor: '#2e3a44',
  }
}

beforeEach(() => {
  window.sessionStorage.clear()
  stubCanvas()
  // jsdom ships no ResizeObserver; the component uses one only to letterbox
  // the paper to the window, which has no bearing on anything asserted here.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
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
    // The flush is synchronous on unmount rather than waiting out the save
    // debounce, which would never fire once the component is gone.
    const kept = loadPage('ABC123')
    expect(kept?.strokes).toHaveLength(1)
    expect(kept?.paperStyle).toBe('staff')
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

  it('keeps a restored page exactly as drawn, regardless of this window\'s size', () => {
    // The whole point of the fixed page space: a page drawn on a phone and
    // reopened on a desktop (or the reverse) is the SAME physical page,
    // so nothing here needs to rescale it - unlike before this component
    // matched the app's fixed CANVAS_WIDTH/HEIGHT backing store, when a
    // restored page had to be scaled to fit whatever window it landed in.
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

  describe('saving a drawing to the device', () => {
    // jsdom's HTMLCanvasElement has no toBlob at all - handleSaveToDevice
    // falls back to toDataURL without it, which is why this needs its own
    // stub rather than relying on the beforeEach one.
    function stubToBlob() {
      vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (
        this: HTMLCanvasElement,
        callback: BlobCallback,
      ) {
        callback(new Blob(['x'], { type: 'image/png' }))
      })
    }

    it('does not revoke the object URL right away, so a slow mobile download is not cut off', () => {
      // Safari/iOS has a documented history of treating a Blob's object URL
      // as already gone if it is revoked while the download is still being
      // read from it. This is exactly the class of thing that cannot be
      // verified against a real device in this sandbox, so the test pins
      // the defensive choice (a long delay) rather than the browser
      // behavior it is defending against.
      vi.useFakeTimers()
      try {
        stubToBlob()
        vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-url')
        const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
        render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} />)

        // By accessible name rather than `title` — see the app's copy of this
        // test. The toolbar moved off hover-only `title` onto IconButton.
        fireEvent.click(screen.getByRole('button', { name: 'Save' }))
        expect(revokeObjectURL).not.toHaveBeenCalled()

        // Nowhere near revoked a few seconds in - a slow connection needs
        // more than an instant, and a plain setTimeout(...,0) would have
        // already fired by here.
        act(() => { vi.advanceTimersByTime(5_000) })
        expect(revokeObjectURL).not.toHaveBeenCalled()

        act(() => { vi.advanceTimersByTime(60_000) })
        expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
      } finally {
        vi.useRealTimers()
      }
    })
  })

  it('gives every toolbar control an accessible name', () => {
    // The regression this exists for: IconButton's `textual` prop suppresses
    // aria-label so that a button's own visible text stays its accessible
    // name. Set it on a control that renders an ICON (or a styled dot, as the
    // brush sizes do) and the button ends up with no name at all — worse than
    // the hover-only `title` this replaced, and invisible without a test,
    // since nothing renders differently.
    render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} />)
    for (const button of screen.getAllByRole('button')) {
      const name = button.getAttribute('aria-label') || button.textContent?.trim()
      expect(name, `unnamed control: ${button.outerHTML.slice(0, 120)}`).toBeTruthy()
    }
  })

})
