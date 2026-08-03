/**
 * The pod roster — who has done which work, so a parent can arrange one of
 * their students to help another.
 *
 * THIS COMPONENT IS DESIGNED AGAINST BECOMING A LEADERBOARD, and that
 * constraint drove every layout decision in it. The backend already
 * refuses to emit a ranking (services/diagnostic/activity.pod_activity: no
 * per-student total, no ordering by any measure, absent rather than zero).
 * But a UI can reintroduce a ranking that the data doesn't contain, simply
 * by choosing the wrong shape — so:
 *
 *  - **Grouped by SKILL, never by student.** A list of children with
 *    numbers beside them reads as a table of who is ahead, whatever the
 *    numbers mean. A list of skills, each naming who has worked it, reads
 *    as what it is: a roster.
 *  - **No student totals anywhere**, not even derived in the client. The
 *    moment a child has one number standing for them, they can be ordered
 *    by it.
 *  - **Alphabetical within each skill**, matching the API. The order must
 *    not shift when the counts do, because a moving order IS a ranking.
 *  - **No bars, no "most", no highlighting of the highest count.** Counts
 *    are rendered identically regardless of size.
 *  - **A child who hasn't done a skill is absent from it**, never shown at
 *    zero beside a sibling. That is the API's behavior and the UI must not
 *    "helpfully" fill the gap back in.
 *
 * Parent-facing only. This is never rendered in a child session — a child
 * who can see they are behind a sibling has been ranked whatever we call
 * the component.
 */
import { useTranslation } from 'react-i18next'
import { Users } from 'lucide-react'

import type { PodWorkRoster as PodWorkRosterData } from '../types'

export default function PodWorkRoster({
  roster,
  loading,
}: {
  roster: PodWorkRosterData | null
  loading: boolean
}) {
  const { t } = useTranslation()
  if (loading) return null

  if (!roster || roster.skills.length === 0) {
    return (
      <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-1.5">{t('podRoster.title')}</h2>
        <p className="text-xs text-gray-500">{t('podRoster.noData')}</p>
      </div>
    )
  }

  // Only skills more than one student has worked are useful for pairing —
  // a skill only one child has touched has nobody to pair them with. Shown
  // separately rather than filtered away entirely, so the parent still sees
  // the whole record.
  const pairable = roster.skills.filter((s) => s.worked_by.length > 1)
  const soloOnly = roster.skills.filter((s) => s.worked_by.length === 1)

  return (
    <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-6">
      <h2 className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-gray-700">
        <Users size={15} className="flex-shrink-0 text-navy-500" />
        {t('podRoster.title')}
      </h2>
      <p className="mb-4 text-xs text-gray-500">{t('podRoster.subtitle')}</p>

      {pairable.length > 0 && (
        <ul className="mb-4">
          {pairable.map((skill) => (
            <li key={`${skill.subject_area}:${skill.skill_id}`} className="border-t border-gray-100 py-3 first:border-t-0">
              <p className="text-xs font-semibold text-navy-700">{skill.label}</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {/* Rendered identically regardless of count — no emphasis
                    on the largest, no ordering by it. */}
                {skill.worked_by.map((w) => (
                  <span
                    key={w.student_name}
                    className="inline-flex items-baseline gap-1 rounded-lg bg-sage-50 px-2 py-0.5 text-xs text-sage-800"
                  >
                    <span className="font-medium">{w.student_name}</span>
                    <span className="tabular-nums text-sage-600">
                      {t('podRoster.completedShort', { count: w.completed })}
                    </span>
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}

      {soloOnly.length > 0 && (
        <div className="rounded-xl bg-gray-50 px-3 py-2">
          <p className="mb-1 text-xs font-semibold text-gray-600">{t('podRoster.workedByOne')}</p>
          <p className="text-xs text-gray-500">
            {soloOnly
              .map((s) => `${s.label} (${s.worked_by[0].student_name})`)
              .join(', ')}
          </p>
        </div>
      )}

      <p className="mt-3 text-xs text-gray-500">{t('podRoster.caveat')}</p>
    </div>
  )
}
