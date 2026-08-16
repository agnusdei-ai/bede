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

describe('X-Bede-Instance capture', () => {
  // See homeschool-api's core/instance_id.py and core/middleware.py's
  // InstanceIdHeaderMiddleware: a voice-stream session's start and the
  // chunk/finish calls that follow it can land on different backend
  // processes under Render autoscaling, and a 404 from that reads
  // identically to a session that simply expired — from a single process's
  // own logs, and from an ordinary debug trace, there was no way to tell
  // them apart. This header, and the capture below, exist so a screenshot
  // of two `instance=` values can prove it directly.
  it('appends instance=<id> to the response line when the header is present', async () => {
    underlying.mockResolvedValueOnce(
      new Response('{}', { status: 200, headers: { 'X-Bede-Instance': 'srv-abc-1' } })
    )
    await fetch('https://example.test/voice/stream/abc123/events')

    expect(found('← 200 GET https://example.test/voice/stream/abc123/events (')).toBe(true)
    expect(messages().some((m) => m.endsWith('instance=srv-abc-1'))).toBe(true)
  })

  it('leaves the line exactly as before when the header is absent', async () => {
    // Every non-voice-stream endpoint, and any deployment where the CORS
    // expose_headers config is missing (the exact regression
    // test_the_instance_id_header_is_actually_exposed_cross_origin guards
    // on the backend) — this side must degrade to the ORIGINAL line, never
    // to a line with a literal "instance=null" or "instance=undefined".
    underlying.mockResolvedValueOnce(new Response('{}', { status: 200 }))
    await fetch('https://example.test/pod/configs')

    const line = messages().find((m) => m.startsWith('← 200'))
    expect(line).toBeDefined()
    expect(line).not.toContain('instance')
  })

  it('lets two responses on the same session be told apart by instance id', async () => {
    // The actual diagnostic: start succeeds on one instance, then
    // chunk/finish 404s because a DIFFERENT instance answered. Both lines
    // must carry their own, different instance= value for that to be
    // readable from a single screenshot, exactly as reported.
    underlying.mockResolvedValueOnce(
      new Response('{}', { status: 200, headers: { 'X-Bede-Instance': 'srv-abc-1' } })
    )
    underlying.mockResolvedValueOnce(
      new Response('{}', { status: 404, headers: { 'X-Bede-Instance': 'srv-xyz-2' } })
    )
    await fetch('https://example.test/voice/stream/abc123/start', { method: 'POST' })
    await fetch('https://example.test/voice/stream/abc123/finish', { method: 'POST' })

    const responseLines = messages().filter((m) => m.startsWith('←'))
    expect(responseLines[0]).toContain('instance=srv-abc-1')
    expect(responseLines[1]).toContain('instance=srv-xyz-2')
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
