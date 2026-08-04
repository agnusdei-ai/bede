/**
 * The property under test is ONE-SHOT-NESS. Everything else here is small;
 * the thing that would actually hurt someone is a notice that either never
 * appears (they're back at a login screen with no explanation, which is the
 * bug this module exists to fix) or appears twice (accusing them of walking
 * away from a session they just signed into).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import en from '../i18n/locales/en.json'
import es from '../i18n/locales/es.json'
import {
  LOGOUT_NOTICE_KEYS,
  setLogoutNotice,
  takeLogoutNotice,
  type LogoutReason,
} from './logoutNotice'

const ALL_REASONS: LogoutReason[] = ['inactivity', 'break-inactivity', 'session-expired']

beforeEach(() => {
  sessionStorage.clear()
  vi.restoreAllMocks()
})

describe('a notice survives exactly one read', () => {
  it('round-trips the reason that was recorded', () => {
    setLogoutNotice('inactivity')
    expect(takeLogoutNotice()).toBe('inactivity')
  })

  it('is gone on the second read', () => {
    // The one that matters: signing back in must not re-show "you were
    // logged out for being idle" over a session that just started.
    setLogoutNotice('inactivity')
    takeLogoutNotice()
    expect(takeLogoutNotice()).toBe(null)
  })

  it('returns null when nothing was recorded', () => {
    expect(takeLogoutNotice()).toBe(null)
  })

  it('keeps the most recent reason when two are recorded before a read', () => {
    setLogoutNotice('inactivity')
    setLogoutNotice('session-expired')
    expect(takeLogoutNotice()).toBe('session-expired')
  })

  it.each(ALL_REASONS)('round-trips %s', (reason) => {
    setLogoutNotice(reason)
    expect(takeLogoutNotice()).toBe(reason)
  })
})

describe('a value this build does not recognise', () => {
  it('reads as no notice rather than as a raw i18n key on screen', () => {
    sessionStorage.setItem('bede-logout-notice', 'something-from-an-older-tab')
    expect(takeLogoutNotice()).toBe(null)
  })

  it('is still cleared, so it cannot be retried forever', () => {
    sessionStorage.setItem('bede-logout-notice', 'nonsense')
    takeLogoutNotice()
    expect(sessionStorage.getItem('bede-logout-notice')).toBe(null)
  })
})

describe('storage that throws', () => {
  // Safari private browsing, a full quota, a locked-down webview. A missing
  // explanation is a worse login screen; a logout that fails to happen is a
  // security problem. This module must never be the second one.
  it('does not throw when writing is refused', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError')
    })
    expect(() => setLogoutNotice('inactivity')).not.toThrow()
  })

  it('does not throw when reading is refused', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('SecurityError')
    })
    expect(() => takeLogoutNotice()).not.toThrow()
    expect(takeLogoutNotice()).toBe(null)
  })
})

describe('every reason can actually be rendered', () => {
  // Without this, adding a reason and forgetting its string would print the
  // literal key "common.loggedOutWhatever" at whoever was just signed out.
  it.each(ALL_REASONS)('has an i18n key for %s', (reason) => {
    expect(LOGOUT_NOTICE_KEYS[reason]).toBeTruthy()
  })

  it.each(ALL_REASONS)('has a real English string for %s', (reason) => {
    const value = LOGOUT_NOTICE_KEYS[reason]
      .split('.')
      .reduce<any>((o, k) => o?.[k], en)
    expect(typeof value).toBe('string')
    expect(value.trim().length).toBeGreaterThan(0)
  })

  it.each(ALL_REASONS)('has a real Spanish string for %s', (reason) => {
    const value = LOGOUT_NOTICE_KEYS[reason]
      .split('.')
      .reduce<any>((o, k) => o?.[k], es)
    expect(typeof value).toBe('string')
    expect(value.trim().length).toBeGreaterThan(0)
  })
})
