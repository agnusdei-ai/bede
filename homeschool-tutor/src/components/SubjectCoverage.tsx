/**
 * Which scheduled subjects are actually getting taught.
 *
 * THIS CARD IS ABOUT THE PLAN, and every choice in it exists to keep it
 * that way. A parent could always see that History had produced nothing;
 * what they could never see was whether History had been *scheduled* and
 * skipped, or simply never scheduled. Those need opposite responses — a
 * conversation versus a calendar — and until now nothing told them apart.
 *
 * The failure mode this is one wrong sentence away from is a card that
 * reads as a report on the child's willingness. So:
 *
 *  - It says when a subject was last TAUGHT, never how the child did in it.
 *    There is no score here, no mastery, no engagement, nothing derived from
 *    the quality of any work.
 *  - "Not yet started" is its own state, distinct from "not lately" — a
 *    subject you haven't got to is not a subject you are neglecting.
 *  - Subjects being kept up are shown too, not just the gaps. A card that
 *    only ever lists problems teaches a parent to dread opening it, and the
 *    honest picture usually includes several subjects going fine.
 *  - The caveat is on the card, not in the docs, because the wrong reading
 *    is the intuitive one.
 */
import { useTranslation } from 'react-i18next'
import { CalendarClock } from 'lucide-react'

import type { SubjectCoverage as SubjectCoverageData } from '../services/api'

function daysLabel(t: ReturnType<typeof useTranslation>['t'], days: number | null): string {
  if (days === null) return t('coverage.notYetStarted')
  if (days === 0) return t('coverage.today')
  return t('coverage.daysAgo', { count: days })
}

export default function SubjectCoverage({
  coverage,
  loading,
  studentName,
}: {
  coverage: SubjectCoverageData | null
  loading: boolean
  studentName: string
}) {
  const { t } = useTranslation()
  if (loading || !coverage || coverage.subjects.length === 0) return null

  const needsAttention = coverage.subjects.filter((s) => s.needs_attention)
  const keptUp = coverage.subjects.filter((s) => !s.needs_attention)

  return (
    <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-6">
      <h2 className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-gray-700">
        <CalendarClock size={15} className="flex-shrink-0 text-navy-500" />
        {t('coverage.title')}
      </h2>
      <p className="mb-3 text-xs text-gray-500">
        {t('coverage.subtitle', { name: studentName, days: coverage.stale_after_days })}
      </p>

      {needsAttention.length > 0 && (
        <ul className="mb-3">
          {needsAttention.map((s) => (
            <li
              key={s.subject}
              className="flex items-baseline justify-between gap-3 border-t border-gray-100 py-2 first:border-t-0"
            >
              <span className="text-xs font-semibold text-navy-700">{s.label}</span>
              <span className="flex-shrink-0 text-xs text-gray-500 tabular-nums">
                {daysLabel(t, s.days_since)}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* Shown as a plain sentence rather than a second list: these need no
          action, and giving them equal visual weight would make the card
          read as a checklist of everything rather than a short prompt. */}
      {keptUp.length > 0 && (
        <p className="mb-3 text-xs text-gray-500">
          {t('coverage.keptUp', { subjects: keptUp.map((s) => s.label).join(', ') })}
        </p>
      )}

      <p className="text-xs text-gray-500">{t('coverage.caveat')}</p>
    </div>
  )
}
