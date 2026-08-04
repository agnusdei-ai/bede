/**
 * The rule worth pinning here is a NEGATIVE one, and it is the reason this
 * component was pulled out of App.tsx to be testable at all: a wrong
 * password produces a 401 exactly like an expired token does, and lands in
 * this same handler. Reporting it as "your session ended" would put a second,
 * false explanation on screen beside the true one.
 *
 * Driven the way a real caller would — call the global fetch() after mount
 * and assert on what the interceptor did — never reaching into internals.
 * Same harness shape as ElevationPrompt.test.tsx.
 */
import { cleanup, render, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSessionStore } from '../store/sessionStore'
import { takeLogoutNotice } from '../utils/logoutNotice'
import GlobalAuthInterceptor from './GlobalAuthInterceptor'

function respond(status: number) {
  return { status, clone() { return respond(status) }, json: async () => ({}) } as unknown as Response
}

/** Mount the interceptor and hand back the wrapped global fetch. */
function mountInterceptor(underlying: (...args: any[]) => Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn(underlying))
  render(
    <MemoryRouter>
      <GlobalAuthInterceptor />
    </MemoryRouter>,
  )
  return window.fetch
}

beforeEach(() => {
  sessionStorage.clear()
  useSessionStore.setState({ token: null, role: null })
})

afterEach(() => {
  cleanup()
  useSessionStore.setState({ token: null, role: null })
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('a 401 while a session was live', () => {
  it('records a session-expired notice so the login screen can explain itself', async () => {
    useSessionStore.setState({ token: 'live-token', role: 'parent' })
    const wrapped = mountInterceptor(async () => respond(401))

    await wrapped('/api/narration/emma/profile')

    await waitFor(() => expect(takeLogoutNotice()).toBe('session-expired'))
  })

  it('clears the session', async () => {
    useSessionStore.setState({ token: 'live-token', role: 'parent' })
    const wrapped = mountInterceptor(async () => respond(401))

    await wrapped('/api/narration/emma/profile')

    await waitFor(() => expect(useSessionStore.getState().token).toBe(null))
  })
})

describe('a 401 with no session behind it', () => {
  it('records no notice — a wrong password is not an expired session', async () => {
    // POST /auth/login with the wrong password returns 401 and passes
    // through this very handler. Without the token check, the parent would
    // be told their session expired on the first password they ever typed.
    const wrapped = mountInterceptor(async () => respond(401))

    await wrapped('/api/auth/login')

    expect(takeLogoutNotice()).toBe(null)
  })
})

describe('everything else is left alone', () => {
  it('ignores a 401 from a third-party origin', async () => {
    useSessionStore.setState({ token: 'live-token', role: 'parent' })
    const wrapped = mountInterceptor(async () => respond(401))

    await wrapped('https://elsewhere.example.com/whatever')

    expect(takeLogoutNotice()).toBe(null)
    expect(useSessionStore.getState().token).toBe('live-token')
  })

  it('passes a successful response straight through', async () => {
    useSessionStore.setState({ token: 'live-token', role: 'parent' })
    const wrapped = mountInterceptor(async () => respond(200))

    const res = await wrapped('/api/auth/validate')

    expect(res.status).toBe(200)
    expect(takeLogoutNotice()).toBe(null)
    expect(useSessionStore.getState().token).toBe('live-token')
  })

  it('stops intercepting once unmounted', async () => {
    // Asserted behaviourally rather than by identity: the cleanup restores
    // `window.fetch.bind(window)`, not the original reference, so a `toBe`
    // check would fail on a component that is in fact working correctly.
    useSessionStore.setState({ token: 'live-token', role: 'parent' })
    vi.stubGlobal('fetch', vi.fn(async () => respond(401)))
    const view = render(
      <MemoryRouter>
        <GlobalAuthInterceptor />
      </MemoryRouter>,
    )

    view.unmount()
    await window.fetch('/api/narration/emma/profile')

    expect(takeLogoutNotice()).toBe(null)
    expect(useSessionStore.getState().token).toBe('live-token')
  })
})
