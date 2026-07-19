import { useTranslation } from 'react-i18next'
import { Mic, PenLine, Coffee, Sparkles, ShieldAlert } from 'lucide-react'
import type { GradeStage } from '../types'

/**
 * A one-time, skippable introduction shown before a child's very first
 * session ever (see useMeetBede.ts — gated per student, per device).
 * Answers a real gap: previously a child's first-ever login went straight
 * from voice verification into a live turn with Bede, no explanation of
 * what's about to happen, how the press-and-hold mic works, or what a
 * lesson looks like — the app's own docs/CHILD_GUIDE.md already explains
 * all of this warmly, it just never reached the child. This is that
 * content, condensed and componentized for the screen rather than a
 * markdown file a parent has to find and relay.
 */
export default function MeetBede({
  studentName, gradeStage, onDone,
}: {
  studentName: string
  gradeStage: GradeStage
  onDone: () => void
}) {
  const { t } = useTranslation()
  const fontClass = gradeStage === 'K-2' ? 'text-lg' : 'text-base'

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-parchment-50 p-4 overflow-y-auto">
      <div className="bg-white rounded-2xl border border-sage-200 shadow-xl p-6 sm:p-8 max-w-md w-full my-auto">
        <div className="text-center mb-5">
          <img
            src="/bede-portrait.webp"
            alt="Bede"
            className="w-24 h-24 rounded-full object-cover object-top mx-auto mb-3 shadow-md"
          />
          <h1 className={`font-display font-bold text-gray-800 ${gradeStage === 'K-2' ? 'text-2xl' : 'text-xl'}`}>
            {t('meetBede.title', { name: studentName })}
          </h1>
          <p className={`text-gray-500 mt-1 ${fontClass}`}>{t('meetBede.subtitle')}</p>
        </div>

        <ul className={`space-y-3.5 text-gray-700 mb-5 ${fontClass}`}>
          <li className="flex gap-3">
            <Sparkles size={20} className="text-sage-600 shrink-0 mt-0.5" />
            <span>{t('meetBede.pointQuestions')}</span>
          </li>
          <li className="flex gap-3">
            <Mic size={20} className="text-sage-600 shrink-0 mt-0.5" />
            <span>{t('meetBede.pointMic')}</span>
          </li>
          <li className="flex gap-3">
            <PenLine size={20} className="text-sage-600 shrink-0 mt-0.5" />
            <span>{t('meetBede.pointPencil')}</span>
          </li>
          <li className="flex gap-3">
            <Coffee size={20} className="text-sage-600 shrink-0 mt-0.5" />
            <span>{t('meetBede.pointBreaks')}</span>
          </li>
        </ul>

        <div className={`flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 mb-5 text-amber-800 ${gradeStage === 'K-2' ? 'text-sm' : 'text-xs'}`}>
          <ShieldAlert size={16} className="flex-shrink-0 mt-0.5" />
          <p>{t('meetBede.safetyNote')}</p>
        </div>

        <button
          onClick={onDone}
          className="w-full py-3.5 bg-navy-500 text-white rounded-xl font-semibold text-base hover:bg-navy-600 transition-colors"
        >
          {t('meetBede.begin')}
        </button>
      </div>
    </div>
  )
}
