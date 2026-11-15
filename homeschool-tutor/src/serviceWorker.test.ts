import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

import { isBedeWorker, retireServiceWorker } from './utils/serviceWorker'

// Bede's service worker is retired (docs/RELIABILITY.md). public/sw.js now
// only removes the worker an older version installed, and the app registers
// nothing. These run the real files.

const WORKER = readFileSync(resolve(__dirname, '../public/sw.js'), 'utf8')
const MAIN = readFileSync(resolve(__dirname, 'main.tsx'), 'utf8')

function loadWorker(cacheNames: string[]) {
  const handlers: Record<string, (e: unknown) => void> = {}
  const deleted: string[] = []
  const unregister = vi.fn(async () => true)
  const skipWaiting = vi.fn()
  const self = {
    addEventListener: (type: string, fn: (e: unknown) => void) => { handlers[type] = fn },
    skipWaiting, registration: { unregister },
  }
  const caches = {
    keys: async () => cacheNames,
    delete: async (k: string) => { deleted.push(k); return true },
  }
  new Function('self', 'caches', WORKER)(self, caches)
  return { handlers, deleted, unregister, skipWaiting }
}

describe('the retired service worker', () => {
  it('intercepts nothing, so every request reaches the network as if no worker existed', () => {
    const { handlers } = loadWorker([])
    expect(handlers.fetch).toBeUndefined()
    expect(WORKER).not.toMatch(/respondWith|addEventListener\(\s*['"]fetch/)
  })

  it('takes over at once, deletes the old caches and unregisters itself', async () => {
    const w = loadWorker(['bede-v2', 'bede-v3', 'someone-elses'])
    w.handlers.install({})
    expect(w.skipWaiting).toHaveBeenCalled()

    let done: Promise<unknown> = Promise.resolve()
    w.handlers.activate({ waitUntil: (p: Promise<unknown>) => { done = p } })
    await done

    expect(w.deleted.sort()).toEqual(['bede-v2', 'bede-v3'])
    expect(w.unregister).toHaveBeenCalledTimes(1)
  })

  it('never reloads an open page, so a lesson in progress is not interrupted', () => {
    expect(WORKER).not.toMatch(/\.navigate\(|location\.reload|clients\.claim/)
  })

  it('never invents a reply for anything', () => {
    expect(WORKER).not.toMatch(/new Response\(/)
  })
})

describe('the app registers no service worker', () => {
  it('main.tsx never calls register()', () => {
    expect(MAIN).not.toMatch(/serviceWorker\s*\.\s*register\s*\(/)
  })

  it('main.tsx retires an old worker on load', () => {
    expect(MAIN).toMatch(/retireServiceWorker\(\)/)
  })
})

const ORIGIN = 'https://bede.local'

function reg(stage: 'installing' | 'waiting' | 'active' | null, script = `${ORIGIN}/sw.js`) {
  const worker = stage ? { scriptURL: script } : null
  return {
    installing: stage === 'installing' ? worker : null,
    waiting: stage === 'waiting' ? worker : null,
    active: stage === 'active' ? worker : null,
    unregister: vi.fn(async () => true),
  } as unknown as ServiceWorkerRegistration & { unregister: ReturnType<typeof vi.fn> }
}

function navWith(regs: ServiceWorkerRegistration[]) {
  return { serviceWorker: { getRegistrations: async () => regs } } as unknown as Navigator
}

describe('isBedeWorker', () => {
  it.each(['installing', 'waiting', 'active'] as const)('recognises Bede\'s worker while it is %s', (stage) => {
    expect(isBedeWorker(reg(stage), ORIGIN)).toBe(true)
  })

  it('does not claim a worker running another script, from another origin, or with no worker at all', () => {
    expect(isBedeWorker(reg('active', `${ORIGIN}/other-sw.js`), ORIGIN)).toBe(false)
    expect(isBedeWorker(reg('active', 'https://elsewhere.example/sw.js'), ORIGIN)).toBe(false)
    expect(isBedeWorker(reg('active', `${ORIGIN}/app/sw.js`), ORIGIN)).toBe(false)
    expect(isBedeWorker(reg(null), ORIGIN)).toBe(false)
  })
})

describe('retireServiceWorker', () => {
  it('unregisters only Bede\'s worker and leaves an unrelated one on the same origin', async () => {
    vi.stubGlobal('location', { origin: ORIGIN })
    const bede = [reg('active'), reg('waiting'), reg('installing')]
    const other = reg('active', `${ORIGIN}/push-worker.js`)
    const deleted: string[] = []
    const store = {
      keys: async () => ['bede-v3', 'other-app'],
      delete: async (k: string) => { deleted.push(k); return true },
    } as unknown as CacheStorage

    expect(await retireServiceWorker(navWith([...bede, other]), store)).toBe(3)
    for (const r of bede) expect(r.unregister).toHaveBeenCalledTimes(1)
    expect(other.unregister).not.toHaveBeenCalled()
    expect(deleted).toEqual(['bede-v3'])
    vi.unstubAllGlobals()
  })

  it('is silent where service workers or Cache Storage are unavailable', async () => {
    await expect(retireServiceWorker(undefined, undefined)).resolves.toBe(0)
    const broken = { serviceWorker: { getRegistrations: async () => { throw new Error('SecurityError') } } } as unknown as Navigator
    const brokenStore = { keys: async () => { throw new Error('blocked') } } as unknown as CacheStorage
    await expect(retireServiceWorker(broken, brokenStore)).resolves.toBe(0)
  })

  it('keeps going when one registration refuses to unregister', async () => {
    vi.stubGlobal('location', { origin: ORIGIN })
    const refusing = reg('active')
    refusing.unregister.mockImplementation(async () => { throw new Error('nope') })
    expect(await retireServiceWorker(navWith([refusing, reg('active')]), undefined)).toBe(1)
    vi.unstubAllGlobals()
  })
})
