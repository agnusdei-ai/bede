import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

import ErrorBoundary from './ErrorBoundary'
import i18n from '../i18n'
import { clearDebugEntries, getDebugEntries } from '../hooks/debugBus'
import * as staleBuild from '../utils/staleBuild'
import { RELOAD_GUARD_MS, RELOAD_MARKER_KEY, isChunkLoadError, reloadOnceForNewRelease } from '../utils/staleBuild'

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

describe('ErrorBoundary', () => {
  it('records a render error in the debug log and shows the recovery screen', () => {
    const reload = vi.spyOn(staleBuild, 'reloadOnceForNewRelease')
    render(<ErrorBoundary><Throws error={new TypeError("Cannot read properties of undefined (reading 'map')")} /></ErrorBoundary>)

    expect(screen.getByRole('button', { name: /Return to Login/ })).toBeTruthy()
    expect(reload).not.toHaveBeenCalled()
    expect(getDebugEntries().map((e) => e.message).join('\n')).toMatch(/ERROR SCREEN render error TypeError: Cannot read properties/)
  })

  it('reloads once for a page file left behind by an update, without the error screen', () => {
    const reload = vi.spyOn(staleBuild, 'reloadOnceForNewRelease').mockReturnValue(true)
    render(<ErrorBoundary><Throws error={STALE} /></ErrorBoundary>)

    expect(reload).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('status').textContent).toMatch(/Bede was updated/)
    expect(screen.queryByRole('button', { name: /Return to Login/ })).toBeNull()
    expect(getDebugEntries().map((e) => e.message).join('\n')).toMatch(/page file failed to load/)
  })

  it('shows the recovery screen when it already reloaded and the file is still missing', () => {
    sessionStorage.setItem(RELOAD_MARKER_KEY, String(Date.now()))
    render(<ErrorBoundary><Throws error={STALE} /></ErrorBoundary>)
    expect(screen.getByRole('button', { name: /Return to Login/ })).toBeTruthy()
  })

  it('speaks Spanish to a Spanish session', async () => {
    await i18n.changeLanguage('es')
    render(<ErrorBoundary><Throws error={new Error('boom')} /></ErrorBoundary>)
    expect(screen.getByRole('button', { name: /Volver al inicio de sesión/ })).toBeTruthy()
  })
})
