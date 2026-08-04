/**
 * The two root-level fetch wrappers, tested TOGETHER (P11 —
 * docs/ARCHITECTURE_PRINCIPLES.md: controls correct in isolation can still
 * be wrong in composition, and each of these has its own passing test
 * already).
 *
 * App.tsx mounts GlobalAuthInterceptor (401 -> logout) and then
 * ElevationPrompt (403 elevation_required -> password prompt -> retry).
 * Sibling effects run in mount order, so the chain a call actually
 * travels is:
 *
 *     window.fetch = ElevationPrompt( GlobalAuthInterceptor( native ) )
 *
 * That ordering is load-bearing in a way neither component's own tests can
 * see, and it has one genuinely surprising consequence — see
 * `a wrong password at the elevation prompt` below.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { elevateSession, fetchMfaStatus, navigate } = vi.hoisted(() => ({
  elevateSession: vi.fn(),
  fetchMfaStatus: vi.fn(),
  navigate: vi.fn(),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return { ...actual, elevateSession, fetchMfaStatus }
})
vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>()
  return { ...actual, useNavigate: () => navigate }
})

import ElevationPrompt from './ElevationPrompt'
import GlobalAuthInterceptor from './GlobalAuthInterceptor'
import { useSessionStore } from '../store/sessionStore'

/** Mirrors App.tsx's own mount order exactly — that order is the thing
 *  under test, so it must not be re-arranged here for convenience. */
function renderBothInterceptors() {
  return render(
    <MemoryRouter>
      <GlobalAuthInterceptor />
      <ElevationPrompt />
    </MemoryRouter>,
  )
}

function elevationRequired403() {
  return {
    status: 403,
    clone() { return elevationRequired403() },
    json: async () => ({ detail: { message: 'Confirm your password', elevation_required: true } }),
  }
}

beforeEach(() => {
  useSessionStore.setState({ token: 'parent-tok', role: 'parent' })
  elevateSession.mockReset()
  fetchMfaStatus.mockReset()
  navigate.mockReset()
  fetchMfaStatus.mockResolvedValue({
    webauthn_available: false, security_keys: [], totp_enabled: false, recovery_secret: null,
  })
})

afterEach(() => {
  useSessionStore.setState({ token: null, role: null })
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  cleanup()
})

describe('GlobalAuthInterceptor + ElevationPrompt composition', () => {
  it('a 401 still logs out when BOTH wrappers are installed', async () => {
    const nativeFetch = vi.fn().mockResolvedValue({
      status: 401,
      clone: () => ({ json: async () => ({}) }),
      json: async () => ({}),
    })
    vi.stubGlobal('fetch', nativeFetch)

    renderBothInterceptors()
    await act(async () => { await fetch('/api/admin/status') })

    // ElevationPrompt's wrapper sits OUTSIDE GlobalAuthInterceptor's, so a
    // 401 has to pass through it untouched to reach the logout.
    expect(useSessionStore.getState().token).toBeNull()
    expect(navigate).toHaveBeenCalledWith('/', { replace: true })
  })

  it('a 403 still prompts, and the retry passes back through the 401 wrapper', async () => {
    const nativeFetch = vi.fn()
      .mockResolvedValueOnce(elevationRequired403())
      .mockResolvedValueOnce({ status: 200, json: async () => ({ ok: true }) })
    vi.stubGlobal('fetch', nativeFetch)
    elevateSession.mockResolvedValue({ elevated: true, expiresAt: 'x', ttlSeconds: 600 })

    renderBothInterceptors()
    let pending: Promise<Response>
    act(() => { pending = fetch('/api/admin/audit') as Promise<Response> })

    fireEvent.change(await screen.findByLabelText('Password'), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    const result = await pending!
    expect(result.status).toBe(200)
    // Still logged in — a successful elevation must not trip the 401 path.
    expect(useSessionStore.getState().token).toBe('parent-tok')
  })

  it('a wrong password at the elevation prompt does NOT log the parent out', async () => {
    // The composition trap this file exists for, and it only shows up
    // against the REAL elevateSession — mocking it (as the two tests above
    // legitimately do) skips the fetch call that is the whole risk.
    //
    // elevateSession() is called from inside ElevationPrompt's own modal,
    // so it travels the SAME wrapped window.fetch chain as everything
    // else. POST /auth/elevate correctly answers a wrong password with
    // 401 — and that 401 reaches GlobalAuthInterceptor, which cannot tell
    // it apart from an expired session. Without a guard, mistyping your
    // password in a step-up prompt ends the entire session and tells you
    // something false about why. Neither component's own test can see
    // this: each is correct alone.
    const actual = await vi.importActual<typeof import('../services/api')>('../services/api')
    elevateSession.mockImplementation(actual.elevateSession)

    const nativeFetch = vi.fn(async (url: string) =>
      String(url).includes('/auth/elevate')
        ? { ok: false, status: 401, clone: () => ({ json: async () => ({ detail: 'Password is incorrect' }) }), json: async () => ({ detail: 'Password is incorrect' }) }
        : elevationRequired403()
    )
    vi.stubGlobal('fetch', nativeFetch)

    renderBothInterceptors()
    act(() => { fetch('/api/admin/audit') })

    fireEvent.change(await screen.findByLabelText('Password'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    expect(await screen.findByText('Password is incorrect')).toBeTruthy()
    // The parent stays logged in and stays on the page — they mistyped a
    // password, they did not lose their session.
    await waitFor(() => {
      expect(useSessionStore.getState().token).toBe('parent-tok')
    })
    expect(navigate).not.toHaveBeenCalledWith('/', { replace: true })
  })
})
