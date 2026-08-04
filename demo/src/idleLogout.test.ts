/**
 * The property that matters most here is a NEGATIVE one: a child listening
 * to Bede read for ten minutes must never be treated as idle. That is the
 * whole reason isSessionBusy exists and the reason the default is 10 minutes
 * rather than the 5 the break timer uses — see idleLogout.ts.
 */
import { describe, expect, it } from 'vitest'

import {
  DEFAULT_IDLE_LOGOUT_MINUTES,
  IDLE_CHECK_INTERVAL_MS,
  IDLE_LOGOUT_CHOICES,
  IDLE_WARNING_MS,
  idleStatus,
  idleTimeoutMs,
  isIdleLogoutEnabled,
  isSessionBusy,
  normalizeIdleMinutes,
} from './idleLogout'

const IDLE = { isStreaming: false, isSpeaking: false, isListening: false, isTranscribing: false }

describe('what counts as activity', () => {
  it('treats a completely quiet session as not busy', () => {
    expect(isSessionBusy(IDLE)).toBe(false)
  })

  it.each([
    ['Bede is streaming a reply', { isStreaming: true }],
    ['Bede is speaking aloud', { isSpeaking: true }],
    ['the mic is listening', { isListening: true }],
    ['a transcript is being made', { isTranscribing: true }],
  ])('counts the session as active while %s', (_label, patch) => {
    expect(isSessionBusy({ ...IDLE, ...patch })).toBe(true)
  })

  it('never expires a session while Bede is speaking, however long the reading runs', () => {
    // The case the whole design exists for: a long narration produces no taps
    // and no keystrokes, and must not be mistaken for an abandoned tab.
    const started = 0
    const twentyMinutesLater = 20 * 60_000
    expect(idleStatus({
      lastActiveAt: started,
      now: twentyMinutesLater,
      minutes: DEFAULT_IDLE_LOGOUT_MINUTES,
      busy: true,
    })).toBe('active')
  })
})

describe('the idle boundary', () => {
  const minutes = 10
  const timeout = idleTimeoutMs(minutes)

  it('is active well inside the window', () => {
    expect(idleStatus({ lastActiveAt: 0, now: 60_000, minutes })).toBe('active')
  })

  it('warns before it expires, never only at the moment of expiry', () => {
    expect(idleStatus({ lastActiveAt: 0, now: timeout - IDLE_WARNING_MS, minutes })).toBe('warning')
    expect(idleStatus({ lastActiveAt: 0, now: timeout - 1, minutes })).toBe('warning')
  })

  it('expires exactly at the timeout, not a tick late', () => {
    expect(idleStatus({ lastActiveAt: 0, now: timeout, minutes })).toBe('expired')
    expect(idleStatus({ lastActiveAt: 0, now: timeout + 5 * 60_000, minutes })).toBe('expired')
  })

  it('leaves a whole check interval inside the warning window', () => {
    // Otherwise the warning could fall between two ticks and a child would be
    // logged out having never been asked whether they were still there.
    expect(IDLE_WARNING_MS).toBeGreaterThan(IDLE_CHECK_INTERVAL_MS)
  })
})

describe('the parent setting', () => {
  it('defaults to 10 minutes', () => {
    expect(DEFAULT_IDLE_LOGOUT_MINUTES).toBe(10)
    expect(IDLE_LOGOUT_CHOICES).toContain(DEFAULT_IDLE_LOGOUT_MINUTES)
  })

  it('is longer than the break-inactivity logout it sits alongside', () => {
    // The break timer (5 minutes, App.tsx) runs when nothing is meant to be
    // happening at all. This one has to leave room for a long quiet reading,
    // so it must never be the stricter of the two by default.
    expect(DEFAULT_IDLE_LOGOUT_MINUTES).toBeGreaterThan(5)
  })

  it('lets a parent turn it off entirely', () => {
    expect(isIdleLogoutEnabled(0)).toBe(false)
    expect(idleStatus({ lastActiveAt: 0, now: 99 * 60_000, minutes: 0 })).toBe('active')
  })

  it('refuses a value that is not on offer, rather than honouring it', () => {
    // A stale or hand-edited sessionStorage value must not become a 1-minute
    // logout that fights ordinary narration.
    expect(normalizeIdleMinutes(1)).toBe(DEFAULT_IDLE_LOGOUT_MINUTES)
    expect(normalizeIdleMinutes(-5)).toBe(DEFAULT_IDLE_LOGOUT_MINUTES)
    expect(normalizeIdleMinutes('nonsense')).toBe(DEFAULT_IDLE_LOGOUT_MINUTES)
    expect(normalizeIdleMinutes(null)).toBe(DEFAULT_IDLE_LOGOUT_MINUTES)
    expect(normalizeIdleMinutes(undefined)).toBe(DEFAULT_IDLE_LOGOUT_MINUTES)
  })

  it('keeps every value a parent can actually pick', () => {
    for (const choice of IDLE_LOGOUT_CHOICES) {
      expect(normalizeIdleMinutes(choice)).toBe(choice)
    }
  })

  it('honours a longer window a parent chose', () => {
    expect(idleStatus({ lastActiveAt: 0, now: 12 * 60_000, minutes: 30 })).toBe('active')
    expect(idleStatus({ lastActiveAt: 0, now: 30 * 60_000, minutes: 30 })).toBe('expired')
  })
})

describe('an unset stored value', () => {
  it('defaults to 10 minutes rather than to "never"', () => {
    // sessionStorage.getItem returns null for a visitor who has never opened
    // the parent menu — which is most of them. Coercing that with Number()
    // first yields 0, a real choice meaning "never log out", so the feature
    // would have been silently off for everyone it was built for.
    expect(normalizeIdleMinutes(sessionStorage.getItem('nothing-stored-here'))).toBe(
      DEFAULT_IDLE_LOGOUT_MINUTES,
    )
    expect(isIdleLogoutEnabled(normalizeIdleMinutes(null))).toBe(true)
  })

  it('still lets an explicit 0 mean never', () => {
    expect(normalizeIdleMinutes(0)).toBe(0)
    expect(normalizeIdleMinutes('0')).toBe(0)
  })
})
