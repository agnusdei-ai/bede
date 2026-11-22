import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'

/** The three steps every K-2 practice routine shares. */
export type RoutineStep = 'watch' | 'together' | 'your_turn'
export const ROUTINE_STEPS: RoutineStep[] = ['watch', 'together', 'your_turn']

/**
 * The shared frame for a Watch, Together, Your turn practice: a full-screen
 * sheet with the three steps shown at the top and a way back to Bede that is
 * always there. It holds no lesson logic, so each practice (maps first) only
 * supplies what goes inside.
 */
export default function RoutineShell({
  title, step, done = false, onClose, children,
}: {
  title: string
  step: RoutineStep
  done?: boolean
  onClose: () => void
  children: ReactNode
}) {
  const { t } = useTranslation()
  const current = ROUTINE_STEPS.indexOf(step)
  return (
    <div
      role="dialog" aria-modal="true" aria-label={title}
      className="fixed inset-0 z-40 flex flex-col bg-parchment-50"
    >
      {/* Two rows on a phone: the title and the way back, then the steps.
          The right padding keeps everything clear of the floating text-size
          button (TextSizeControl, fixed top-right), which used to sit on top
          of the last step. */}
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1 pl-3 pr-16 sm:pl-4 py-2 short:py-1 border-b border-sage-200 bg-white">
        <h2 className="order-1 min-w-0 flex-1 truncate text-base font-semibold text-navy-700">{title}</h2>
        <ol className="order-3 flex w-full flex-wrap items-center gap-1.5 sm:order-2 sm:w-auto" aria-label={t('routine.steps')}>
          {ROUTINE_STEPS.map((s, i) => {
            const state = done || i < current ? 'past' : i === current ? 'now' : 'next'
            return (
              <li
                key={s}
                aria-current={state === 'now' ? 'step' : undefined}
                className={`rounded-full px-2 sm:px-3 py-1 text-xs font-medium whitespace-nowrap ${
                  state === 'now' ? 'bg-navy-700 text-white'
                    : state === 'past' ? 'bg-sage-100 text-sage-700'
                      : 'bg-gray-100 text-gray-500'
                }`}
              >
                {t(`routine.step.${s}`)}
              </li>
            )
          })}
        </ol>
        <button
          type="button" onClick={onClose} aria-label={t('routine.back')} title={t('routine.back')}
          className="order-2 min-h-14 min-w-14 flex items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 sm:order-3"
        >
          <X size={20} />
        </button>
      </header>
      <div className="flex-1 overflow-auto px-4 py-4 short:py-2">
        <div className="mx-auto max-w-xl flex flex-col items-center gap-4">{children}</div>
      </div>
    </div>
  )
}
