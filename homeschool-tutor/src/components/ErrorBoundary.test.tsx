import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'

import ErrorBoundary from './ErrorBoundary'
import i18n from '../i18n'
import { clearDebugEntries, getDebugEntries } from '../hooks/debugBus'
import * as staleBuild from '../utils/staleBuild'
import { RELOAD_GUARD_MS, RELOAD_MARKER_KEY, entryScriptOf, isChunkLoadError, releaseChanged, reloadOnceForNewRelease } from '../utils/staleBuild'

function Throws({ error }: { error: Error }): never {
  throw error
}

const STALE = new TypeError('Failed to fetch dynamically imported module: https://bede.local/assets/TutorSession-abc123.js')

beforeEach(() => {
  clearDebugEntries()
  sessionStorage.clear()
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  void i18n.changeLanguage('en')
})

describe('isChunkLoadError', () => {
  it.each([
    'Failed to fetch dynamically imported module: /assets/x.js',
    'error loading dynamically imported module: /assets/x.js',
    'Importing a module script failed.',
    'Unable to preload CSS for /assets/x.css',
  ])('recognises %s', (message) => {
    expect(isChunkLoadError(new TypeError(message))).toBe(true)
  })

  it('does not mistake a render bug for a stale release', () => {
    expect(isChunkLoadError(new TypeError("Cannot read properties of undefined (reading 'map')"))).toBe(false)
    expect(isChunkLoadError(null)).toBe(false)
  })
})

describe('reloadOnceForNewRelease', () => {
  it('reloads once, then refuses inside the guard window so it can never loop', () => {
    const reload = vi.fn()
    expect(reloadOnceForNewRelease(reload, 1_000_000)).toBe(true)
    expect(reloadOnceForNewRelease(reload, 1_000_000 + RELOAD_GUARD_MS - 1)).toBe(false)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('may reload again after the guard window', () => {
    const reload = vi.fn()
    reloadOnceForNewRelease(reload, 1_000_000)
    expect(reloadOnceForNewRelease(reload, 1_000_000 + RELOAD_GUARD_MS + 1)).toBe(true)
    expect(reload).toHaveBeenCalledTimes(2)
  })

  it('does not reload when it cannot record that it did', () => {
    const reload = vi.fn()
    expect(reloadOnceForNewRelease(reload, 1, null)).toBe(false)
    const broken = { getItem: () => null, setItem: () => { throw new Error('QuotaExceededError') } } as unknown as Storage
    expect(reloadOnceForNewRelease(reload, 1, broken)).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })
})

function page(entry: string | null): Document {
  return new DOMParser().parseFromString(
    `<!doctype html><head>${entry ? `<script type="module" crossorigin src="${entry}"></script>` : ''}</head>`, 'text/html')
}

function served(html: string, ok = true) {
  return vi.fn(async () => ({ ok, text: async () => html }) as unknown as Response)
}

describe('releaseChanged', () => {
  const OLD = '/assets/index-OLD111.js'
  const NEW = '/assets/index-NEW222.js'
  const html = (entry: string) => `<!doctype html><html><head><script type="module" crossorigin src="${entry}"></script></head></html>`

  it('is true when the server names a different entry script', async () => {
    expect(await releaseChanged(served(html(NEW)), page(OLD))).toBe(true)
  })

  it('is false when the server names the same one', async () => {
    expect(await releaseChanged(served(html(OLD)), page(OLD))).toBe(false)
  })

  it('is false when the fetch fails or a navigation cancels it', async () => {
    const cancelled = vi.fn(async () => { throw new TypeError('Load failed') })
    expect(await releaseChanged(cancelled, page(OLD))).toBe(false)
    expect(await releaseChanged(served('', false), page(OLD))).toBe(false)
  })

  it('is false when either document names no entry script', async () => {
    expect(await releaseChanged(served('<p>maintenance</p>'), page(OLD))).toBe(false)
    expect(await releaseChanged(served(html(NEW)), page(null))).toBe(false)
  })

  it('is false in development, where both name /src/main.tsx', async () => {
    expect(await releaseChanged(served(html('/src/main.tsx')), page('/src/main.tsx'))).toBe(false)
  })

  it('asks for the page uncached', async () => {
    const f = served(html(NEW))
    await releaseChanged(f, page(OLD))
    expect(f).toHaveBeenCalledWith('/', expect.objectContaining({ cache: 'no-store' }))
  })

  it('reads the entry script a real build writes', () => {
    expect(entryScriptOf(page('/assets/index-Cg5PxFbO.js'))).toBe('/assets/index-Cg5PxFbO.js')
  })
})

describe('ErrorBoundary', () => {
  it('records a render error in the debug log and shows the recovery screen', () => {
    const reload = vi.spyOn(staleBuild, 'reloadOnceForNewRelease')
    render(<ErrorBoundary><Throws error={new TypeError("Cannot read properties of undefined (reading 'map')")} /></ErrorBoundary>)

    expect(screen.getByRole('button', { name: /Return to Login/ })).toBeTruthy()
    expect(reload).not.toHaveBeenCalled()
    expect(getDebugEntries().map((e) => e.message).join('\n')).toMatch(/ERROR SCREEN render error TypeError: Cannot read properties/)
  })

  it('reloads once when the server serves a new release, without the error screen', async () => {
    vi.spyOn(staleBuild, 'releaseChanged').mockResolvedValue(true)
    const reload = vi.spyOn(staleBuild, 'reloadOnceForNewRelease').mockReturnValue(true)
    render(<ErrorBoundary><Throws error={STALE} /></ErrorBoundary>)

    expect(screen.getByRole('status').textContent).toMatch(/Checking for a new version/)
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/Bede was updated/))
    expect(reload).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: /Return to Login/ })).toBeNull()
    expect(getDebugEntries().map((e) => e.message).join('\n')).toMatch(/page file failed to load/)
  })

  it('never reloads for a failed page file when the release has not changed', async () => {
    // The regression the WebKit journeys caught: a page navigating away
    // cancels the page files it was loading, which reads exactly like a
    // stale release. Reloading on that hijacked the navigation underway.
    vi.spyOn(staleBuild, 'releaseChanged').mockResolvedValue(false)
    const reload = vi.spyOn(staleBuild, 'reloadOnceForNewRelease')
    render(<ErrorBoundary><Throws error={STALE} /></ErrorBoundary>)

    expect(await screen.findByRole('button', { name: /Return to Login/ })).toBeTruthy()
    expect(reload).not.toHaveBeenCalled()
    expect(getDebugEntries().map((e) => e.message).join('\n')).toMatch(/release unchanged, not reloading/)
  })

  it('shows the recovery screen when it already reloaded and the file is still missing', async () => {
    vi.spyOn(staleBuild, 'releaseChanged').mockResolvedValue(true)
    sessionStorage.setItem(RELOAD_MARKER_KEY, String(Date.now()))
    render(<ErrorBoundary><Throws error={STALE} /></ErrorBoundary>)
    expect(await screen.findByRole('button', { name: /Return to Login/ })).toBeTruthy()
  })

  it('never asks the server about a render error', () => {
    const asked = vi.spyOn(staleBuild, 'releaseChanged')
    render(<ErrorBoundary><Throws error={new Error('boom')} /></ErrorBoundary>)
    expect(asked).not.toHaveBeenCalled()
  })

  it('speaks Spanish to a Spanish session', async () => {
    await i18n.changeLanguage('es')
    render(<ErrorBoundary><Throws error={new Error('boom')} /></ErrorBoundary>)
    expect(screen.getByRole('button', { name: /Volver al inicio de sesión/ })).toBeTruthy()
  })
})

describe('main.tsx', () => {
  it('only records a preload failure; the error screen alone decides to reload', async () => {
    const { readFileSync } = await import('node:fs')
    const { resolve } = await import('node:path')
    const main = readFileSync(resolve(__dirname, '../main.tsx'), 'utf8')
    const start = main.indexOf("addEventListener('vite:preloadError'")
    expect(start).toBeGreaterThan(-1)
    // The handler ends at its own closing line; a `})` inside a type
    // annotation must not cut the slice short.
    const handler = main.slice(start, main.indexOf('\n})', start))
    expect(handler).toMatch(/logDebug/)
    expect(handler).not.toMatch(/preventDefault|reloadOnceForNewRelease|location\.reload/)
  })
})
