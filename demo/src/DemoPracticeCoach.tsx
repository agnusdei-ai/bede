import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Loader2, X } from 'lucide-react'
import {
  approveDemoPractice,
  fetchDemoPracticePacks,
  fetchDemoPracticeReadingRoute,
  fetchDemoReadingProgress,
  readDemoPracticePhotos,
  planDemoPractice,
  type DemoPracticeAssessment,
  type DemoPracticeSetDraft,
} from './api'
import DemoQuizBuilder from './DemoQuizBuilder'
import { splitIntoParts, uploadProblem } from './uploadParts'
import { withProgress, type ProgressState } from './readingProgress'
import ReadingProgressBar from './ReadingProgressBar'
import Diagram, { pictureWords } from './Diagram'

// HEIC is left out on purpose: iPhones then send a JPEG copy, and the server's
// HEIC decoder is held back until its security fix ships.
const ACCEPT = 'image/jpeg,image/png,image/webp,image/avif,.jpg,.jpeg,.png,.webp,.avif,application/pdf,.pdf'

function base64Payload(dataUrl: string) {
  const comma = dataUrl.indexOf(',')
  return comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl
}

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(base64Payload(String(reader.result)))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function flaggedCount(assessment: DemoPracticeAssessment) {
  return assessment.sections.reduce(
    (count, section) => count + section.items.filter((item) => item.ask_parent || item.confidence < 0.75).length,
    0,
  )
}

export default function DemoPracticeCoach({
  token,
  onClose,
  onApproved,
}: {
  token: string
  onClose: () => void
  onApproved: (items: { index: number; prompt: string; hint: string }[]) => void
}) {
  const { t } = useTranslation()
  const [packs, setPacks] = useState<{ id: string; display_name: string }[]>([])
  const [route, setRoute] = useState<{ local_available: boolean; cloud_provider: string | null } | null>(null)
  const [subject, setSubject] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [progress, setProgress] = useState<ProgressState | null>(null)
  const [cloudConsent, setCloudConsent] = useState(false)
  const [stage, setStage] = useState<'start' | 'reading' | 'review' | 'planning' | 'plan'>('start')
  const [assessment, setAssessment] = useState<DemoPracticeAssessment | null>(null)
  const [practice, setPractice] = useState<DemoPracticeSetDraft | null>(null)
  const [planSummary, setPlanSummary] = useState('')
  const [diagnosis, setDiagnosis] = useState<{
    errors: Array<{ item_ref: string; category: string; evidence: string; audience: 'parent_and_child' | 'parent_only' }>
    strengths: Array<{ category: string; note: string }>
    ask_parent: string[]
  } | null>(null)
  const [keep, setKeep] = useState<boolean[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'practice' | 'quiz'>('practice')

  useEffect(() => {
    let active = true
    Promise.all([fetchDemoPracticePacks(token), fetchDemoPracticeReadingRoute(token)])
      .then(([available, readingRoute]) => {
        if (!active) return
        setPacks(available)
        setSubject(available[0]?.id ?? '')
        setRoute(readingRoute)
      })
      .catch(() => { if (active) setError(t('demoPractice.loadError')) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [token, t])

  const usesCloud = !!route && !route.local_available && !!route.cloud_provider
  const noReader = !!route && !route.local_available && !route.cloud_provider
  const remaining = useMemo(() => assessment ? flaggedCount(assessment) : 0, [assessment])

  const read = async () => {
    if (!files.length || !subject || noReader || (usesCloud && !cloudConsent)) return
    setStage('reading')
    setError('')
    try {
      // Any number of pages: sent a part at a time. The demo stores nothing,
      // so each part carries what the earlier parts read.
      let sofar: DemoPracticeAssessment | undefined
      let firstPage = 1
      await withProgress(splitIntoParts(files), async (part, _index, progressId) => {
        const pages = await Promise.all(part.map(async (file) => ({ data: await readFile(file) })))
        const result = await readDemoPracticePhotos(token, {
          subject,
          pages,
          cloud_consent: usesCloud && cloudConsent,
          first_page: firstPage,
          continues: sofar,
          progress_id: progressId,
        })
        sofar = result.assessment
        firstPage += result.pages_read ?? pages.length
      }, (id) => fetchDemoReadingProgress(token, id), setProgress)
      if (!sofar) return
      setAssessment(sofar)
      setStage('review')
    } catch (reason) {
      setStage('start')
      setError(reason instanceof Error ? reason.message : t('demoPractice.readError'))
    } finally {
      setProgress(null)
      setFiles([])
    }
  }

  const editItem = (
    sectionIndex: number,
    itemIndex: number,
    patch: Partial<DemoPracticeAssessment['sections'][0]['items'][0]>,
  ) => {
    setAssessment((previous) => {
      if (!previous) return previous
      return {
        ...previous,
        sections: previous.sections.map((section, currentSection) => currentSection === sectionIndex
        ? {
          ...section,
          items: section.items.map((item, currentItem) => currentItem === itemIndex ? { ...item, ...patch } : item),
        }
        : section),
      }
    })
  }

  const makePlan = async () => {
    if (!assessment || remaining) return
    setStage('planning')
    setError('')
    try {
      const result = await planDemoPractice(token, assessment)
      setPractice(result.practice_set)
      setPlanSummary(result.summary)
      setDiagnosis(result.diagnosis)
      setKeep((result.practice_set?.items ?? []).map(() => true))
      setStage('plan')
    } catch (reason) {
      setStage('review')
      setError(reason instanceof Error ? reason.message : t('demoPractice.planError'))
    }
  }

  const approve = async () => {
    if (!practice) return
    const selected = {
      ...practice,
      items: practice.items.filter((_, index) => keep[index]),
    }
    if (!selected.items.length) return
    setSaving(true)
    setError('')
    try {
      const result = await approveDemoPractice(token, selected)
      onApproved(result.items)
      onClose()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('demoPractice.planError'))
    } finally {
      setSaving(false)
    }
  }

  const label = 'block text-xs font-medium text-gray-600'
  const button = 'min-h-[44px] rounded-lg px-4 py-2 text-sm font-medium'

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-navy-900/50 p-3" role="dialog" aria-modal="true" aria-label={t('demoPractice.title')}>
      <div className="flex max-h-[calc(100dvh-1.5rem)] w-full max-w-2xl flex-col rounded-2xl border border-sage-200 bg-parchment-50 shadow-xl">
        <div className="flex shrink-0 items-center justify-between border-b border-sage-200 px-4 py-3">
          <h2 className="font-display text-base font-bold text-navy-800">{t('demoPractice.title')}</h2>
          <button type="button" onClick={onClose} aria-label={t('demoPractice.close')} className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-gray-600 hover:bg-sage-100">
            <X size={18} />
          </button>
        </div>

        <div role="tablist" aria-label={t('demoPractice.title')} className="flex shrink-0 gap-1 border-b border-sage-200 px-4 pt-2">
          {(['practice', 'quiz'] as const).map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={tab === name}
              onClick={() => setTab(name)}
              className={`min-h-[44px] rounded-t-lg px-3 text-sm font-medium ${tab === name ? 'bg-white text-navy-800' : 'text-gray-600 hover:bg-sage-100'}`}
            >
              {t(name === 'practice' ? 'demoPractice.tabPractice' : 'demoPractice.tabQuiz')}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 text-sm text-gray-700">
          {tab === 'quiz' && (
            <DemoQuizBuilder token={token} onApproved={(items) => { onApproved(items); onClose() }} />
          )}
          {tab === 'practice' && <>
          {error && <p role="alert" className="rounded-lg bg-madder-50 px-3 py-2 text-madder-800">{error}</p>}
          {loading && <p role="status">{t('demoPractice.loading')}</p>}

          {!loading && (stage === 'start' || stage === 'reading') && (
            <div className="space-y-3">
              <p className="text-xs text-gray-500">{t('demoPractice.privacy')}</p>
              <label className={label}>
                {t('demoPractice.subject')}
                <select value={subject} onChange={(event) => setSubject(event.target.value)} className="mt-1 block w-full rounded-lg border border-gray-200 bg-white px-3 py-2">
                  {packs.map((pack) => <option key={pack.id} value={pack.id}>{pack.display_name}</option>)}
                </select>
              </label>
              {route?.local_available && <p className="text-xs text-sage-800">{t('demoPractice.local')}</p>}
              {usesCloud && (
                <label className="flex items-start gap-2 rounded-lg bg-gold-50 px-3 py-2 text-xs">
                  <input type="checkbox" checked={cloudConsent} onChange={(event) => setCloudConsent(event.target.checked)} className="mt-0.5" />
                  <span>{t('demoPractice.cloud', { provider: route?.cloud_provider ?? '' })}</span>
                </label>
              )}
              {usesCloud && (
                <>
                  <p className="text-xs text-gray-600">{t('demoPractice.cloudRetention', { provider: route?.cloud_provider ?? '' })}</p>
                  <p className="text-xs text-gray-600">{t('demoPractice.cropTip')}</p>
                </>
              )}
              {noReader && <p className="text-xs text-madder-800">{t('demoPractice.noReader')}</p>}
              <label className={label}>
                {t('demoPractice.photos')}
                <input
                  type="file"
                  accept={ACCEPT}
                  multiple
                  aria-label={t('demoPractice.photos')}
                  onChange={(event) => {
                    const picked = Array.from(event.target.files ?? [])
                    const problem = uploadProblem(picked)
                    setError(problem ? t(problem === 'file' ? 'demoPractice.fileTooLarge' : 'demoPractice.uploadTooLarge') : '')
                    setFiles(problem ? [] : picked)
                    event.target.value = ''
                  }}
                  className="mt-1 block w-full text-xs"
                />
              </label>
              <p className="text-xs text-gray-500">{t('demoPractice.photosHint')}</p>
              <button type="button" onClick={() => void read()} disabled={stage === 'reading' || !files.length || !subject || noReader || (usesCloud && !cloudConsent)} className={`${button} bg-navy-700 text-white disabled:opacity-40`}>
                {stage === 'reading' ? t('demoPractice.reading') : t('demoPractice.read')}
              </button>
              <ReadingProgressBar state={progress} />
            </div>
          )}

          {(stage === 'review' || stage === 'planning') && assessment && (
            <div className="space-y-3">
              <p className="font-medium">{t('demoPractice.teacherCount', {
                correct: assessment.sections.flatMap((section) => section.items).filter((item) => item.teacher_mark === 'correct').length,
                total: assessment.sections.flatMap((section) => section.items).filter((item) => item.teacher_mark !== 'unmarked').length,
              })}</p>
              {remaining > 0 && <p role="status" className="rounded-lg bg-gold-50 px-3 py-2 text-xs">{t('demoPractice.checkCount', { count: remaining })}</p>}
              {assessment.sections.map((section, sectionIndex) => (
                <fieldset key={`${section.label}-${sectionIndex}`} className="rounded-xl border border-gray-200 p-3">
                  <legend className="px-1 text-xs font-semibold">{section.label}</legend>
                {section.instructions && <p className="text-xs text-gray-500">{section.instructions}</p>}
                {section.word_bank.length > 0 && <p className="text-xs text-gray-500">{t('demoPractice.wordBank')}: {section.word_bank.join(', ')}</p>}
                  {section.items.map((item, itemIndex) => {
                    const flagged = Boolean(item.ask_parent) || item.confidence < 0.75
                    const itemName = `${section.label} #${item.number}`
                    return (
                      <div key={`${item.number}-${itemIndex}`} className={`mt-2 rounded-lg p-2 ${flagged ? 'bg-gold-50' : 'bg-white'}`}>
                        <p className="text-xs">{item.number}. {item.prompt}{item.stimulus && !item.diagram ? <span className="italic text-gray-500"> ({pictureWords(item.stimulus)})</span> : null}</p>
                        <Diagram d={item.diagram} />
                        <div className="mt-2 flex flex-wrap gap-2">
                          <input aria-label={t('demoPractice.answerFor', { item: itemName })} value={item.student_response ?? ''} onChange={(event) => editItem(sectionIndex, itemIndex, { student_response: event.target.value })} className="min-w-0 flex-1 rounded border border-gray-200 px-2 py-1" />
                          <select aria-label={t('demoPractice.markFor', { item: itemName })} value={item.teacher_mark} onChange={(event) => editItem(sectionIndex, itemIndex, { teacher_mark: event.target.value as typeof item.teacher_mark })} className="rounded border border-gray-200 px-2 py-1">
                            {(['correct', 'incorrect', 'partial', 'unmarked'] as const).map((mark) => <option key={mark} value={mark}>{t(`demoPractice.mark.${mark}`)}</option>)}
                          </select>
                          {item.teacher_mark !== 'correct' && (
                            <input aria-label={t('demoPractice.correctionFor', { item: itemName })} placeholder={t('demoPractice.correction')} value={item.teacher_correction ?? ''} onChange={(event) => editItem(sectionIndex, itemIndex, { teacher_correction: event.target.value || null })} className="min-w-0 flex-1 rounded border border-gray-200 px-2 py-1" />
                          )}
                        </div>
                        {flagged && (
                          <div className="mt-2 flex items-center gap-2 text-xs">
                            <span>{item.ask_parent || t('demoPractice.unsure')}</span>
                            <button type="button" onClick={() => editItem(sectionIndex, itemIndex, { ask_parent: null, confidence: 1 })} className="rounded bg-white px-2 py-1 font-medium text-navy-800 ring-1 ring-navy-100">
                              <Check size={13} className="inline" /> {t('demoPractice.looksRight')}
                            </button>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </fieldset>
              ))}
              <button type="button" onClick={() => void makePlan()} disabled={remaining > 0 || stage === 'planning'} className={`${button} bg-navy-700 text-white disabled:opacity-40`}>
                {stage === 'planning' ? t('demoPractice.planning') : t('demoPractice.confirm')}
              </button>
            </div>
          )}

          {stage === 'plan' && (
            <div className="space-y-3">
              {planSummary && <p className="rounded-lg bg-white p-3 text-xs">{planSummary}</p>}
              {diagnosis && (
                <section aria-label={t('demoPractice.diagnosis')} className="space-y-2 rounded-lg border border-sage-200 p-3 text-xs">
                  <h3 className="font-semibold">{t('demoPractice.diagnosis')}</h3>
                  {diagnosis.errors.some((entry) => entry.audience === 'parent_and_child') && (
                    <div>
                      <h4 className="font-semibold">{t('demoPractice.workOn')}</h4>
                      <ul className="list-disc space-y-1 pl-5">
                      {diagnosis.errors.filter((entry) => entry.audience !== 'parent_only').map((entry, index) => (
                        <li key={`${entry.item_ref}-${index}`}>{entry.item_ref}: {entry.evidence}</li>
                      ))}
                      </ul>
                    </div>
                  )}
                  {diagnosis.errors.some((entry) => entry.audience === 'parent_only') && (
                    <div>
                      <h4 className="font-semibold">{t('demoPractice.forParentOnly')}</h4>
                      <ul className="list-disc space-y-1 pl-5">
                        {diagnosis.errors.filter((entry) => entry.audience === 'parent_only').map((entry, index) => (
                          <li key={`parent-${entry.item_ref}-${index}`}>{entry.item_ref}: {entry.evidence}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {diagnosis.errors.length === 0 && <p>{t('demoPractice.noErrors')}</p>}
                  {diagnosis.strengths.length > 0 && (
                    <div>
                      <h4 className="font-semibold">{t('demoPractice.strengths')}</h4>
                      <ul className="list-disc space-y-1 pl-5">
                        {diagnosis.strengths.map((entry, index) => <li key={`${entry.category}-${index}`}>{entry.note}</li>)}
                      </ul>
                    </div>
                  )}
                  {diagnosis.ask_parent.length > 0 && (
                    <div>
                      <h4 className="font-semibold">{t('demoPractice.parentQuestions')}</h4>
                      {diagnosis.ask_parent.map((question, index) => <p key={`question-${index}`}>{question}</p>)}
                    </div>
                  )}
                </section>
              )}
              {practice ? (
                <>
                  <h3 className="font-semibold">{t('demoPractice.planHeading', { minutes: practice.est_minutes })}</h3>
                  <p className="text-xs text-gray-600">{t('demoPractice.recheck', { dates: practice.recheck_schedule.join(', ') })}</p>
                  <ol className="space-y-2">
                    {practice.items.map((item, index) => (
                      <li key={`${item.target}-${index}`} className="flex gap-2 rounded-lg bg-white p-2 text-xs">
                        <input type="checkbox" checked={keep[index] ?? true} aria-label={t('demoPractice.include', { number: index + 1 })} onChange={(event) => setKeep((items) => items.map((value, itemIndex) => itemIndex === index ? event.target.checked : value))} />
                        <div>
                          <p className="font-medium">{item.prompt}</p>
                          <Diagram d={item.diagram} />
                          <p>{t('demoPractice.answer')}: {item.expected_answer}</p>
                          {item.hint && <p>{t('demoPractice.hint')}: {item.hint}</p>}
                        </div>
                      </li>
                    ))}
                  </ol>
                  <p className="text-xs"><strong>{t('demoPractice.script')}:</strong> {practice.parent_script}</p>
                  <button type="button" onClick={() => void approve()} disabled={saving || !keep.some(Boolean)} className={`${button} bg-sage-700 text-white disabled:opacity-40`}>
                    {saving ? <Loader2 size={15} className="mr-1 inline animate-spin" /> : <Check size={15} className="mr-1 inline" />}
                    {t('demoPractice.approve')}
                  </button>
                  <button type="button" onClick={onClose} disabled={saving} className={`${button} border border-gray-200 text-gray-700`}>
                    {t('demoPractice.discard')}
                  </button>
                </>
              ) : <p>{t('demoPractice.nothingToPractice')}</p>}
            </div>
          )}
          </>}
        </div>
      </div>
    </div>
  )
}
