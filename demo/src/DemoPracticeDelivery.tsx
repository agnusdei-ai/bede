import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { DemoPracticeDeliveryItem } from './api'
import Diagram from './Diagram'

export default function DemoPracticeDelivery({
  items,
  busy,
  onAnswer,
}: {
  items: DemoPracticeDeliveryItem[]
  busy: boolean
  onAnswer: (prompt: string, response: string) => void
}) {
  const { t } = useTranslation()
  const [responses, setResponses] = useState<Record<number, string>>({})
  const [response, setResponse] = useState('')
  const sendingRef = useRef(false)
  const current = items.find((item) => responses[item.index] === undefined)

  useEffect(() => {
    if (!busy) sendingRef.current = false
  }, [busy])

  const submit = () => {
    const answer = response.trim()
    if (!current || !answer || busy || sendingRef.current) return
    sendingRef.current = true
    setResponses((previous) => ({ ...previous, [current.index]: answer }))
    setResponse('')
    onAnswer(current.prompt, answer)
  }

  return (
    <section aria-label={t('demoPractice.deliveryTitle')} className="rounded-xl border border-sage-200 bg-sage-50 p-3 text-sm">
      {current ? (
        <>
          <h3 className="font-semibold text-sage-900">{t('demoPractice.deliveryTitle')}</h3>
          <p className="mt-2 text-gray-800">{current.prompt}</p>
          <Diagram d={current.diagram} />
          {current.hint && <p className="mt-1 text-xs text-gray-600">{t('demoPractice.deliveryHint', { hint: current.hint })}</p>}
          <label className="mt-2 block">
            <span className="sr-only">{t('demoPractice.responseLabel')}</span>
            <textarea
              value={response}
              onChange={(event) => setResponse(event.target.value)}
              aria-label={t('demoPractice.responseLabel')}
              rows={2}
              maxLength={4000}
              className="w-full rounded-lg border border-sage-300 bg-white px-3 py-2"
            />
          </label>
          <button
            type="button"
            onClick={submit}
            disabled={!response.trim() || busy}
            className="mt-2 inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-sage-700 px-4 py-2 font-medium text-white disabled:opacity-50"
          >
            {t('demoPractice.submitResponse')}
          </button>
        </>
      ) : (
        <p role="status">{t('demoPractice.completed', { count: Object.keys(responses).length })}</p>
      )}
    </section>
  )
}
