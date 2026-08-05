/**
 * The unit tests in utils/canvasPersistence.test.ts prove the store keeps
 * and refuses the right things. What they cannot prove is that this
 * component actually READS it on the way in and WRITES it on the way out,
 * which is the whole of what a child experiences: the page is still there
 * when they come back from Bede, and gone when they said to put it away.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import HandwritingCanvas from './HandwritingCanvas'
import { canvasStorageKey, loadPage, savePage } from '../utils/canvasPersistence'

// jsdom has no 2D context. Everything this component asks of one is a draw
// call whose output nothing here inspects, so a recording stub is enough -
// the assertions below are all about storage and what the child is shown.
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

function storedPage(strokes = 2) {
  return {
    strokes: Array.from({ length: strokes }, (_, i) => ({
      points: [
        { x: i, y: i, pressure: 0.5 },
        { x: i + 10, y: i + 10, pressure: 0.5 },
      ],
      width: 3,
      color: '#1b3a6b',
      tool: 'pen' as const,
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

describe('HandwritingCanvas page persistence', () => {
  it('comes back to the page the child left, paper and all', () => {
    savePage('Emma', storedPage())
    render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="Emma" />)

    // Undo is only live when there are strokes to undo, so an enabled Undo
    // is this component saying "I have the child's strokes".
    expect(screen.getByRole('button', { name: /undo/i }).hasAttribute('disabled')).toBe(false)
    expect(screen.getByRole('button', { name: 'Staff' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('keeps the page when the child leaves for Bede', () => {
    const { unmount } = render(
      <HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="Emma" subject="mathematics" />,
    )
    expect(window.sessionStorage.getItem(canvasStorageKey('Emma'))).toBeNull()

    unmount()
    // The flush is synchronous on unmount rather than waiting out the save
    // debounce, which would never fire once the component is gone.
    expect(loadPage('Emma')?.paperStyle).toBe('graph')
  })

  it('keeps nothing at all without a persist key', () => {
    const { unmount } = render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} />)
    unmount()
    expect(window.sessionStorage.length).toBe(0)
  })

  it('asks before throwing away a page with work on it', () => {
    savePage('Emma', storedPage())
    render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="Emma" />)

    fireEvent.click(screen.getByRole('button', { name: /new page/i }))
    expect(screen.getByText(/start a fresh page\? this one will be gone/i)).toBeTruthy()
    // Still there: asking is not doing.
    expect(loadPage('Emma')).not.toBeNull()

    fireEvent.click(screen.getByText('Never mind'))
    expect(loadPage('Emma')).not.toBeNull()
  })

  it('offers a way to keep the drawing before it goes', () => {
    savePage('Emma', storedPage())
    render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="Emma" />)

    fireEvent.click(screen.getByRole('button', { name: /new page/i }))
    expect(screen.getByRole('button', { name: /save it first/i })).toBeTruthy()
  })

  it('forgets the page for good once the child starts a fresh one', () => {
    savePage('Emma', storedPage())
    const { unmount } = render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="Emma" />)

    fireEvent.click(screen.getByRole('button', { name: /new page/i }))
    fireEvent.click(screen.getByRole('button', { name: /start a fresh page/i }))
    expect(loadPage('Emma')?.strokes ?? []).toHaveLength(0)

    // And the unmount flush must not resurrect what was just put away.
    unmount()
    expect(loadPage('Emma')?.strokes ?? []).toHaveLength(0)
  })

  it('starts a fresh page with no question when there is nothing to lose', () => {
    render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="Emma" />)
    fireEvent.click(screen.getByRole('button', { name: /new page/i }))
    expect(screen.queryByText(/this one will be gone/i)).toBeNull()
  })

  it('tells a Spanish-speaking child the same things in Spanish', async () => {
    await i18n.changeLanguage('es')
    savePage('Emma', storedPage())
    render(<HandwritingCanvas onSubmit={vi.fn()} onCancel={vi.fn()} persistKey="Emma" />)

    fireEvent.click(screen.getByRole('button', { name: /hoja nueva/i }))
    expect(screen.getByText(/¿empezamos una hoja nueva\?/i)).toBeTruthy()
  })
})
