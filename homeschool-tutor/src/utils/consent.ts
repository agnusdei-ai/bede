import type { HouseholdConsent } from '../services/api'

/**
 * Whether the parent must tick the consent box for a pod save to go through:
 * when the server says consent is outstanding OR the consent lookup failed.
 * Unknown state must not silently allow a student configuration save; the
 * consent checkbox is unavailable until the current notice can be fetched.
 * A family that agreed at install time never sees the box.
 */
export function tickRequiredToSave(consent: HouseholdConsent | null): boolean {
  return consent === null || consent.needs_consent
}

/** True when at least one child agreed to an earlier version of the notice. */
export function noticeChanged(consent: HouseholdConsent): boolean {
  return consent.students.some((s) => s.stale)
}
