import { describe, it, expect } from 'vitest'
import {
  licenseUrgency,
  noticeWindowDays,
  termDays,
  MIN_NOTICE_DAYS,
  MAX_NOTICE_DAYS,
  URGENT_DAYS,
} from './licenseUrgency'
import type { LicenseStatus } from '../types'

/**
 * The defect these were written against: `LicenseSettings.tsx` warned at a
 * flat `days_remaining <= 30`, which a 30-day trial satisfies from the minute
 * it is issued. The chip was lit for the entire trial, so it told a parent
 * nothing, and at day 28 it said exactly what it had said on day 0.
 */

function status(partial: Partial<LicenseStatus>): LicenseStatus {
  return {
    ok: true,
    required: true,
    source: 'db',
    problem: null,
    is_expired: false,
    ...partial,
  }
}

/** A license of `term` days with `remaining` days left. */
function term(termLength: number, remaining: number): LicenseStatus {
  const expires = new Date('2026-06-01T00:00:00Z')
  const issued = new Date(expires.getTime() - termLength * 86_400_000)
  return status({
    issued: issued.toISOString().slice(0, 10),
    expires: expires.toISOString().slice(0, 10),
    days_remaining: remaining,
    // The backend derives both from one `expires` date, so a fixture that
    // let these disagree would be testing a payload the API cannot produce.
    is_expired: remaining < 0,
  })
}

describe('termDays', () => {
  it('measures the license term from issue to expiry', () => {
    expect(termDays(term(365, 100))).toBe(365)
    expect(termDays(term(30, 10))).toBe(30)
  })

  it('returns null when either date is missing or unparseable', () => {
    expect(termDays(status({ expires: '2026-06-01', days_remaining: 5 }))).toBeNull()
    expect(termDays(status({ issued: '2026-01-01', days_remaining: 5 }))).toBeNull()
    expect(termDays(status({ issued: 'nonsense', expires: '2026-06-01' }))).toBeNull()
  })
})

describe('noticeWindowDays', () => {
  it('caps an annual membership at the old 30-day window', () => {
    // 10% of 365 is 36.5 — the ceiling keeps today's behaviour unchanged, so
    // nothing about an existing family's card moves.
    expect(noticeWindowDays(term(365, 200))).toBe(MAX_NOTICE_DAYS)
  })

  it('floors a 30-day trial at a week instead of warning from day zero', () => {
    // THE POINT. 10% of 30 is 3 days, which is too little notice to act on,
    // so the floor lifts it to a week — and crucially NOT to 30, which would
    // be the entire trial.
    expect(noticeWindowDays(term(30, 25))).toBe(MIN_NOTICE_DAYS)
    expect(noticeWindowDays(term(30, 25))).toBeLessThan(30)
  })

  it('falls back to the old window when the server sends no issue date', () => {
    // An older API that predates `issued` must keep warning exactly as it
    // did rather than silently going quiet.
    expect(noticeWindowDays(status({ expires: '2026-06-01', days_remaining: 20 }))).toBe(
      MAX_NOTICE_DAYS,
    )
  })
})

describe('licenseUrgency', () => {
  it('says nothing for a trial that has just started', () => {
    // The whole defect, stated as one assertion: day 1 of a 30-day trial.
    expect(licenseUrgency(term(30, 29))).toBe('none')
  })

  it('warns partway through a trial, in time to act', () => {
    expect(licenseUrgency(term(30, 6))).toBe('soon')
  })

  it('escalates in the last few days whatever the term was', () => {
    // URGENT_DAYS is deliberately fixed: the last days before lessons stop
    // are equally short whether the term was a month or a year.
    expect(licenseUrgency(term(30, URGENT_DAYS))).toBe('urgent')
    expect(licenseUrgency(term(365, URGENT_DAYS))).toBe('urgent')
  })

  it('still says nothing early in an annual membership', () => {
    expect(licenseUrgency(term(365, 200))).toBe('none')
  })

  it('warns a month out on an annual membership, as it always did', () => {
    expect(licenseUrgency(term(365, 20))).toBe('soon')
  })

  it('reports an expired license as expired, not merely urgent', () => {
    expect(licenseUrgency(term(30, -1))).toBe('expired')
    expect(licenseUrgency(status({ is_expired: true, days_remaining: -4 }))).toBe('expired')
  })

  it('reads a non-positive day count as expired even without the is_expired flag', () => {
    // `is_expired` is optional on LicenseStatus, so this must not be the only
    // signal consulted. Writing this test is what caught the function
    // trusting it alone and calling a lapsed license merely 'urgent'.
    expect(licenseUrgency(status({ days_remaining: 0 }))).toBe('expired')
    expect(licenseUrgency(status({ days_remaining: -1 }))).toBe('expired')
  })

  it('treats an unusable license as expired even when the dates look fine', () => {
    // A gated instance or a bad key is the most urgent thing on the page
    // regardless of what `expires` says.
    expect(licenseUrgency(status({ ok: false, days_remaining: 200 }))).toBe('expired')
  })

  it('says nothing for a license that never expires', () => {
    expect(licenseUrgency(status({ days_remaining: null }))).toBe('none')
    expect(licenseUrgency(status({}))).toBe('none')
  })
})
