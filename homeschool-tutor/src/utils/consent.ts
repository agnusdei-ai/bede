import type { HouseholdConsent } from '../services/api'

/**
 * Whether the parent must tick the consent box for a pod save to go through:
 * when the server says consent is outstanding OR the consent lookup failed.
 * Unknown state must not silently allow a student configuration save; the
 * consent checkbox is unavailable until the current notice can be fetched.
 * A family that agreed at install time never sees the box. A first pod or
 * newly added child needs acknowledgement unless covered by the install ack.
 */
export function tickRequiredToSave(consent: HouseholdConsent | null, proposedStudentNames: string[] = []): boolean {
  if (consent === null || consent.needs_consent) return true
  if (consent.install_ack) return false

  // The household status lists only students already configured on the server.
  // A first pod or newly added child must not inherit another child's consent.
  const covered = new Set(consent.students
    .filter((student) => student.consented && !student.stale)
    .map((student) => student.student_name))
  return proposedStudentNames.some((name) => name.trim() !== '' && !covered.has(name.trim()))
}

/** True when at least one child agreed to an earlier version of the notice. */
export function noticeChanged(consent: HouseholdConsent): boolean {
  return consent.students.some((s) => s.stale)
}
