/**
 * These tests exist because the diagnostics they cover were written in
 * response to a failure that the app's own instrumentation could not see.
 * A diagnostic that silently stops working is worse than none, because it
 * is trusted — so each case here asserts that a specific failure SHOWS UP
 * in the buffer, not merely that the code runs.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearDebugEntries, getDebugEntries } from './debugBus'
import { installDiagnostics } from './diagnostics'

// Order matters and is the whole trick here. installDiagnostics() captures
// whatever `fetch` exists at install time and replaces the global with its
// wrapper, so the mock has to be in place FIRST — then calling fetch() runs
// wrapper → mock. Spying on the global afterwards would replace the wrapper
// instead of the thing it delegates to, and silently test nothing.
const underlying = vi.fn()
vi.stubGlobal('fetch', underlying)
installDiagnostics() // the real app installs once, at boot

const messages = () => getDebugEntries().map((e) => e.message)
const found = (needle: string) => messages().some((m) => m.includes(needle))

beforeEach(() => {
  clearDebugEntries()
  underlying.mockReset()
})

describe('CSP violations', () => {
  it('records the directive and blocked URI', () => {
    // The exact shape of the 2026-08-04 outage: connect-src refused the
    // demo's own backend, no request was issued, and the server saw
    // nothing. This event was the only structured evidence available.
    const ev = new Event('securitypolicyviolation') as SecurityPolicyViolationEvent
    Object.assign(ev, {
      effectiveDirective: 'connect-src',
      violatedDirective: 'connect-src',
      blockedURI: 'https://bede-demo-api.onrender.com/auth/demo-code',
      sourceFile: 'https://agnusdei.ai/bede/assets/index.js',
      lineNumber: 42,
    })
    document.dispatchEvent(ev)

    expect(found('CSP BLOCKED')).toBe(true)
    expect(found('directive=connect-src')).toBe(true)
    expect(found('bede-demo-api.onrender.com/auth/demo-code')).toBe(true)
  })
})

describe('fetch logging', () => {
  it('logs a request and its status', async () => {
    underlying.mockResolvedValueOnce(new Response('{}', { status: 200 }))
    await fetch('https://example.test/auth/demo-code', { method: 'POST' })

    // Both halves matter: a "→" with no matching "←" is precisely the
    // signature of a request that was blocked before it was ever sent,
    // which is what the CSP bug looked like from inside the app.
    expect(found('→ POST https://example.test/auth/demo-code')).toBe(true)
    expect(found('← 200 POST https://example.test/auth/demo-code')).toBe(true)
  })

  it('logs the RAW error when a request fails, not a friendly substitute', async () => {
    underlying.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(fetch('https://example.test/auth/demo-code')).rejects.toThrow()

    expect(found('✗ GET https://example.test/auth/demo-code')).toBe(true)
    expect(found('TypeError: Failed to fetch')).toBe(true)
  })

  it('re-throws rather than swallowing — diagnostics must not change behaviour', async () => {
    const boom = new TypeError('Load failed')
    underlying.mockRejectedValueOnce(boom)
    await expect(fetch('https://example.test/x')).rejects.toBe(boom)
  })
})

describe('privacy', () => {
  it('never records a query string', async () => {
    // A debug panel is screenshot-able by design and this is a children's
    // product: a student name or token in a query string must not survive
    // into a buffer somebody photographs.
    underlying.mockResolvedValueOnce(new Response('{}', { status: 200 }))
    await fetch('https://example.test/pod/configs?student=Emma&token=secret123')

    expect(found('/pod/configs')).toBe(true)
    expect(found('Emma')).toBe(false)
    expect(found('secret123')).toBe(false)
    expect(found('?')).toBe(false)
  })
})
