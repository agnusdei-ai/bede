import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Camera, Check, Printer, Sparkles, X } from 'lucide-react'
import {
  approvePracticeSet, confirmPracticeReading, discardPracticeSet, fetchPracticePacks,
  fetchReadingRoute, planPractice, PracticeConsentRequired, readPracticePhotos,
} from '../services/api'
import type {
  GradedAssessment, PracticePlan, PracticeReading, PracticeSetDraft, ReadingRoute, TeacherMark,
} from '../services/api'

// Parent-only (docs/PRACTICE_COACH.md). Photos of a graded quiz are read,
// the parent settles anything the reader was unsure of, Bede diagnoses the
// pattern and drafts practice, and the parent approves or discards it.
// Nothing here is ever shown to the child.

export const MAX_PAGES = 6
const MARKS: TeacherMark[] = ['correct', 'incorrect', 'partial', 'unmarked']
const CONFIDENCE_FLOOR = 0.75

/** What the file picker offers. The server decides the real type from the file's
 *  bytes (never from this list or the filename), so this only shapes the dialog.
 *  HEIC is withheld while the bundled native decoder lacks security fixes.
 *  The API also refuses HEIC before native decoding. A PDF counts for every page it holds. */
export const PRACTICE_ACCEPT =
  'image/jpeg,image/png,application/pdf,.pdf'

type Stage = 'start' | 'reading' | 'review' | 'planning' | 'plan' | 'done'

/** A data: URL from FileReader becomes the bare base64 the API expects —
 *  the same shape the handwriting canvas sends. */
export function toBase64Payload(dataUrl: string): string {
  const comma = dataUrl.indexOf(',')
  return comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl
}

export function isFlagged(item: { confidence: number; ask_parent?: string | null }): boolean {
  return Boolean(item.ask_parent) || item.confidence < CONFIDENCE_FLOOR
}

export function flaggedCount(a: GradedAssessment): number {
  return a.sections.reduce((n, s) => n + s.items.filter(isFlagged).length, 0)
}

export function teacherCount(a: GradedAssessment) {
  const marked = a.sections.flatMap((s) => s.items).filter((i) => i.teacher_mark !== 'unmarked')
  return { correct: marked.filter((i) => i.teacher_mark === 'correct').length, total: marked.length }
}

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(toBase64Payload(String(reader.result)))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!))
}

export default function PracticeCoach({ token, studentName }: { token: string; studentName: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [packs, setPacks] = useState<{ id: string; display_name: string }[]>([])
  const [route, setRoute] = useState<ReadingRoute | null>(null)
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

  useEffect(() => {
    if (!open) return
    let active = true
    Promise.all([fetchPracticePacks(token), fetchReadingRoute(token)])
      .then(([p, r]) => {
        if (!active) return
        setPacks(p)
        setRoute(r)
        setSubject((s) => s || p[0]?.id || '')
      })
      .catch(() => { if (active) setMessage(t('practiceCoach.loadError')) })
    return () => { active = false }
  }, [open, token, t])

  // A different child starts over: nothing from one child's quiz may linger
  // on another child's page.
  useEffect(() => {
    setStage('start'); setReading(null); setDraft(null); setPlan(null); setFiles([])
    setConsent(false); setMessage(''); setDecision(null)
  }, [studentName])

  const usesCloud = !!route && !route.local_available && !!route.cloud_provider
  const noReader = !!route && !route.local_available && !route.cloud_provider
  const remaining = draft ? flaggedCount(draft) : 0
  const count = useMemo(() => (draft ? teacherCount(draft) : null), [draft])

  const read = async () => {
    if (!files.length || !subject || (usesCloud && !consent)) return
    setStage('reading'); setMessage('')
    try {
      const pages = await Promise.all(files.map(async (f) => ({ data: await readFile(f) })))
      const result = await readPracticePhotos(token, studentName, {
        subject, pages, cloud_consent: usesCloud && consent,
      })
      setReading(result); setDraft(result.assessment); setStage('review')
    } catch (err) {
      setStage('start')
      setMessage(err instanceof PracticeConsentRequired
        ? t('practiceCoach.consentNeeded', { provider: err.provider ?? '' })
        : err instanceof Error ? err.message : t('practiceCoach.readError'))
    } finally {
      setFiles([])  // the photos are not kept in this page either
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
      await confirmPracticeReading(token, studentName, reading.id, draft)
      const result = await planPractice(token, studentName, reading.id)
      setPlan(result)
      setKeep((result.practice_set?.items ?? []).map(() => true))
      setStage('plan')
    } catch (err) {
      setStage('review')
      setMessage(err instanceof Error ? err.message : t('practiceCoach.planError'))
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
      await approvePracticeSet(token, studentName, plan.set_id, set)
      setDecision('approved'); setStage('done')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t('practiceCoach.planError'))
    }
  }

  const discard = async () => {
    if (!plan?.set_id) return
    try {
      await discardPracticeSet(token, studentName, plan.set_id)
      setDecision('discarded'); setStage('done')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t('practiceCoach.planError'))
    }
  }

  const printWorksheet = () => {
    const set = chosenSet()
    if (!set) return
    const win = window.open('', '_blank')
    if (!win) return
    const rows = set.items.map((item) =>
      `<li><p>${escapeHtml(item.prompt)}</p><div class="line"></div></li>`).join('')
    win.document.write(`<!doctype html><meta charset="utf-8"><title>${escapeHtml(t('practiceCoach.worksheetTitle'))}</title>
<style>body{font-family:Georgia,serif;margin:2rem;color:#1d2433}li{margin:0 0 1.4rem}.line{border-bottom:1px solid #999;height:2rem}</style>
<h1>${escapeHtml(t('practiceCoach.worksheetTitle'))}</h1><ol>${rows}</ol>`)
    win.document.close()
    win.print()
  }

  const reset = () => {
    setStage('start'); setReading(null); setDraft(null); setPlan(null); setDecision(null); setMessage('')
  }

  return (
    <section className="rounded-2xl border border-sage-100 bg-white p-4 sm:p-5 shadow-sm" aria-label={t('practiceCoach.title')}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <Sparkles size={19} className="mt-0.5 shrink-0 text-sage-700" />
          <div>
            <h2 className="font-display text-base font-semibold text-gray-800">{t('practiceCoach.title')}</h2>
            <p className="text-xs text-gray-500 mt-1">{t('practiceCoach.description')}</p>
          </div>
        </div>
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
          className="inline-flex items-center gap-1.5 rounded-lg bg-navy-50 px-3 py-2 text-sm font-medium text-navy-800">
          <Camera size={15} /> {open ? t('practiceCoach.close') : t('practiceCoach.open')}
        </button>
      </div>

      {open && (
        <div className="mt-4 space-y-4 text-sm text-gray-700">
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

              {route?.local_available && <p className="text-xs text-sage-800">{t('practiceCoach.routeLocal')}</p>}
              {usesCloud && (
                <label className="flex items-start gap-2 rounded-lg bg-gold-50 px-3 py-2 text-xs text-gray-700">
                  <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5" />
                  <span>{t('practiceCoach.routeCloud', { provider: route?.cloud_provider ?? '' })}</span>
                </label>
              )}
              {noReader && <p className="text-xs text-madder-800">{t('practiceCoach.routeNone')}</p>}

              <label className="block">
                <span className="text-xs font-medium text-gray-600">{t('practiceCoach.photos', { max: MAX_PAGES })}</span>
                <input type="file" accept={PRACTICE_ACCEPT} multiple aria-label={t('practiceCoach.photos', { max: MAX_PAGES })}
                  onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, MAX_PAGES))}
                  className="mt-1 block w-full text-xs" />
              </label>
              <p className="text-xs text-gray-500">{t('practiceCoach.photosHint', { max: MAX_PAGES })}</p>
              <p className="text-xs text-gray-500">{t('practiceCoach.privacy')}</p>

              <button type="button" onClick={read}
                disabled={stage === 'reading' || !files.length || !subject || noReader || (usesCloud && !consent)}
                className="rounded-lg bg-navy-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">
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
                                className="inline-flex items-center gap-1 rounded bg-white px-2 py-1 font-medium text-navy-800 ring-1 ring-navy-100">
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
                  className="rounded-lg bg-navy-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">
                  {stage === 'planning' ? t('practiceCoach.planning') : t('practiceCoach.confirm')}
                </button>
                <button type="button" onClick={reset} className="rounded-lg px-3 py-2 text-sm text-gray-600">{t('practiceCoach.startOver')}</button>
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
                  <p className="text-xs text-gray-500">{t('practiceCoach.recheck')}</p>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={approve} disabled={!keep.some(Boolean)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-sage-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">
                      <Check size={15} /> {t('practiceCoach.approve')}
                    </button>
                    <button type="button" onClick={printWorksheet} disabled={!keep.some(Boolean)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-navy-50 px-3 py-2 text-sm font-medium text-navy-800 disabled:opacity-40">
                      <Printer size={15} /> {t('practiceCoach.print')}
                    </button>
                    <button type="button" onClick={discard}
                      className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-gray-600">
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
              <button type="button" onClick={reset} className="rounded-lg bg-navy-50 px-3 py-2 text-sm font-medium text-navy-800">
                {t('practiceCoach.another')}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
