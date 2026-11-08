import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

// Runs the real public/sw.js with a fake service-worker global, so these
// checks cover the file the browser actually installs.
function loadWorker(fetchImpl: () => Promise<Response>) {
  const handlers: Record<string, (e: unknown) => void> = {}
  const self = {
    addEventListener: (type: string, fn: (e: unknown) => void) => { handlers[type] = fn },
    skipWaiting: () => {}, clients: { claim: () => {} },
  }
  const caches = {
    open: async () => ({ addAll: async () => {}, put: async () => {} }),
    keys: async () => [], delete: async () => true, match: async () => undefined,
  }
  const src = readFileSync(resolve(__dirname, '../public/sw.js'), 'utf8')
  new Function('self', 'caches', 'fetch', src)(self, caches, fetchImpl)
  return (url: string, method = 'GET') => {
    const respondWith = vi.fn()
    handlers.fetch({ request: { url, method }, respondWith })
    return respondWith
  }
}

describe('service worker', () => {
  it('never answers a tutoring turn itself, so a dropped send stays a network error the app retries', () => {
    const fetchImpl = vi.fn(() => Promise.reject(new TypeError('Load failed')))
    const dispatch = loadWorker(fetchImpl)
    expect(dispatch('https://bede.local/api/tutor/chat', 'POST')).not.toHaveBeenCalled()
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('leaves every API path to the network, GET included', () => {
    const dispatch = loadWorker(() => Promise.reject(new TypeError('Load failed')))
    for (const path of ['/api/pod/configs', '/api/practice/x/delivery', '/api/voice/stream/start']) {
      expect(dispatch('https://bede.local' + path)).not.toHaveBeenCalled()
    }
  })

  it('never invents an "offline" reply for anything', () => {
    const src = readFileSync(resolve(__dirname, '../public/sw.js'), 'utf8')
    expect(src).not.toMatch(/error:\s*'offline'|new Response\(/)
  })

  it('still serves static assets cache-first, and only for GET', () => {
    const dispatch = loadWorker(() => Promise.resolve(new Response('ok')))
    expect(dispatch('https://bede.local/assets/app.js')).toHaveBeenCalledTimes(1)
    expect(dispatch('https://bede.local/assets/app.js', 'POST')).not.toHaveBeenCalled()
  })
})
