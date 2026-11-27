import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  RELOCATE_MARKER_KEY,
  installWebkitNavigationGuard,
  navigationEntryIsStale,
} from './webkitNavigationGuard'

// A window stand-in whose Navigation API behaves like WebKit 26.0 (the entry
// never follows pushState) or like a fixed engine (it does).
function fakeWindow(engine: 'webkit26.0' | 'fixed' | 'no-navigation-api') {
  let href = 'http://127.0.0.1/'
  let entryUrl: string | null = href
  const store = new Map<string, string>()
  const replace = vi.fn((to: string) => { href = to; entryUrl = to })
  const history = {
    pushState(_s: unknown, _t: string, url?: string | URL | null) {
      href = new URL(String(url), href).href
      if (engine === 'fixed') entryUrl = href
    },
  } as unknown as History
  const win = {
    history,
    location: { get href() { return href }, replace },
    sessionStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => { store.set(k, v) },
    },
    ...(engine === 'no-navigation-api' ? {} : {
      navigation: { get currentEntry() { return entryUrl === undefined ? null : { url: entryUrl } } },
    }),
  } as unknown as Window
  return { win, replace, store, setEntry: (u: string | null) => { entryUrl = u } }
}

let uninstall = () => {}
afterEach(() => uninstall())

describe('WebKit 26.0 reload-crash guard (#861)', () => {
  it('relocates once when the engine did not record the push', () => {
    const f = fakeWindow('webkit26.0')
    const log = vi.fn()
    uninstall = installWebkitNavigationGuard(f.win, log)
    f.win.history.pushState({}, '', '/session?student=A')
    expect(f.replace).toHaveBeenCalledTimes(1)
    expect(f.replace).toHaveBeenCalledWith('http://127.0.0.1/session?student=A')
    expect(log).toHaveBeenCalledTimes(1)
    expect(navigationEntryIsStale(f.win)).toBe(false)
  })

  it('does nothing on an engine that records the push', () => {
    const f = fakeWindow('fixed')
    uninstall = installWebkitNavigationGuard(f.win)
    f.win.history.pushState({}, '', '/session')
    expect(f.replace).not.toHaveBeenCalled()
  })

  it('does nothing without a Navigation API (older Firefox)', () => {
    const f = fakeWindow('no-navigation-api')
    const before = f.win.history.pushState
    uninstall = installWebkitNavigationGuard(f.win)
    expect(f.win.history.pushState).toBe(before)
  })

  it('never navigates from an already-empty entry, which crashes too', () => {
    const f = fakeWindow('webkit26.0')
    uninstall = installWebkitNavigationGuard(f.win)
    f.setEntry(null)
    f.win.history.pushState({}, '', '/session')
    expect(f.replace).not.toHaveBeenCalled()
  })

  it('cannot loop on an engine that never reports a match', () => {
    const f = fakeWindow('webkit26.0')
    uninstall = installWebkitNavigationGuard(f.win)
    f.win.history.pushState({}, '', '/session')
    f.setEntry('http://127.0.0.1/') // the relocation "did not take"
    f.win.history.pushState({}, '', '/session')
    expect(f.replace).toHaveBeenCalledTimes(1)
    expect(f.store.has(RELOCATE_MARKER_KEY)).toBe(true)
  })

  it('is installed by main.tsx before the app renders', async () => {
    const { readFileSync } = await import('node:fs')
    const { resolve } = await import('node:path')
    const src = readFileSync(resolve(__dirname, 'main.tsx'), 'utf8')
    const install = src.indexOf('installWebkitNavigationGuard(window')
    expect(install).toBeGreaterThan(-1)
    expect(install).toBeLessThan(src.indexOf('createRoot(document'))
  })

  it('is the same code the app ships, byte for byte', async () => {
    const { readFileSync } = await import('node:fs')
    const { resolve } = await import('node:path')
    const demo = readFileSync(resolve(__dirname, 'webkitNavigationGuard.ts'), 'utf8')
    const app = readFileSync(resolve(__dirname, '../../homeschool-tutor/src/utils/webkitNavigationGuard.ts'), 'utf8')
    expect(demo).toBe(app)
  })
})
