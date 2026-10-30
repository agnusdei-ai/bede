import type { HouseholdConsent } from '../services/api'

/**
 * Whether the parent must tick the consent box for a pod save to go through:
 * exactly when the server says consent is outstanding. A family that agreed
 * at install time never sees the box.
 */
export function tickRequiredToSave(consent: HouseholdConsent | null): boolean {
  return !!consent && consent.needs_consent
}

/** True when at least one child agreed to an earlier version of the notice. */
export function noticeChanged(consent: HouseholdConsent): boolean {
  return consent.students.some((s) => s.stale)
}
