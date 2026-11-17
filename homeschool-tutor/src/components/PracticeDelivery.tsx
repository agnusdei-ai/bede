import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Loader2, RefreshCw } from 'lucide-react'
import { fetchPracticeDelivery, recordPracticeOutcome } from '../services/api'
import type { PracticeDeliverySet } from '../services/api'
import Diagram from './Diagram'

/** PracticeOutcomeRequest.response's max_length in models/practice.py; a test
 *  holds the two equal. The box used to allow 4,000, so a longer answer was
 *  typed and then refused on save. */
export const MAX_PRACTICE_ANSWER_CHARS = 1000

export default function PracticeDelivery({
  token,
  studentName,
  onAnswer,
  busy = false,
}: {
  token: string
  studentName: string
  onAnswer: (prompt: string, response: string) => void
  /** Bede is still replying. The chat drops anything sent while it streams,
   *  so an answer sent now would be recorded but never reach Bede: wait. */
  busy?: boolean
}) {
  const { t } = useTranslation()
  const [sets, setSets] = useState<PracticeDeliverySet[] | null>(null)
  const [response, setResponse] = useState('')
  const [loading, setLoading] = useState(false)
  const [savingKey, setSavingKey] = useState<string | null>(null)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setSets(await fetchPracticeDelivery(token, studentName))
    } catch {
      setError(t('practiceDelivery.loadError'))
    } finally {
      setLoading(false)
    }
  }, [token, studentName, t])

  useEffect(() => {
    void refresh()
    const onFocus = () => { void refresh() }
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [refresh])

  const current = sets?.flatMap((set) =>
    set.items
      .filter((item) => !set.completed_indices.includes(item.index))
      .map((item) => ({ set, item })),
  )[0] ?? null

  const submit = async () => {
    if (!current || !response.trim() || busy) return
    const key = `${current.set.id}:${current.item.index}`
    setSavingKey(key)
    setError('')
    try {
      await recordPracticeOutcome(
        token, studentName, current.set.id, current.item.index, response.trim(),
      )
      const submitted = response.trim()
      setSets((previous) => previous?.map((set) => (
        set.id === current.set.id
          ? { ...set, completed_indices: [...new Set([...set.completed_indices, current.item.index])] }
          : set
      )) ?? null)
      setResponse('')
      onAnswer(current.item.prompt, submitted)
    } catch {
      setError(t('practiceDelivery.saveError'))
    } finally {
      setSavingKey(null)
    }
  }

  if (sets === null && loading) return null

  return (
    // Capped and scrollable on its own: at large text on a phone, an uncapped
    // card pushed the conversation down to a 56 px strip, so Bede's replies
    // arrived but could not be read.
    <section
      aria-label={t('practiceDelivery.title')}
      className="mx-4 mt-3 max-h-[25dvh] shrink-0 overflow-y-auto rounded-xl border border-sage-200 bg-sage-50 p-3 text-sm"
    >
      {current ? (
        <>
          <h3 className="font-semibold text-sage-900">{t('practiceDelivery.title')}</h3>
          <p className="mt-2 text-gray-800">{current.item.prompt}</p>
          <Diagram d={current.item.diagram} />
          {current.item.hint && <p className="mt-1 text-xs text-gray-600">{t('practiceDelivery.hint', { hint: current.item.hint })}</p>}
          <label className="mt-2 block">
            <span className="sr-only">{t('practiceDelivery.responseLabel')}</span>
            <textarea
              value={response}
              onChange={(event) => setResponse(event.target.value)}
              aria-label={t('practiceDelivery.responseLabel')}
              rows={2}
              maxLength={MAX_PRACTICE_ANSWER_CHARS}
              className="w-full rounded-lg border border-sage-300 bg-white px-3 py-2"
            />
          </label>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={!response.trim() || savingKey !== null || busy}
            className="mt-2 inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-sage-700 px-4 py-2 font-medium text-white disabled:opacity-50"
          >
            {savingKey ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
            {t('practiceDelivery.submit')}
          </button>
        </>
      ) : (
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="inline-flex min-h-[44px] items-center gap-2 rounded-lg px-2 font-medium text-sage-900 disabled:opacity-50"
        >
          <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
          {t('practiceDelivery.check')}
        </button>
      )}
      {error && <p role="alert" className="mt-2 text-xs text-madder-800">{error}</p>}
    </section>
  )
}
