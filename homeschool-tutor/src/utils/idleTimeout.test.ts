import { describe, expect, it } from 'vitest'

import {
  IDLE_CHECK_INTERVAL_MS,
  IDLE_TIMEOUT_MS,
  IDLE_WARNING_MS,
  idleStatus,
  isSessionBusy,
} from './idleTimeout'

const QUIET = { isStreaming: false, voiceActive: false }

describe('what counts as activity', () => {
  it('treats a fully quiet session as not busy', () => {
    expect(isSessionBusy(QUIET)).toBe(false)
  })

  it.each([
    ['Bede is streaming a reply', { isStreaming: true }],
    ['Bede is speaking, or the mic is live', { voiceActive: true }],
  ])('counts the session as active while %s', (_label, patch) => {
    expect(isSessionBusy({ ...QUIET, ...patch })).toBe(true)
  })

  it('never expires a session while Bede is reading aloud, however long', () => {
    // The flaw this closes: AppShell reset only on input events, so a child
    // sitting still through a long passage looked exactly like an abandoned
    // tab. Being logged out mid-lesson costs a real family a re-login.
    expect(idleStatus({
      lastActiveAt: 0,
      now: IDLE_TIMEOUT_MS * 3,
      busy: true,
    })).toBe('active')
  })
})

describe('the boundary', () => {
  it('is active well inside the window', () => {
    expect(idleStatus({ lastActiveAt: 0, now: 60_000 })).toBe('active')
  })

  it('warns before expiring, never only at the moment of expiry', () => {
    expect(idleStatus({ lastActiveAt: 0, now: IDLE_TIMEOUT_MS - IDLE_WARNING_MS })).toBe('warning')
    expect(idleStatus({ lastActiveAt: 0, now: IDLE_TIMEOUT_MS - 1 })).toBe('warning')
  })

  it('expires exactly at the timeout', () => {
    expect(idleStatus({ lastActiveAt: 0, now: IDLE_TIMEOUT_MS })).toBe('expired')
  })

  it('leaves several checks inside the warning window', () => {
    // Otherwise the warning could fall between two samples and a child would
    // be logged out having never been asked whether they were still there.
    expect(IDLE_WARNING_MS).toBeGreaterThan(IDLE_CHECK_INTERVAL_MS * 3)
  })
})

describe('the window itself', () => {
  it('is unchanged at 30 minutes', () => {
    // Deliberately not shortened. This is session-wide and covers reading and
    // thinking time; tightening it is a product decision, not a side effect
    // of making it count the right things.
    expect(IDLE_TIMEOUT_MS).toBe(30 * 60 * 1000)
  })

  it('honours a caller-supplied window without changing the default', () => {
    expect(idleStatus({ lastActiveAt: 0, now: 5000, timeoutMs: 4000 })).toBe('expired')
    expect(idleStatus({ lastActiveAt: 0, now: 5000 })).toBe('active')
  })
})
