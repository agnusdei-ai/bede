/**
 * The work ledger — what a student has actually DONE.
 *
 * Sits next to the mastery snapshots on the Progress page and deliberately
 * looks different from them, because it means something different. A
 * mastery snapshot renders probability bars: an inference about the child.
 * This renders counts and dates: a record of events. Giving the two the
 * same visual language would blur exactly the distinction the backend went
 * to some trouble to preserve (see services/diagnostic/activity.py).
 *
 * Three rules this component follows, each mirroring one the API already
 * enforces:
 *
 *  1. No bars, percentages, or progress rings. Those read as "how far
 *     along is my child", which is the mastery card's job. Here the honest
 *     visual is a count.
 *  2. Unscored work is shown as unscored, never as zero. A dimension Bede
 *     didn't observe is a blank, and a blank must not look like a low mark.
 *  3. Nothing is averaged. Distributions are rendered as the counts they
 *     are.
 */
import { useTranslation } from 'react-i18next'
import { CheckCircle2, Sparkles } from 'lucide-react'

import type { WorkLedger as WorkLedgerData, WorkLedgerSkill } from '../types'

/** A small count chip. Muted when zero, so a zero reads as "none of this"
 *  rather than as a result worth looking at. */
function Count({ n, label }: { n: number; label: string }) {
  return (
    <span
      className={`inline-flex items-baseline gap-1 rounded-lg px-2 py-0.5 text-xs ${
        n > 0 ? 'bg-sage-50 text-sage-800' : 'bg-gray-50 text-gray-400'
      }`}
    >
      <span className="font-semibold tabular-nums">{n}</span>
      <span>{label}</span>
    </span>
  )
}

function SkillRow({ skill }: { skill: WorkLedgerSkill }) {
  const { t } = useTranslation()
  const unscored = skill.completed - skill.scored

  return (
    <li className="border-t border-gray-100 py-3 first:border-t-0">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-xs font-semibold text-navy-700">{skill.label}</p>
        <span className="flex-shrink-0 text-xs text-gray-400 tabular-nums">
          {t('workLedger.completedCount', { count: skill.completed })}
        </span>
      </div>

      <div className="mt-1.5 flex flex-wrap gap-1.5">
        <Count n={skill.unaided} label={t('workLedger.unaided')} />
        <Count n={skill.with_a_hint} label={t('workLedger.withAHint')} />
        <Count n={skill.with_help} label={t('workLedger.withHelp')} />
      </div>

      {skill.scored > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {skill.quality.exemplary > 0 && (
            <Count n={skill.quality.exemplary} label={t('workLedger.exemplary')} />
          )}
          {skill.distinction.noteworthy > 0 && (
            <Count n={skill.distinction.noteworthy} label={t('workLedger.noteworthy')} />
          )}
          {skill.distinction.original > 0 && (
            <Count n={skill.distinction.original} label={t('workLedger.original')} />
          )}
          {skill.speed.brisk > 0 && (
            <Count n={skill.speed.brisk} label={t('workLedger.brisk')} />
          )}
        </div>
      )}

      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-400">
        {skill.last_worked && (
          <span>
            {t('workLedger.lastWorked', {
              date: new Date(skill.last_worked).toLocaleDateString(),
            })}
          </span>
        )}
        {/* Unscored work is stated, not hidden and not rendered as a zero
            mark — a blank has to stay visibly different from a low one. */}
        {unscored > 0 && <span>{t('workLedger.notYetScored', { count: unscored })}</span>}
      </div>
    </li>
  )
}

/**
 * The initiative panel. Counts only — no badge, no threshold, no verdict.
 * Whether a child is a "learning entrepreneur" is not a call this software
 * makes; it counts the evidence and the parent reads it.
 */
function InitiativePanel({ ledger }: { ledger: WorkLedgerData }) {
  const { t } = useTranslation()
  const s = ledger.initiative
  if (s.scored_activities === 0) return null

  return (
    <div className="mt-4 rounded-xl border border-navy-100 bg-navy-50/60 p-4">
      <div className="mb-2 flex items-center gap-1.5">
        <Sparkles size={14} className="flex-shrink-0 text-navy-500" />
        <h3 className="text-xs font-semibold text-navy-800">{t('workLedger.initiativeTitle')}</h3>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Count n={s.exemplary} label={t('workLedger.exemplary')} />
        <Count n={s.beyond_the_task} label={t('workLedger.beyondTheTask')} />
        <Count n={s.brisk} label={t('workLedger.brisk')} />
      </div>
      {s.standout_skills.length > 0 && (
        <p className="mt-2 text-xs text-gray-600">
          {t('workLedger.standoutIn', {
            skills: s.standout_skills.map((k) => k.label).join(', '),
          })}
        </p>
      )}
      <p className="mt-2 text-xs text-gray-500">{t('workLedger.initiativeCaveat')}</p>
    </div>
  )
}

export default function WorkLedger({
  ledger,
  loading,
  studentName,
}: {
  ledger: WorkLedgerData | null
  loading: boolean
  studentName: string
}) {
  const { t } = useTranslation()
  if (loading) return null

  if (!ledger || ledger.total === 0) {
    return (
      <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-1.5">{t('workLedger.title')}</h2>
        <p className="text-xs text-gray-500">{t('workLedger.noData', { name: studentName })}</p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-6">
      <div className="mb-1 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-gray-700">
          <CheckCircle2 size={15} className="flex-shrink-0 text-sage-600" />
          {t('workLedger.title')}
        </h2>
        <span className="flex-shrink-0 text-xs text-gray-400 tabular-nums">
          {t('workLedger.totalCompleted', { count: ledger.total })}
        </span>
      </div>
      <p className="mb-3 text-xs text-gray-500">
        {t('workLedger.subtitle', { days: ledger.since_days })}
      </p>

      <ul className="mb-1">
        {ledger.skills.map((skill) => (
          <SkillRow key={`${skill.subject_area}:${skill.skill_id}`} skill={skill} />
        ))}
      </ul>

      <InitiativePanel ledger={ledger} />
    </div>
  )
}
