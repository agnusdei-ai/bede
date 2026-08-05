/**
 * Frontend half of P8 (core/elevation.py) — ElevationPrompt.tsx wraps
 * window.fetch so any of the ~15 elevation-gated call sites gets a password
 * prompt automatically instead of a bare, unexplained 403. These tests drive
 * it exactly the way a real caller would: call the global fetch() after the
 * component has mounted and assert on what that call ultimately resolves to,
 * never reaching into the component's internals.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { elevateSession, fetchMfaStatus } = vi.hoisted(() => ({
  elevateSession: vi.fn(),
  fetchMfaStatus: vi.fn(),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return { ...actual, elevateSession, fetchMfaStatus }
})

import { useSessionStore } from '../store/sessionStore'
import ElevationPrompt from './ElevationPrompt'

function elevationRequired403() {
  return {
    status: 403,
    clone() {
      return elevationRequired403()
    },
    json: async () => ({ detail: { message: 'Confirm your password to continue', elevation_required: true } }),
  }
}

function ordinary403() {
  return {
    status: 403,
    clone() {
      return ordinary403()
    },
    json: async () => ({ detail: 'Not authorized' }),
  }
}

beforeEach(() => {
  useSessionStore.setState({ token: 'parent-tok', role: 'parent' })
  elevateSession.mockReset()
  fetchMfaStatus.mockReset()
  fetchMfaStatus.mockResolvedValue({
    webauthn_available: false,
    security_keys: [],
    totp_enabled: false,
    recovery_secret: null,
  })
})

afterEach(() => {
  useSessionStore.setState({ token: null, role: null })
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  cleanup()
})

describe('ElevationPrompt — intercepting an unelevated call', () => {
  it('shows the password prompt when a wrapped call returns the elevation_required shape', async () => {
    const originalFetch = vi.fn().mockResolvedValue(elevationRequired403())
    vi.stubGlobal('fetch', originalFetch)

    render(<ElevationPrompt />)
    act(() => {
      fetch('/api/admin/audit')
    })

    expect(await screen.findByText('Confirm your password')).toBeTruthy()
  })

  it('does not prompt for an ordinary 403 with no elevation_required marker', async () => {
    const originalFetch = vi.fn().mockResolvedValue(ordinary403())
    vi.stubGlobal('fetch', originalFetch)

    render(<ElevationPrompt />)
    let result: any
    await act(async () => {
      result = await fetch('/api/some/endpoint')
    })

    expect(screen.queryByText('Confirm your password')).toBeNull()
    expect(result.status).toBe(403)
  })

  it('does not prompt for a plain 200 response', async () => {
    const originalFetch = vi.fn().mockResolvedValue({ status: 200, clone: () => ({ json: async () => ({}) }), json: async () => ({}) })
    vi.stubGlobal('fetch', originalFetch)

    render(<ElevationPrompt />)
    await act(async () => {
      await fetch('/api/some/endpoint')
    })

    expect(screen.queryByText('Confirm your password')).toBeNull()
  })

  it('never wraps fetch for a non-parent role', async () => {
    useSessionStore.setState({ role: 'child' })
    const originalFetch = vi.fn().mockResolvedValue(elevationRequired403())
    vi.stubGlobal('fetch', originalFetch)

    render(<ElevationPrompt />)
    let result: any
    await act(async () => {
      result = await fetch('/api/admin/audit')
    })

    // Passed straight to the real fetch, unexamined — a child session never
    // reaches an elevation-gated endpoint, so there is nothing to intercept.
    expect(result.status).toBe(403)
    expect(screen.queryByText('Confirm your password')).toBeNull()
  })
})

describe('ElevationPrompt — successful elevation retries the original call', () => {
  it('elevates, retries once, and the caller sees the retried response', async () => {
    const originalFetch = vi.fn()
      .mockResolvedValueOnce(elevationRequired403())
      .mockResolvedValueOnce({ status: 200, json: async () => ({ ok: true }) })
    vi.stubGlobal('fetch', originalFetch)
    elevateSession.mockResolvedValue({ elevated: true, expiresAt: '2026-01-01T00:00:00Z', ttlSeconds: 600 })

    render(<ElevationPrompt />)
    let resultPromise: Promise<any>
    act(() => {
      resultPromise = fetch('/api/admin/audit')
    })

    fireEvent.change(await screen.findByLabelText('Password'), { target: { value: 'correct horse battery staple' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => expect(elevateSession).toHaveBeenCalledWith('parent-tok', 'correct horse battery staple', undefined))

    const result = await resultPromise!
    expect(result.status).toBe(200)
    expect(originalFetch).toHaveBeenCalledTimes(2)
    await waitFor(() => expect(screen.queryByText('Confirm your password')).toBeNull())
  })

  it('sends the TOTP code when the parent has TOTP enrolled', async () => {
    fetchMfaStatus.mockResolvedValue({
      webauthn_available: false,
      security_keys: [],
      totp_enabled: true,
      recovery_secret: null,
    })
    const originalFetch = vi.fn()
      .mockResolvedValueOnce(elevationRequired403())
      .mockResolvedValueOnce({ status: 200, json: async () => ({ ok: true }) })
    vi.stubGlobal('fetch', originalFetch)
    elevateSession.mockResolvedValue({ elevated: true, expiresAt: '2026-01-01T00:00:00Z', ttlSeconds: 600 })

    render(<ElevationPrompt />)
    act(() => {
      fetch('/api/admin/audit')
    })

    await screen.findByText('Confirm your password')
    const totpField = await screen.findByLabelText('Authenticator code')
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pw' } })
    fireEvent.change(totpField, { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() => expect(elevateSession).toHaveBeenCalledWith('parent-tok', 'pw', '123456'))
  })

  it('shows the server error and stays open on a wrong password', async () => {
    const originalFetch = vi.fn().mockResolvedValue(elevationRequired403())
    vi.stubGlobal('fetch', originalFetch)
    elevateSession.mockRejectedValue(new Error('Password is incorrect'))

    render(<ElevationPrompt />)
    act(() => {
      fetch('/api/admin/audit')
    })

    fireEvent.change(await screen.findByLabelText('Password'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    expect(await screen.findByText('Password is incorrect')).toBeTruthy()
    expect(screen.getByText('Confirm your password')).toBeTruthy()
  })
})

describe('ElevationPrompt — cancelling', () => {
  it('resolves the original call with the unmodified 403 when the parent cancels', async () => {
    const originalFetch = vi.fn().mockResolvedValue(elevationRequired403())
    vi.stubGlobal('fetch', originalFetch)

    render(<ElevationPrompt />)
    let resultPromise: Promise<any>
    act(() => {
      resultPromise = fetch('/api/admin/audit')
    })

    await screen.findByText('Confirm your password')
    fireEvent.click(screen.getByLabelText('Close'))

    const result = await resultPromise!
    expect(result.status).toBe(403)
    expect(elevateSession).not.toHaveBeenCalled()
    expect(originalFetch).toHaveBeenCalledTimes(1)
  })
})

describe('ElevationPrompt — coalescing concurrent calls', () => {
  it('shows exactly one prompt and retries every waiting call once elevated', async () => {
    const originalFetch = vi.fn()
      .mockResolvedValueOnce(elevationRequired403())
      .mockResolvedValueOnce(elevationRequired403())
      .mockResolvedValueOnce({ status: 200, json: async () => ({ which: 1 }) })
      .mockResolvedValueOnce({ status: 200, json: async () => ({ which: 2 }) })
    vi.stubGlobal('fetch', originalFetch)
    elevateSession.mockResolvedValue({ elevated: true, expiresAt: '2026-01-01T00:00:00Z', ttlSeconds: 600 })

    render(<ElevationPrompt />)
    let p1: Promise<any>, p2: Promise<any>
    act(() => {
      p1 = fetch('/api/admin/audit')
      p2 = fetch('/api/admin/license')
    })

    // Only one modal, even though two calls both needed elevation.
    await screen.findByText('Confirm your password')
    expect(fetchMfaStatus).toHaveBeenCalledTimes(1)

    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    const [r1, r2] = await Promise.all([p1!, p2!])
    expect(r1.status).toBe(200)
    expect(r2.status).toBe(200)
    expect(elevateSession).toHaveBeenCalledTimes(1)
    expect(originalFetch).toHaveBeenCalledTimes(4)
  })
})
