import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Camera, Check, Printer, Sparkles, X } from 'lucide-react'

import {
  approvePracticeSet,
  confirmPracticeReading,
  discardPracticeSet,
  fetchPracticePacks,
  fetchPracticeRoute,
  planPractice,
  PracticeConsentRequired,
  PracticeQuotaExceeded,
  readPracticePhotos,
  TrialSessionEndedError,
} from './api'
import type {
  GradedAssessment, PracticeDemoRoute, PracticePlan, PracticeReading, PracticeSetDraft, TeacherMark,
} from './api'
import {
  flaggedCount, isFlagged, MARKS, MAX_PAGES, PRACTICE_ACCEPT, teacherCount, toBase64Payload, worksheetHtml,
} from './practiceCoachLogic'

/**
 * The demo's Practice Coach (docs/PRACTICE_COACH.md, "On the public demo"),
 * a mirror of homeschool-tutor/src/components/PracticeCoach.tsx. The gates
 * are the product's own and `practiceCoach.test.tsx` breaks each in turn:
 *
 *   - nothing is uploaded without the visitor's tick, which names the
 *     provider and is asked again for EVERY upload (it resets after each);
 *   - a reading the reader was unsure of cannot go on to planning until each
 *     flagged answer is settled with "Looks right" (or corrected);
 *   - the visitor can untick items before approving, and print a worksheet
 *     (prompts and answer lines only, never the expected answers);
 *   - starting another quiz clears the last one entirely.
 *
 * What differs from the app, on purpose: there is no child to deliver to and
 * no student record, so "approve" keeps nothing past the session; the pages
 * always go to the demo's cloud provider (there is no local model); the
 * session has a small allowance of reads (server-enforced, shown here).
 */

type Stage = 'start' | 'reading' | 'review' | 'planning' | 'plan' | 'done'

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(toBase64Payload(String(reader.result)))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

export function PracticeCoachCard({
  token,
  onSessionEnded,
}: {
  token: string
  onSessionEnded?: () => void
}) {
  const { t } = useTranslation()
  // Held in a ref so a parent that passes a fresh callback every render does
  // not refetch the packs and reading route (and reset the allowance) each time.
  const endedRef = useRef(onSessionEnded)
  endedRef.current = onSessionEnded
  const [packs, setPacks] = useState<{ id: string; display_name: string }[]>([])
  const [route, setRoute] = useState<PracticeDemoRoute | null>(null)
  const [subject, setSubject] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [consent, setConsent] = useState(false)
  const [stage, setStage] = useState<Stage>('start')
  const [reading, setReading] = useState<PracticeReading | null>(null)
  const [draft, setDraft] = useState<GradedAssessment | null>(null)
  const [plan, setPlan] = useState<PracticePlan | null>(null)
  const [keep, setKeep] = useState<boolean[]>([])
  const [message, setMessage] = useState('')
  const [decision, setDecision] = useState<'approved' | 'discarded' | null>(null)
  const [fileInputKey, setFileInputKey] = useState(0)

  useEffect(() => {
    let active = true
    Promise.all([fetchPracticePacks(token), fetchPracticeRoute(token)])
      .then(([p, r]) => {
        if (!active) return
        setPacks(p)
        setRoute(r)
        setSubject((s) => s || p[0]?.id || '')
      })
      .catch((err) => {
        if (!active) return
        if (err instanceof TrialSessionEndedError) endedRef.current?.()
        else setMessage(t('practiceCoach.loadError'))
      })
    return () => { active = false }
  }, [token, t])

  const provider = route?.cloud_provider ?? null
  const noReader = !!route && !provider
  const outOfReads = !!route && route.uploads_remaining <= 0
  const remaining = draft ? flaggedCount(draft) : 0
  const count = useMemo(() => (draft ? teacherCount(draft) : null), [draft])

  const fail = (err: unknown, fallback: string) => {
    if (err instanceof TrialSessionEndedError) { endedRef.current?.(); return }
    setMessage(err instanceof Error && err.message ? err.message : fallback)
  }

  const read = async () => {
    if (!files.length || !subject || !consent || noReader || outOfReads) return
    // A new upload starts from nothing: no earlier reading, plan or decision may linger.
    setReading(null); setDraft(null); setPlan(null); setDecision(null); setKeep([])
    setStage('reading'); setMessage('')
    try {
      const pages = await Promise.all(files.map(async (f) => ({ data: await readFile(f) })))
      const result = await readPracticePhotos(token, { subject, pages, cloud_consent: consent })
      setReading(result); setDraft(result.assessment); setStage('review')
      if (typeof result.uploads_remaining === 'number') {
        setRoute((r) => (r ? { ...r, uploads_remaining: result.uploads_remaining as number } : r))
      }
    } catch (err) {
      setStage('start')
      if (err instanceof PracticeQuotaExceeded) {
        setRoute((r) => (r ? { ...r, uploads_remaining: 0 } : r))
        setMessage(err.message)
      } else if (err instanceof PracticeConsentRequired) {
        setMessage(t('practiceCoach.consentNeeded', { provider: err.provider ?? '' }))
      } else {
        fail(err, t('practiceCoach.readError'))
      }
    } finally {
      // The pages are not kept in this page either, and the tick is per upload:
      // the next one has to be agreed to again.
      setFiles([]); setConsent(false); setFileInputKey((k) => k + 1)
    }
  }

  const editItem = (si: number, ii: number, patch: Partial<GradedAssessment['sections'][0]['items'][0]>) => {
    setDraft((d) => {
      if (!d) return d
      const next: GradedAssessment = structuredClone(d)
      Object.assign(next.sections[si].items[ii], patch)
      return next
    })
  }

  const confirmAndPlan = async () => {
    if (!reading || !draft || remaining) return
    setStage('planning'); setMessage('')
    try {
      await confirmPracticeReading(token, reading.id, draft)
      const result = await planPractice(token, reading.id)
      setPlan(result)
      setKeep((result.practice_set?.items ?? []).map(() => true))
      setStage('plan')
    } catch (err) {
      setStage('review')
      fail(err, t('practiceCoach.planError'))
    }
  }

  const chosenSet = (): PracticeSetDraft | null => {
    if (!plan?.practice_set) return null
    return { ...plan.practice_set, items: plan.practice_set.items.filter((_, i) => keep[i]) }
  }

  const approve = async () => {
    const set = chosenSet()
    if (!plan?.set_id || !set || !set.items.length) return
    try {
      await approvePracticeSet(token, plan.set_id, set)
      setDecision('approved'); setStage('done')
    } catch (err) {
      fail(err, t('practiceCoach.planError'))
    }
  }

  const discard = async () => {
    if (!plan?.set_id) return
    try {
      await discardPracticeSet(token, plan.set_id)
      setDecision('discarded'); setStage('done')
    } catch (err) {
      fail(err, t('practiceCoach.planError'))
    }
  }

  const printWorksheet = () => {
    const set = chosenSet()
    if (!set) return
    const win = window.open('', '_blank')
    if (!win) return
    win.document.write(worksheetHtml(t('practiceCoach.worksheetTitle'), set.items.map((i) => i.prompt)))
    win.document.close()
    win.print()
  }

  const reset = () => {
    setStage('start'); setReading(null); setDraft(null); setPlan(null); setKeep([])
    setDecision(null); setMessage(''); setConsent(false); setFiles([]); setFileInputKey((k) => k + 1)
  }

  return (
    <section className="rounded-2xl border border-sage-100 bg-white p-4 text-sm text-gray-700" aria-label={t('practiceCoach.title')}>
      <div className="flex items-start gap-2.5">
        <Sparkles size={19} className="mt-0.5 shrink-0 text-sage-700" />
        <div>
          <h2 className="font-display text-base font-semibold text-gray-800">{t('practiceCoach.title')}</h2>
          <p className="text-xs text-gray-500 mt-1">{t('practiceCoach.description')}</p>
        </div>
      </div>

      <div className="mt-4 space-y-4">
        {message && <p role="alert" className="rounded-lg bg-madder-50 px-3 py-2 text-madder-800">{message}</p>}

        {(stage === 'start' || stage === 'reading') && (
          <div className="space-y-3">
            <label className="block">
              <span className="text-xs font-medium text-gray-600">{t('practiceCoach.subject')}</span>
              <select value={subject} onChange={(e) => setSubject(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-gray-200 px-3 py-2">
                {packs.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
              </select>
            </label>

            {provider && (
              <label className="flex items-start gap-2 rounded-lg bg-gold-50 px-3 py-2 text-xs text-gray-700">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5" />
                <span>{t('practiceCoach.routeCloud', { provider })}</span>
              </label>
            )}
            {noReader && <p className="text-xs text-madder-800">{t('practiceCoach.routeNone')}</p>}
            {route && (
              <p className="text-xs text-gray-500">
                {t('practiceCoach.allowance', { left: route.uploads_remaining, max: route.max_uploads })}
              </p>
            )}

            <label className="block">
              <span className="text-xs font-medium text-gray-600">{t('practiceCoach.photos', { max: MAX_PAGES })}</span>
              <input key={fileInputKey} type="file" accept={PRACTICE_ACCEPT} multiple
                aria-label={t('practiceCoach.photos', { max: MAX_PAGES })}
                onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, MAX_PAGES))}
                className="mt-1 block w-full text-xs" />
            </label>
            <p className="text-xs text-gray-500">{t('practiceCoach.photosHint', { max: MAX_PAGES })}</p>
            <p className="text-xs text-gray-500">{t('practiceCoach.privacy')}</p>

            <button type="button" onClick={read}
              disabled={stage === 'reading' || !files.length || !subject || noReader || outOfReads || !consent}
              className="rounded-lg bg-navy-700 px-4 py-2 min-h-[44px] text-sm font-medium text-white disabled:opacity-40">
              {stage === 'reading' ? t('practiceCoach.reading') : t('practiceCoach.read')}
            </button>
          </div>
        )}

        {(stage === 'review' || stage === 'planning') && draft && (
          <div className="space-y-4">
            {count && <p className="font-medium">{t('practiceCoach.teacherCount', count)}</p>}
            {remaining > 0
              ? <p role="status" className="rounded-lg bg-gold-50 px-3 py-2 text-xs">{t('practiceCoach.checkCount', { count: remaining })}</p>
              : <p className="text-xs text-sage-800">{t('practiceCoach.allSettled')}</p>}
            {draft.sections.map((section, si) => (
              <fieldset key={section.label} className="rounded-xl border border-gray-100 p-3">
                <legend className="px-1 text-xs font-semibold text-gray-600">{section.label}</legend>
                {section.instructions && <p className="mb-2 text-xs text-gray-500">{section.instructions}</p>}
                <ul className="space-y-2">
                  {section.items.map((item, ii) => {
                    const flagged = isFlagged(item)
                    const label = `${section.label} #${item.number}`
                    return (
                      <li key={item.number} data-flagged={flagged || undefined}
                        className={`rounded-lg p-2 ${flagged ? 'bg-gold-50 ring-1 ring-gold-300' : 'bg-parchment-50'}`}>
                        <p className="text-xs text-gray-600">{item.number}. {item.prompt}{item.stimulus ? ` (${item.stimulus})` : ''}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-2">
                          <input value={item.student_response ?? ''} aria-label={t('practiceCoach.answerFor', { item: label })}
                            onChange={(e) => editItem(si, ii, { student_response: e.target.value })}
                            className="min-w-0 flex-1 rounded border border-gray-200 px-2 py-1" />
                          <select value={item.teacher_mark} aria-label={t('practiceCoach.markFor', { item: label })}
                            onChange={(e) => editItem(si, ii, { teacher_mark: e.target.value as TeacherMark })}
                            className="rounded border border-gray-200 px-2 py-1">
                            {MARKS.map((m) => <option key={m} value={m}>{t(`practiceCoach.mark.${m}`)}</option>)}
                          </select>
                          {item.teacher_mark !== 'correct' && (
                            <input value={item.teacher_correction ?? ''} placeholder={t('practiceCoach.correction')}
                              aria-label={t('practiceCoach.correctionFor', { item: label })}
                              onChange={(e) => editItem(si, ii, { teacher_correction: e.target.value || null })}
                              className="min-w-0 flex-1 rounded border border-gray-200 px-2 py-1" />
                          )}
                        </div>
                        {flagged && (
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                            <span>{item.ask_parent || t('practiceCoach.unsure')}</span>
                            <button type="button" onClick={() => editItem(si, ii, { ask_parent: null, confidence: 1 })}
                              className="inline-flex items-center gap-1 rounded bg-white px-2 py-1 min-h-[32px] font-medium text-navy-800 ring-1 ring-navy-100">
                              <Check size={13} /> {t('practiceCoach.looksRight')}
                            </button>
                          </div>
                        )}
                      </li>
                    )
                  })}
                </ul>
              </fieldset>
            ))}
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={confirmAndPlan} disabled={remaining > 0 || stage === 'planning'}
                className="rounded-lg bg-navy-700 px-4 py-2 min-h-[44px] text-sm font-medium text-white disabled:opacity-40">
                {stage === 'planning' ? t('practiceCoach.planning') : t('practiceCoach.confirm')}
              </button>
              <button type="button" onClick={reset} className="rounded-lg px-3 py-2 min-h-[44px] text-sm text-gray-600">{t('practiceCoach.startOver')}</button>
            </div>
          </div>
        )}

        {stage === 'plan' && plan && (
          <div className="space-y-4">
            {count && <p className="font-medium">{t('practiceCoach.teacherCount', count)}</p>}
            {[
              { key: 'workOn', items: plan.diagnosis.errors.filter((e) => e.audience === 'parent_and_child') },
              { key: 'forYou', items: plan.diagnosis.errors.filter((e) => e.audience === 'parent_only') },
            ].filter((group) => group.items.length > 0).map((group) => (
              <div key={group.key}>
                <h3 className="text-xs font-semibold text-gray-600">{t(`practiceCoach.${group.key}`)}</h3>
                <ul className="mt-1 list-disc pl-5 text-xs">
                  {group.items.map((e) => <li key={`${e.item_ref}-${e.category}`}>{e.item_ref}: {e.evidence}</li>)}
                </ul>
              </div>
            ))}
            {plan.diagnosis.strengths.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-gray-600">{t('practiceCoach.strengths')}</h3>
                <ul className="mt-1 list-disc pl-5 text-xs">{plan.diagnosis.strengths.map((s) => <li key={s.category}>{s.note}</li>)}</ul>
              </div>
            )}
            {plan.practice_set ? (
              <div className="space-y-2">
                <h3 className="text-xs font-semibold text-gray-600">
                  {t('practiceCoach.setHeading', { minutes: plan.practice_set.est_minutes })}
                </h3>
                <ol className="space-y-2">
                  {plan.practice_set.items.map((item, i) => (
                    <li key={i} className="flex items-start gap-2 rounded-lg bg-parchment-50 p-2 text-xs">
                      <input type="checkbox" checked={keep[i] ?? true} aria-label={t('practiceCoach.include', { n: i + 1 })}
                        onChange={(e) => setKeep((k) => k.map((v, j) => (j === i ? e.target.checked : v)))} className="mt-0.5" />
                      <div>
                        <p className="font-medium text-gray-800">{item.prompt}</p>
                        <p className="text-gray-600">{t('practiceCoach.answer')}: {item.expected_answer}</p>
                        {item.hint && <p className="text-gray-500">{t('practiceCoach.hint')}: {item.hint}</p>}
                      </div>
                    </li>
                  ))}
                </ol>
                <p className="text-xs text-gray-600"><span className="font-semibold">{t('practiceCoach.script')}:</span> {plan.practice_set.parent_script}</p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={approve} disabled={!keep.some(Boolean)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-sage-700 px-4 py-2 min-h-[44px] text-sm font-medium text-white disabled:opacity-40">
                    <Check size={15} /> {t('practiceCoach.approve')}
                  </button>
                  <button type="button" onClick={printWorksheet} disabled={!keep.some(Boolean)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-navy-50 px-3 py-2 min-h-[44px] text-sm font-medium text-navy-800 disabled:opacity-40">
                    <Printer size={15} /> {t('practiceCoach.print')}
                  </button>
                  <button type="button" onClick={discard}
                    className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 min-h-[44px] text-sm text-gray-600">
                    <X size={15} /> {t('practiceCoach.discard')}
                  </button>
                </div>
              </div>
            ) : <p className="text-xs">{t('practiceCoach.nothingToPractise')}</p>}
          </div>
        )}

        {stage === 'done' && (
          <div className="space-y-2">
            <p role="status">{decision === 'approved' ? t('practiceCoach.approved') : t('practiceCoach.discarded')}</p>
            <button type="button" onClick={reset} disabled={outOfReads}
              className="rounded-lg bg-navy-50 px-3 py-2 min-h-[44px] text-sm font-medium text-navy-800 disabled:opacity-40">
              {t('practiceCoach.another')}
            </button>
          </div>
        )}
      </div>
    </section>
  )
}

/** The card in a panel over the chat, opened from the parent controls menu,
 *  the same way the demo's Parent Setup panel is. */
export default function PracticeCoachPanel({
  token,
  onClose,
  onSessionEnded,
}: {
  token: string
  onClose: () => void
  onSessionEnded?: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-900/40 backdrop-blur-sm p-3">
      <div role="dialog" aria-modal="true" aria-label={t('practiceCoach.title')}
        className="w-full max-w-lg max-h-[calc(100dvh-1.5rem)] flex flex-col bg-parchment-50 rounded-2xl border border-sage-200 shadow-xl">
        <div className="shrink-0 flex items-center justify-between px-4 py-3 border-b border-sage-200 rounded-t-2xl">
          <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-navy-600">
            <Camera size={15} /> {t('practiceCoach.preview')}
          </span>
          <button type="button" onClick={onClose} aria-label={t('practiceCoach.close')} title={t('practiceCoach.close')}
            className="p-2 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-gray-500 hover:bg-sage-100">
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto p-3">
          <PracticeCoachCard token={token} onSessionEnded={onSessionEnded} />
        </div>
      </div>
    </div>
  )
}
