/**
 * How close a license is to leaving a family without Bede — sized against
 * that license's own TERM, not a fixed number of days.
 *
 * `LicenseSettings.tsx` used one threshold: `days_remaining <= 30`. That is a
 * sensible notice period for a 365-day membership and it is **noise for a
 * short-dated key**. A 30-day trial satisfies it from the minute it is
 * issued, so the card reads "needs attention" for the entire trial, the
 * parent learns the chip means nothing, and at day 28 — the one moment it
 * matters — it says exactly what it has said all along.
 *
 * So the rule is proportional: warn inside 10% of the term, with a floor of
 * `MIN_NOTICE_DAYS` (a week is the least notice that lets anyone act) and a
 * ceiling of `MAX_NOTICE_DAYS` (beyond a month, a renewal is not yet news).
 *
 *   365-day membership -> 36.5, capped to 30   (today's behaviour, unchanged)
 *   30-day trial       -> 3, floored to 7      (warns at day 23, not day 0)
 *   60-day key         -> 6, floored to 7
 *
 * `urgent` is deliberately separate from `soon`: it is what justifies opening
 * the card on arrival rather than leaving a chip to be noticed, and it is
 * fixed at `URGENT_DAYS` regardless of term, because the last few days before
 * a lesson stops working are equally short whatever the term was.
 *
 * A pure function with no I/O, following `utils/masteryCycle.ts`'s precedent,
 * so a test states a situation rather than building one.
 */
import type { LicenseStatus } from '../types'

export const MIN_NOTICE_DAYS = 7
export const MAX_NOTICE_DAYS = 30
export const URGENT_DAYS = 3
export const NOTICE_FRACTION_OF_TERM = 0.1

export type LicenseUrgency = 'none' | 'soon' | 'urgent' | 'expired'

/** Days between `issued` and `expires`, or null when either is absent. */
export function termDays(status: LicenseStatus): number | null {
  if (!status.issued || !status.expires) return null
  const issued = Date.parse(status.issued)
  const expires = Date.parse(status.expires)
  if (Number.isNaN(issued) || Number.isNaN(expires)) return null
  const days = Math.round((expires - issued) / 86_400_000)
  return days > 0 ? days : null
}

/**
 * How many days before expiry this license should start warning.
 *
 * Falls back to `MAX_NOTICE_DAYS` when the term is unknown, which is the
 * pre-existing behaviour: an older server that does not send `issued` keeps
 * warning exactly as it did rather than silently stopping.
 */
export function noticeWindowDays(status: LicenseStatus): number {
  const term = termDays(status)
  if (term === null) return MAX_NOTICE_DAYS
  const proportional = Math.round(term * NOTICE_FRACTION_OF_TERM)
  return Math.min(MAX_NOTICE_DAYS, Math.max(MIN_NOTICE_DAYS, proportional))
}

export function licenseUrgency(status: LicenseStatus): LicenseUrgency {
  // An unusable license is already the most urgent thing on the page,
  // whatever the dates say — this covers a bad key and a gated instance,
  // not only an expired one.
  if (!status.ok || status.is_expired) return 'expired'

  const remaining = status.days_remaining
  if (remaining === null || remaining === undefined) return 'none'
  // A day count at or below zero IS expired, independent of `is_expired`.
  // The backend derives both from one date so they agree in practice, but
  // `is_expired` is optional on this type — so trusting it alone would let a
  // payload that omits it report an expired license as merely `urgent`. The
  // two signals are checked separately rather than one being assumed from
  // the other.
  if (remaining <= 0) return 'expired'
  if (remaining <= URGENT_DAYS) return 'urgent'
  if (remaining <= noticeWindowDays(status)) return 'soon'
  return 'none'
}
