/**
 * The wiring between the idle clock and the explanation.
 *
 * utils/idleTimeout.ts and utils/logoutNotice.ts are both unit-tested on
 * their own, and both pass whether or not AppShell actually calls them —
 * which is the gap this file closes. Mutation-checked: deleting the
 * `setLogoutNotice(notice)` line in AppShell fails these tests, and it
 * failed nothing before they existed.
 */
import { act, cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSessionStore } from '../store/sessionStore'
import { IDLE_TIMEOUT_MS, IDLE_WARNING_MS } from '../utils/idleTimeout'
import { takeLogoutNotice } from '../utils/logoutNotice'
import AppShell from './AppShell'

function renderShell() {
  return render(
    <MemoryRouter>
      <AppShell><div>lesson</div></AppShell>
    </MemoryRouter>,
  )
}

/**
 * Advance both the faked wall clock and the interval timers, then let any
 * promises those callbacks created settle.
 *
 * Deliberately not @testing-library's `waitFor`: it polls on REAL timers, so
 * under `vi.useFakeTimers()` it never gets a second look and just times out
 * after five seconds. Everything asserted here settles inside this act()
 * instead, so the assertions can be plain and immediate.
 */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

/** Let mount-time promises (the initial token validation) resolve. */
async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
}

beforeEach(() => {
  sessionStorage.clear()
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200 }) as unknown as Response))
  useSessionStore.setState({ token: 'live-token', role: 'child', isStreaming: false, voiceActive: false })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  useSessionStore.setState({ token: null, role: null, isStreaming: false, voiceActive: false })
})

describe('being signed out for sitting still', () => {
  it('records a reason the login screen can show', async () => {
    // The whole point. Before this, the session vanished and the login page
    // appeared with no explanation at all.
    renderShell()
    await advance(IDLE_TIMEOUT_MS + 1000)

    expect(useSessionStore.getState().token).toBe(null)
    expect(takeLogoutNotice()).toBe('inactivity')
  })

  it('warns before it acts, and the warning is not the logout', async () => {
    renderShell()
    await advance(IDLE_TIMEOUT_MS - IDLE_WARNING_MS + 1000)

    expect(screen.queryByRole('status')).not.toBeNull()
    // Still signed in — a warning that logs you out is not a warning.
    expect(useSessionStore.getState().token).toBe('live-token')
    expect(takeLogoutNotice()).toBe(null)
  })

  it('does nothing at all while the session is well inside the window', async () => {
    renderShell()
    await advance(IDLE_TIMEOUT_MS / 2)

    expect(screen.queryByRole('status')).toBeNull()
    expect(useSessionStore.getState().token).toBe('live-token')
    expect(takeLogoutNotice()).toBe(null)
  })
})

describe('listening to Bede is not being idle', () => {
  it('does not sign a child out mid-passage', async () => {
    // A child sitting still while Bede reads produces no input events. That
    // used to be indistinguishable from an abandoned tab.
    renderShell()
    useSessionStore.setState({ voiceActive: true })
    await advance(IDLE_TIMEOUT_MS + 1000)

    expect(useSessionStore.getState().token).toBe('live-token')
    expect(takeLogoutNotice()).toBe(null)
  })

  it('does not sign a parent out while a reply is still streaming', async () => {
    renderShell()
    useSessionStore.setState({ isStreaming: true })
    await advance(IDLE_TIMEOUT_MS + 1000)

    expect(useSessionStore.getState().token).toBe('live-token')
    expect(takeLogoutNotice()).toBe(null)
  })

  it('starts the full window over once Bede stops, rather than resuming a countdown', async () => {
    renderShell()
    useSessionStore.setState({ voiceActive: true })
    await advance(IDLE_TIMEOUT_MS + 1000)
    useSessionStore.setState({ voiceActive: false })

    // Half a window after a long reading: nowhere near expiry, because the
    // clock restarted rather than resuming from under the reading.
    await advance(IDLE_TIMEOUT_MS / 2)
    expect(useSessionStore.getState().token).toBe('live-token')

    // And it does still expire eventually — this is a reset, not an exemption.
    await advance(IDLE_TIMEOUT_MS)
    expect(useSessionStore.getState().token).toBe(null)
    expect(takeLogoutNotice()).toBe('inactivity')
  })
})

describe('a token the server no longer accepts', () => {
  it('is explained differently from walking away', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401 }) as unknown as Response))
    renderShell()
    await flush()

    expect(useSessionStore.getState().token).toBe(null)
    expect(takeLogoutNotice()).toBe('session-expired')
  })
})
