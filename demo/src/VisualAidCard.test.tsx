/**
 * Regression coverage for a real reliability gap: the Wikipedia summary
 * lookup had no retry at all, so a single transient failure (a slow mobile
 * connection, a dropped packet) permanently showed "Picture unavailable
 * right now" for that card, with no way to recover within the same turn —
 * reported live from a real session on a weak-signal connection, after the
 * previously-diagnosed CSP root cause (site/_headers) was independently
 * confirmed still correctly deployed (site-headers-live.yml green), so the
 * card's own fetch resilience was the remaining gap.
 *
 * What's pinned here:
 *   - a lookup that fails once and then succeeds still resolves to the
 *     image (the actual fix — this failed before it existed);
 *   - a lookup that succeeds on the first try never waits for a retry
 *     (no regression to the common case's speed);
 *   - a lookup that fails on every attempt still degrades to the
 *     "Picture unavailable right now" captioned card, never a broken-image
 *     icon (the pre-existing guarantee, still intact);
 *   - unmounting mid-retry aborts cleanly with no state update after
 *     unmount (no "can't update state on an unmounted component" warning,
 *     no crash).
 */
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import VisualAidCard from './VisualAidCard'
import type { VisualAidData } from './api'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

beforeEach(() => {
  vi.useFakeTimers()
})

const aid: VisualAidData = {
  id: 'millet_angelus',
  category: 'picture_study',
  title: 'The Angelus',
  creator: 'Jean-François Millet',
  year: '1857-1859',
  wiki_title: 'The Angelus (painting)',
  description: 'Two farm workers pause at dusk to pray the Angelus.',
}

const okResponse = () => ({
  ok: true,
  json: async () => ({ thumbnail: { source: 'https://upload.wikimedia.org/angelus.jpg' } }),
})

const failedResponse = () => ({ ok: false, status: 503, json: async () => ({}) })

describe('VisualAidCard — Wikipedia lookup resilience', () => {
  it('resolves the image after one transient failure followed by success', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(failedResponse())
      .mockResolvedValueOnce(okResponse())
    vi.stubGlobal('fetch', fetchMock)

    render(<VisualAidCard aid={aid} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    const img = screen.getByRole('img', { name: 'The Angelus' }) as HTMLImageElement
    expect(img.src).toBe('https://upload.wikimedia.org/angelus.jpg')
    expect(screen.queryByText('Picture unavailable right now')).toBeNull()
  })

  it('does not wait for a retry when the first attempt succeeds', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(okResponse())
    vi.stubGlobal('fetch', fetchMock)

    render(<VisualAidCard aid={aid} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('img', { name: 'The Angelus' })).not.toBeNull()
  })

  it('still degrades to the captioned card when every attempt fails', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(failedResponse())
      .mockResolvedValueOnce(failedResponse())
    vi.stubGlobal('fetch', fetchMock)

    render(<VisualAidCard aid={aid} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(screen.queryByText('Picture unavailable right now')).not.toBeNull()
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('aborts cleanly when unmounted mid-retry, with no state update after unmount', async () => {
    // A real fetch() rejects immediately when handed an already-aborted
    // signal — this mock has to model that itself, since a plain vi.fn()
    // has no idea AbortController semantics exist, unlike a real browser.
    const fetchMock = vi.fn().mockImplementation((_url: string, init?: { signal?: AbortSignal }) => {
      if (init?.signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'))
      return Promise.resolve(failedResponse())
    })
    vi.stubGlobal('fetch', fetchMock)
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const { unmount } = render(<VisualAidCard aid={aid} />)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    unmount()
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })

    // The retry wait races the abort signal rather than a bare setTimeout —
    // an unmount mid-wait must short-circuit immediately, never reaching a
    // second, wasted fetch() call after the delay finally elapses.
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const reactWarnings = errorSpy.mock.calls.filter((c) =>
      String(c[0]).includes('unmounted') || String(c[0]).includes('act('),
    )
    expect(reactWarnings).toHaveLength(0)
    errorSpy.mockRestore()
  })
})
