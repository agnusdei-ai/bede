import type { SessionConfig, Subject } from '../types'

/**
 * Create a parent-approved, single-subject teaching session from the
 * existing plan. This is a SESSION-ONLY copy: it never writes to the
 * student's saved daily schedule or adds a subject the parent didn't choose.
 *
 * The full config is preserved for privacy, language, accessibility,
 * constitutional boundaries, and term outcomes. Resume notes for unrelated
 * subjects are omitted so Bede doesn't mistake them for today's work.
 */
export function prepareFocusedLesson(
  existing: SessionConfig,
  subject: Subject,
  parentFocus: string,
): SessionConfig | null {
  if (!existing.subjects.includes(subject)) return null

  const focus = parentFocus.trim().slice(0, 300)
  return {
    ...existing,
    subjects: [subject],
    lesson_focus: focus || undefined,
    lesson_resume: existing.lesson_resume?.filter((note) => note.subject === subject),
  }
}
