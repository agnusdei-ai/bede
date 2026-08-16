/**
 * One answer to "where is my child", instead of five.
 *
 * WHAT THIS REPLACED. The Progress page rendered five separate
 * `MasterySnapshot` cards — mathematics, composition, phonics, literacy,
 * language exposure — each with its own heading, its own evidence count,
 * its own amber calibration banner, and its own set of bars. They are the
 * same component with a different `subject_area`, so a parent scrolled
 * through five near-identical panels to assemble, in their head, the one
 * picture the page should have shown them.
 *
 * It also made a real sentence impossible to write. PLACEMENT_SPEC.md's D3
 * says placement results should "seed the normal cards" — which is not a
 * coherent thing to say when there is no single picture to seed. This is
 * that picture.
 *
 * THE SHAPE: one row per area, each stating where it stands in a line, each
 * opening to the detail that used to be a whole card. Five lines answer the
 * question; the detail is one tap away rather than five scrolls.
 *
 * WHAT IT DOES NOT DO, carried over from the cards it replaces:
 *
 *  - **No overall score.** There is no roll-up across areas, no composite,
 *    no single number for the child. Each area stands on its own, because
 *    averaging maths against language exposure would invent a quantity that
 *    does not exist and would read as a grade.
 *  - **No ordering by how well they are doing.** Rows sit in a fixed
 *    pedagogical order (foundational first), never sorted by score — a list
 *    that reshuffles as a child improves is a ranking of their own subjects.
 *  - **An area still says plainly when it is not calibrated**, rather than
 *    showing a confident-looking bar built from four observations.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, Compass } from 'lucide-react'

import type { MasteryProfileSummary } from '../types'

export interface MasteryArea {
  key: string
  label: string
  summary: MasteryProfileSummary | null
  /** Already-translated, area-specific "nothing here yet" copy. */
  noDataText: string
  /** Already-translated calibration explanation for this area. */
  calibrationText: string
}

function Bar({ probability, level }: {
  probability: number
  level: MasteryProfileSummary['domains'][number]['level']
}) {
  const color = level === 'secure' ? 'bg-emerald-400' : level === 'developing' ? 'bg-amber-400' : 'bg-red-300'
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${Math.round(probability * 100)}%` }} />
      </div>
      <span className="w-10 shrink-0 text-right text-xs tabular-nums text-gray-500">
        {Math.round(probability * 100)}%
      </span>
    </div>
  )
}

/** The one-line state of an area, shown on its closed row. */
function rowState(
  t: ReturnType<typeof useTranslation>['t'],
  summary: MasteryProfileSummary | null,
): { text: string; tone: 'none' | 'calibrating' | 'ready' } {
  if (!summary) return { text: t('mastery.notStartedYet'), tone: 'none' }
  if (summary.calibration) {
    return {
      text: t('mastery.stillGettingToKnow', { count: summary.evidence_count }),
      tone: 'calibrating',
    }
  }
  const secure = summary.domains.filter((d) => d.level === 'secure').length
  return {
    text: t('mastery.secureOf', { secure, total: summary.domains.length }),
    tone: 'ready',
  }
}

function AreaRow({ area }: { area: MasteryArea }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const state = rowState(t, area.summary)
  const hasDetail = area.summary !== null

  return (
    <li className="border-t border-gray-100 first:border-t-0">
      <button
        type="button"
        onClick={() => hasDetail && setOpen((v) => !v)}
        aria-expanded={hasDetail ? open : undefined}
        disabled={!hasDetail}
        className={`flex w-full items-baseline gap-2 py-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-400 rounded ${
          hasDetail ? 'cursor-pointer hover:bg-gray-50/60' : 'cursor-default'
        }`}
      >
        {hasDetail
          ? (open
            ? <ChevronDown size={13} className="mt-0.5 shrink-0 text-gray-400" aria-hidden="true" />
            : <ChevronRight size={13} className="mt-0.5 shrink-0 text-gray-400" aria-hidden="true" />)
          : <span className="w-[13px] shrink-0" aria-hidden="true" />}
        <span className="flex-1 text-xs font-semibold text-navy-700">{area.label}</span>
        <span
          className={`shrink-0 text-xs tabular-nums ${
            state.tone === 'calibrating' ? 'text-amber-700'
              : state.tone === 'none' ? 'text-gray-400'
              : 'text-gray-500'
          }`}
        >
          {state.text}
        </span>
      </button>

      {open && area.summary && (
        <div className="pb-3 pl-[21px]">
          {area.summary.calibration && (
            <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              {area.calibrationText}
            </p>
          )}
          <div className="mb-3 space-y-2.5">
            {area.summary.domains.map((d) => (
              <div key={d.domain}>
                <p className="mb-1 text-xs font-medium text-gray-600">{d.domain}</p>
                <Bar probability={d.average_probability} level={d.level} />
              </div>
            ))}
          </div>
          {area.summary.gaps.length > 0 && (
            <div className="mb-2">
              <p className="mb-0.5 text-xs font-semibold text-gray-700">{t('progress.gapsToFocusOn')}</p>
              <p className="text-xs text-gray-500">{area.summary.gaps.map((s) => s.label).join(', ')}</p>
            </div>
          )}
          {area.summary.next_steps.length > 0 && (
            <div>
              <p className="mb-0.5 text-xs font-semibold text-gray-700">{t('progress.suggestedNextSteps')}</p>
              <p className="text-xs text-gray-500">{area.summary.next_steps.map((s) => s.label).join(', ')}</p>
            </div>
          )}
        </div>
      )}
    </li>
  )
}

export default function MasteryOverview({
  areas,
  loading,
  studentName,
}: {
  areas: MasteryArea[]
  loading: boolean
  studentName: string
}) {
  const { t } = useTranslation()
  if (loading || areas.length === 0) return null

  const started = areas.filter((a) => a.summary !== null)

  return (
    <div className="rounded-2xl border border-sage-100 bg-white p-6 shadow-sm">
      <h2 className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-gray-700">
        <Compass size={15} className="shrink-0 text-navy-500" />
        {t('mastery.title', { name: studentName })}
      </h2>
      <p className="mb-2 text-xs text-gray-500">{t('mastery.subtitle')}</p>

      <ul>
        {areas.map((area) => <AreaRow key={area.key} area={area} />)}
      </ul>

      {/* Only when nothing has been assessed anywhere. A per-area "not
          started" already says it on its own row, and repeating it under
          the list would read as a complaint about the family. */}
      {started.length === 0 && (
        <p className="mt-3 text-xs text-gray-500">{t('mastery.nothingYet', { name: studentName })}</p>
      )}
    </div>
  )
}
