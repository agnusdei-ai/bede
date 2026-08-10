import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ClipboardList, Check, Loader2, X } from 'lucide-react'
import { submitFeedback } from '../services/api'

/**
 * The in-app leg of the beta survey — see docs/BETA_SURVEY.md, which is the
 * source of truth for every question here and for the rules governing what
 * a survey in this product may ask.
 *
 * Deliberately the SHORT set, not the whole instrument. This interrupts a
 * parent who came to the Progress page to look at their children, so it
 * carries only the five questions that need someone who has actually used
 * Bede, and links out to the full form for anyone willing to keep going.
 *
 * The answer VALUES below are the same strings site/survey/index.html
 * submits, verbatim, and are posted under the same 'beta_survey' category.
 * That is what lets a response from here pool with one from the website
 * instead of arriving as a second, differently-worded dataset that has to
 * be reconciled by hand. BetaSurveyModal.test.tsx pins it against the real
 * page rather than trusting the two to stay in step.
 *
 * Nothing here asks the parent to rate their child. Every question is about
 * Bede or about the parent's own day, which is the same line the product
 * itself draws between recording work and judging a person.
 */

/** Question keys, in the order they are asked. */
const QUESTIONS = ['daysUsed', 'parentTime', 'vsParent', 'accuracy'] as const
type QuestionKey = (typeof QUESTIONS)[number]

/**
 * The wire value for each option, keyed by the i18n key of its label.
 * Values are English regardless of the parent's locale, on purpose: they
 * are data for one inbox, not text for a reader, and translating them would
 * split every question into as many buckets as there are locales.
 */
const OPTIONS: Record<QuestionKey, ReadonlyArray<{ key: string; value: string }>> = {
  daysUsed: [
    { key: 'daysFew', value: 'Fewer than 3' },
    { key: 'daysWeek', value: 'About a week' },
    { key: 'daysMonth', value: 'Two to four weeks' },
    { key: 'daysLonger', value: 'More than a month' },
    { key: 'daysStopped', value: 'We stopped using it' },
  ],
  parentTime: [
    { key: 'timeBack', value: 'Gave me real time back' },
    { key: 'timeSame', value: 'About the same' },
    { key: 'timeCost', value: 'Cost me time' },
    { key: 'timeEarly', value: 'Too early to say' },
  ],
  vsParent: [
    { key: 'vsBetter', value: 'Better than I would have done' },
    { key: 'vsSame', value: 'About what I would have done' },
    { key: 'vsWorse', value: 'Worse than I would have done' },
    { key: 'vsUnsure', value: 'Have not watched closely enough' },
  ],
  accuracy: [
    { key: 'accuracyNo', value: 'No' },
    { key: 'accuracySmall', value: 'Yes, something small' },
    { key: 'accuracyBig', value: 'Yes, something that mattered' },
  ],
}

/** The full survey, for a parent willing to answer more than five questions. */
export const FULL_SURVEY_URL = 'https://agnusdei.ai/survey/'

export default function BetaSurveyModal({
  token,
  onClose,
  onDefer,
}: {
  token: string
  /** Answered, or explicitly declined — never ask again on this device. */
  onClose: () => void
  /** Dismissed for now — ask again in a fortnight. */
  onDefer: () => void
}) {
  const { t } = useTranslation()
  const [answers, setAnswers] = useState<Partial<Record<QuestionKey, string>>>({})
  const [detail, setDetail] = useState('')
  const [oneThing, setOneThing] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')

  const answered = Object.values(answers).filter(Boolean).length
  const hasSomething = answered > 0 || detail.trim() !== '' || oneThing.trim() !== ''

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!hasSomething) return
    setStatus('sending')

    // Assembled as readable "Question: answer" lines, the same shape the
    // website's own form produces, so both arrive looking alike in one
    // inbox. Questions are labelled in English for the same reason the
    // values are — the reader is the operator, not the parent.
    const lines: string[] = ['[In-app beta survey]', '']
    for (const q of QUESTIONS) {
      if (answers[q]) lines.push(`${t(`betaSurvey.${q}`, { lng: 'en' })}: ${answers[q]}`)
    }
    if (detail.trim()) lines.push(`${t('betaSurvey.accuracyDetail', { lng: 'en' })}: ${detail.trim()}`)
    if (oneThing.trim()) lines.push(`${t('betaSurvey.oneThing', { lng: 'en' })}: ${oneThing.trim()}`)

    try {
      await submitFeedback(token, 'beta_survey', lines.join('\n').slice(0, 2000))
      setStatus('sent')
    } catch {
      setStatus('error')
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4 overflow-y-auto">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-md p-6 relative my-8">
        <button
          onClick={onDefer}
          className="absolute top-3 right-3 text-gray-400 hover:text-gray-600"
          aria-label={t('betaSurvey.notNow')}
        >
          <X size={18} />
        </button>

        {status === 'sent' ? (
          <div className="text-center py-4">
            <Check size={28} className="mx-auto mb-3 text-green-600" />
            <p className="text-sm font-semibold text-gray-800 mb-1">{t('betaSurvey.thanks')}</p>
            <p className="text-xs text-gray-500 mb-1">{t('betaSurvey.thanksMore')}</p>
            <a
              href={FULL_SURVEY_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-navy-600 underline"
            >
              {t('betaSurvey.fullSurveyLink')}
            </a>
            <button
              onClick={onClose}
              className="mt-5 w-full py-2.5 bg-navy-100 text-navy-700 rounded-xl font-semibold text-sm hover:bg-navy-200 transition-colors"
            >
              {t('betaSurvey.done')}
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="flex items-center gap-1.5 mb-1">
              <ClipboardList size={16} className="text-navy-500" />
              <h2 className="text-sm font-display font-bold text-gray-800">{t('betaSurvey.title')}</h2>
            </div>
            <p className="text-xs text-gray-500 mb-4">{t('betaSurvey.subtitle')}</p>

            {QUESTIONS.map((q) => (
              <fieldset key={q} className="mb-4">
                <legend className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1.5">
                  {t(`betaSurvey.${q}`)}
                </legend>
                <div className="flex flex-col gap-1">
                  {OPTIONS[q].map((opt) => (
                    <label key={opt.key} className="flex items-start gap-2 text-sm text-gray-700 cursor-pointer">
                      <input
                        type="radio"
                        name={q}
                        value={opt.value}
                        checked={answers[q] === opt.value}
                        onChange={() => setAnswers((a) => ({ ...a, [q]: opt.value }))}
                        className="mt-1 accent-navy-500"
                      />
                      <span>{t(`betaSurvey.${opt.key}`)}</span>
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}

            {/* Shown always, not only after "yes" — a parent who has not
                picked an accuracy option yet may still want to describe
                what they saw, and a field that appears on selection is a
                field most people never discover. */}
            <label htmlFor="beta-survey-detail" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              {t('betaSurvey.accuracyDetail')}
            </label>
            <textarea
              id="beta-survey-detail"
              maxLength={600}
              rows={2}
              value={detail}
              onChange={(e) => setDetail(e.target.value)}
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 mb-4 resize-none focus:outline-none focus:ring-2 focus:ring-navy-400"
            />

            <label htmlFor="beta-survey-one-thing" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              {t('betaSurvey.oneThing')}
            </label>
            <textarea
              id="beta-survey-one-thing"
              maxLength={600}
              rows={2}
              value={oneThing}
              onChange={(e) => setOneThing(e.target.value)}
              placeholder={t('betaSurvey.oneThingPlaceholder') ?? ''}
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 mb-2 resize-none focus:outline-none focus:ring-2 focus:ring-navy-400"
            />

            <p className="text-xs text-gray-400 mb-4">{t('betaSurvey.privacyNote')}</p>

            {status === 'error' && (
              <p className="text-xs text-red-600 mb-3">{t('betaSurvey.error')}</p>
            )}

            <div className="flex gap-2">
              <button
                type="button"
                onClick={onDefer}
                className="flex-1 py-2.5 bg-gray-100 text-gray-600 rounded-xl font-semibold text-sm hover:bg-gray-200 transition-colors"
              >
                {t('betaSurvey.notNow')}
              </button>
              <button
                type="submit"
                disabled={status === 'sending' || !hasSomething}
                className="flex-1 py-2.5 bg-navy-500 text-white rounded-xl font-semibold text-sm hover:bg-navy-600 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {status === 'sending' && <Loader2 size={14} className="animate-spin" />}
                {t('betaSurvey.submit')}
              </button>
            </div>

            <button
              type="button"
              onClick={onClose}
              className="w-full mt-2 text-xs text-gray-400 hover:text-gray-600 underline"
            >
              {t('betaSurvey.dontAskAgain')}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
