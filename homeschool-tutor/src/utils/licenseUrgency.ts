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
 *   7-day trial        -> 1, floored to 3      (warns at day 4, not day 0)
 *
 * **That last row is a fix, not an extra example.** Decision 36 cut the
 * trial from 30 days to 7, and a floor of `MIN_NOTICE_DAYS` (7) is then equal
 * to the entire term: `days_remaining` is 7 on the issue date, so the card
 * read "needs attention" from the minute the trial started and opened itself
 * on arrival — precisely the defect described above, reintroduced by a shorter
 * term rather than by a flat threshold. A floor can only ever be a floor while
 * it is smaller than the term it floors.
 *
 * So when the term is no longer than `MIN_NOTICE_DAYS`, the floor becomes
 * `URGENT_DAYS` — itself clamped to `term - 1`, because `URGENT_DAYS` (3) is
 * no more a floor for a three-day key than seven was for a seven-day one. On a one-week trial that is the honest shape: there
 * is no relaxed heads-up phase to have, and every day on which the warning
 * appears is a day to act — so `soon` simply never fires for such a term and
 * `urgent` covers the last three days. Nothing at 14 days or above moves.
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

/** At or below this term, `MIN_NOTICE_DAYS` would be >= the whole term and so
 * could not act as a floor at all; `URGENT_DAYS` is used instead. Equal to
 * `MIN_NOTICE_DAYS` rather than a second tunable number, because that IS the
 * condition — a floor stops being one exactly when it reaches the term. */
export const SHORT_TERM_DAYS = MIN_NOTICE_DAYS

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
  // The floor must stay strictly below the term, or it stops being a floor and
  // the card warns from day zero again. `URGENT_DAYS` is small enough for a
  // week but not for a three-day key, so it is itself clamped to `term - 1`.
  // At a term of 1 there is no silent day to leave and warning immediately is
  // the correct answer rather than a defect.
  const floor =
    term <= SHORT_TERM_DAYS ? Math.max(1, Math.min(URGENT_DAYS, term - 1)) : MIN_NOTICE_DAYS
  return Math.min(MAX_NOTICE_DAYS, Math.max(floor, proportional))
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
