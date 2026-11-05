import { useTranslation } from 'react-i18next'
import type { ProgressState } from './readingProgress'

/** The Practice Coach's reading progress: a bar, its percentage, and what is happening now. */
export default function ReadingProgressBar({ state }: { state: ProgressState | null }) {
  const { t } = useTranslation()
  if (!state) return null
  let label = t(`readingProgress.${state.stage}`)
  if (state.stage === 'reading' && state.total) label = t('readingProgress.read', { done: state.done, total: state.total })
  if (state.parts > 1) label += ` ${t('readingProgress.part', { part: state.part, parts: state.parts })}`
  return (
    <div className="space-y-1" aria-live="polite">
      <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={state.percent}
        aria-label={t('readingProgress.label')} className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
        <div className="h-full rounded-full bg-navy-700 transition-all duration-500" style={{ width: `${Math.max(3, state.percent)}%` }} />
      </div>
      <p className="text-xs text-gray-600">{state.percent}% · {label}</p>
    </div>
  )
}
