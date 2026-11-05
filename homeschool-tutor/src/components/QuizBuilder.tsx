import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileQuestion, Loader2, Printer } from 'lucide-react'
import { SOURCE_TEXT_MAX_CHARS, splitIntoParts, uploadProblem } from '../utils/uploadParts'
import Diagram, { diagramMarkup } from './Diagram'
import ReadingProgressBar from './ReadingProgressBar'
import { newProgressId, overallPercent, watchProgress, withProgress, type ProgressState } from '../utils/readingProgress'
import {
  copyEducatorQuizSource,
  copyQuizSource,
  fetchEducatorQuizOptions,
  fetchReadingProgress,
  fetchQuizOptions,
  generateEducatorQuiz,
  generateQuiz,
  type GeneratedQuiz,
  type QuizKind,
  type QuizLevel,
  type QuizOptions,
} from '../services/api'

// HEIC is left out on purpose: iPhones then send a JPEG copy, and the server's
// HEIC decoder is held back until its security fix ships.
const ACCEPT = 'image/jpeg,image/png,image/webp,image/avif,.jpg,.jpeg,.png,.webp,.avif,application/pdf,.pdf'

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const url = String(reader.result)
      const comma = url.indexOf(',')
      resolve(comma >= 0 ? url.slice(comma + 1) : url)
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!))
}

export function optionLines(options: string[]): string[] {
  return options.map((o, i) => `${String.fromCharCode(65 + i)}) ${o}`)
}

/**
 * Make a new quiz or exam for one student from an existing quiz, a previous
 * or prep exam, or a description of the lesson. Bede drafts questions and
 * answers; maths answers are worked out again on the server, everything else
 * is marked to check. Nothing is saved: the parent prints the quiz and the
 * answer key.
 */
export default function QuizBuilder({ token, studentName = '', audience = 'parent', onEdit }: {
  token: string
  studentName?: string
  /** A teacher drafts for a class, on the school's own model only. */
  audience?: 'parent' | 'educator'
  /** Hand the kept questions to the teacher quiz tool, to approve the key and score work. */
  onEdit?: (quiz: GeneratedQuiz) => void
}) {
  const teacher = audience === 'educator'
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [options, setOptions] = useState<QuizOptions | null>(null)
  const [subject, setSubject] = useState('')
  const [grade, setGrade] = useState('3')
  const [kind, setKind] = useState<QuizKind>('quiz')
  const [level, setLevel] = useState<QuizLevel>('on_level')
  const [count, setCount] = useState(10)
  const [focus, setFocus] = useState('')
  const [sourceText, setSourceText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [quiz, setQuiz] = useState<GeneratedQuiz | null>(null)
  const [keep, setKeep] = useState<boolean[]>([])
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!open || options) return
    let active = true
    const load = teacher ? fetchEducatorQuizOptions(token) : fetchQuizOptions(token)
    load
      .then((loaded) => {
        if (!active) return
        setOptions(loaded)
        setSubject((s) => s || loaded.subjects[0]?.id || '')
      })
      .catch(() => { if (active) setMessage(t('quizBuilder.loadError')) })
    return () => { active = false }
  }, [open, options, token, t, teacher])

  // A different child starts over, so one child's quiz never shows on another's page.
  useEffect(() => {
    setQuiz(null); setFiles([]); setSourceText(''); setFocus(''); setConsent(false); setMessage('')
  }, [studentName])

  const route = options?.route
  // Photos follow the photo-reading rules; a typed topic or pasted quiz uses
  // the draft provider, which needs no photo switch but still needs the tick.
  const photosReadable = !!route && (route.local_available || !!route.cloud_provider)
  const provider = files.length ? route?.cloud_provider : route?.draft_provider
  const usesCloud = !!route && !route.local_available && !!provider
  const noReader = !!route && !route.local_available && !provider
  const hasMaterial = files.length > 0 || sourceText.trim() !== '' || focus.trim() !== ''
  const canDraft = !!subject && hasMaterial && !noReader && (!usesCloud || consent) && !busy

  const [progress, setProgress] = useState<ProgressState | null>(null)
  const draft = async () => {
    if (!canDraft) return
    setBusy(true)
    setMessage('')
    try {
      // A source that fits one request goes as pages; a longer one is copied
      // out as text a part at a time, each part's photos read only when sent.
      const parts = splitIntoParts(files)
      let pages: { data: string }[] = []
      let pagesText: string | undefined
      let trimmed = false
      if (parts.length <= 1) {
        pages = await Promise.all(files.map(async (file) => ({ data: await readFile(file) })))
      } else {
        let firstPage = 1
        const texts = await withProgress(parts, async (part, _index, progressId) => {
          const data = await Promise.all(part.map(async (file) => ({ data: await readFile(file) })))
          const piece = { subject, pages: data, cloud_consent: usesCloud && consent, first_page: firstPage, progress_id: progressId }
          const copied = teacher ? await copyEducatorQuizSource(token, piece) : await copyQuizSource(token, studentName, piece)
          firstPage += copied.pages_read
          return copied.text
        }, (id) => fetchReadingProgress(token, id, teacher), setProgress)
        pagesText = texts.join('\n\n')
        trimmed = pagesText.length > SOURCE_TEXT_MAX_CHARS
        pagesText = pagesText.slice(0, SOURCE_TEXT_MAX_CHARS)
      }
      const draftId = newProgressId()
      const body = {
        subject, grade, kind, level, question_count: count,
        focus: focus.trim() || undefined, source_text: sourceText.trim() || undefined,
        pages, source_pages_text: pagesText, cloud_consent: usesCloud && consent, progress_id: draftId,
      }
      if (files.length) setProgress({ stage: pagesText ? 'drafting' : 'sending', done: 0, total: null, part: 1, parts: 1, percent: pagesText ? 95 : 0 })
      const stop = files.length
        ? watchProgress((id) => fetchReadingProgress(token, id, teacher), draftId, (snap) => setProgress((was) => {
          const percent = Math.max(was?.percent ?? 0, overallPercent(1, 1, snap))
          return { ...snap, part: 1, parts: 1, percent }
        }))
        : () => undefined
      let result
      try {
        result = teacher ? await generateEducatorQuiz(token, body) : await generateQuiz(token, studentName, body)
      } finally {
        stop()
      }
      if (trimmed) setMessage(t('quizBuilder.sourceTrimmed'))
      setQuiz(result.quiz)
      setKeep(result.quiz.questions.map(() => true))
    } catch (err) {
      setMessage(err instanceof Error ? err.message : t('quizBuilder.draftError'))
    } finally {
      setProgress(null)
      setBusy(false)
    }
  }

  const chosen = () => quiz ? quiz.questions.filter((_, i) => keep[i]) : []

  const print = (withAnswers: boolean) => {
    const questions = chosen()
    if (!quiz || !questions.length) return
    const win = window.open('', '_blank')
    if (!win) return
    const rows = questions.map((q, i) => {
      const opts = q.options.length ? `<ul>${optionLines(q.options).map((o) => `<li>${escapeHtml(o)}</li>`).join('')}</ul>` : ''
      const tail = withAnswers ? `<p class="ans">${escapeHtml(q.answer)}</p>` : '<div class="line"></div>'
      return `<li><p>${i + 1}. ${escapeHtml(q.prompt)}</p>${diagramMarkup(q.diagram, t)}${opts}${tail}</li>`
    }).join('')
    const heading = withAnswers ? `${quiz.title}: ${t('quizBuilder.answerKey')}` : quiz.title
    win.document.write(`<!doctype html><meta charset="utf-8"><title>${escapeHtml(heading)}</title>
<style>body{font-family:Georgia,serif;margin:2rem;color:#1d2433}ol{list-style:none;padding:0}li{margin:0 0 1.2rem}ul{list-style:none;padding-left:1rem}.line{border-bottom:1px solid #999;height:2rem}.ans{font-weight:bold}</style>
<h1>${escapeHtml(heading)}</h1><ol>${rows}</ol>`)
    win.document.close()
    win.print()
  }

  const field = 'mt-1 block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm'
  const label = 'block text-xs font-medium text-gray-600'
  const button = 'inline-flex min-h-[44px] items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-medium'

  return (
    <section className="rounded-2xl border border-sage-100 bg-white p-4 sm:p-5 shadow-sm" aria-label={t('quizBuilder.title')}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <FileQuestion size={18} className="mt-0.5 text-sage-700" aria-hidden />
          <div>
            <h2 className="font-display text-base font-semibold text-gray-800">{t('quizBuilder.title')}</h2>
            <p className="text-xs text-gray-500">{t(teacher ? 'quizBuilder.teacherDescription' : 'quizBuilder.description')}</p>
          </div>
        </div>
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
          className={`${button} border border-sage-200 text-sage-800 hover:bg-sage-50`}>
          {open ? t('quizBuilder.close') : t('quizBuilder.open')}
        </button>
      </div>

      {open && (
        <div className="mt-4 space-y-3 text-sm text-gray-700">
          {message && <p role="alert" className="rounded-lg bg-madder-50 px-3 py-2 text-madder-800">{message}</p>}
          {!options && !message && <p role="status">{t('quizBuilder.loading')}</p>}

          {options && !quiz && (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <label className={label}>{t('quizBuilder.subject')}
                  <select value={subject} onChange={(e) => setSubject(e.target.value)} className={field}>
                    {options.subjects.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
                  </select>
                </label>
                <label className={label}>{t('quizBuilder.grade')}
                  <select value={grade} onChange={(e) => setGrade(e.target.value)} className={field}>
                    {options.grades.map((g) => <option key={g} value={g}>{g === 'K' ? t('quizBuilder.kindergarten') : t('quizBuilder.gradeN', { grade: g })}</option>)}
                  </select>
                </label>
                <label className={label}>{t('quizBuilder.kind')}
                  <select value={kind} onChange={(e) => setKind(e.target.value as QuizKind)} className={field}>
                    {options.kinds.map((k) => <option key={k} value={k}>{t(`quizBuilder.kinds.${k}`)}</option>)}
                  </select>
                </label>
                <label className={label}>{t('quizBuilder.level')}
                  <select value={level} onChange={(e) => setLevel(e.target.value as QuizLevel)} className={field}>
                    {options.levels.map((l) => <option key={l} value={l}>{t(`quizBuilder.levels.${l}`)}</option>)}
                  </select>
                </label>
                <label className={label}>{t('quizBuilder.count')}
                  <input type="number" min={1} max={options.max_questions} value={count}
                    onChange={(e) => setCount(Math.max(1, Math.min(options.max_questions, Number(e.target.value) || 1)))}
                    className={field} />
                </label>
              </div>
              <label className={label}>{t('quizBuilder.focus')}
                <input value={focus} onChange={(e) => setFocus(e.target.value)} placeholder={t('quizBuilder.focusPlaceholder')} className={field} />
              </label>
              <label className={label}>{t('quizBuilder.source')}
                <textarea value={sourceText} onChange={(e) => setSourceText(e.target.value)} rows={3} className={field} />
              </label>
              <label className={label}>{t('quizBuilder.pages')}
                <input type="file" accept={ACCEPT} multiple aria-label={t('quizBuilder.pages')}
                  disabled={!photosReadable}
                  onChange={(e) => {
                    const picked = Array.from(e.target.files ?? [])
                    const problem = uploadProblem(picked)
                    setMessage(problem ? t(problem === 'file' ? 'quizBuilder.fileTooLarge' : 'quizBuilder.uploadTooLarge') : '')
                    setFiles(problem ? [] : picked); e.target.value = ''
                  }}
                  className="mt-1 block w-full text-xs" />
              </label>
              {!photosReadable && !noReader && <p className="text-xs text-gray-600">{t('quizBuilder.noPhotos')}</p>}
              {files.length > 0 && <p className="text-xs text-gray-500">{t('quizBuilder.pagesChosen', { count: files.length })}</p>}
              {usesCloud && (
                <label className="flex items-start gap-2 rounded-lg bg-gold-50 px-3 py-2 text-xs">
                  <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5" />
                  <span>{t('quizBuilder.cloud', { provider: provider ?? '' })}</span>
                </label>
              )}
              {usesCloud && files.length > 0 && (
                <>
                  <p className="text-xs text-gray-600">{t('practiceCoach.cloudRetention', { provider: provider ?? '' })}</p>
                  <p className="text-xs text-gray-600">{t('practiceCoach.cropTip')}</p>
                </>
              )}
              {noReader && <p className="text-xs text-madder-800">{t(teacher ? 'quizBuilder.noLocalModel' : 'quizBuilder.noReader')}</p>}
              <button type="button" onClick={() => void draft()} disabled={!canDraft}
                className={`${button} bg-navy-700 text-white disabled:opacity-40`}>
                {busy ? <><Loader2 size={15} className="animate-spin" />{t('quizBuilder.drafting')}</> : t('quizBuilder.draft')}
              </button>
              <ReadingProgressBar state={progress} />
            </>
          )}

          {quiz && (
            <>
              <h3 className="font-semibold text-gray-800">{quiz.title}</h3>
              <p className="text-xs text-gray-600">
                {t('quizBuilder.summary', { count: quiz.questions.length, minutes: quiz.est_minutes })}
                {quiz.coverage.length > 0 && <> · {quiz.coverage.join(', ')}</>}
              </p>
              <p className="text-xs text-gray-600">{t('quizBuilder.checkNote')}</p>
              <ol className="space-y-2">
                {quiz.questions.map((q, index) => (
                  <li key={q.number} className="flex gap-2 rounded-lg border border-gray-100 p-2 text-xs">
                    <input type="checkbox" checked={keep[index] ?? true}
                      aria-label={t('quizBuilder.include', { number: q.number })}
                      onChange={(e) => setKeep((v) => v.map((x, i) => i === index ? e.target.checked : x))} />
                    <div className="min-w-0 flex-1 space-y-1">
                      <p className="font-medium">{q.number}. {q.prompt}</p>
                      <Diagram d={q.diagram} />
                      {q.options.length > 0 && <p className="whitespace-pre-line text-gray-600">{optionLines(q.options).join('\n')}</p>}
                      <label className="flex items-center gap-2">
                        <span>{t('quizBuilder.answer')}</span>
                        <input value={q.answer} aria-label={t('quizBuilder.answerFor', { number: q.number })}
                          onChange={(e) => setQuiz((prev) => prev && { ...prev, questions: prev.questions.map((x, i) => i === index ? { ...x, answer: e.target.value } : x) })}
                          className="min-w-0 flex-1 rounded border border-gray-200 px-2 py-1" />
                        <span className={q.answer_check === 'verify' ? 'text-gold-800' : 'text-sage-700'}>
                          {t(`quizBuilder.status.${q.answer_check}`)}
                        </span>
                      </label>
                      {q.second_answer && <p className="text-gold-800">{t('quizBuilder.secondAnswer', { answer: q.second_answer })}</p>}
                    </div>
                  </li>
                ))}
              </ol>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => print(false)} disabled={!keep.some(Boolean)}
                  className={`${button} bg-sage-700 text-white disabled:opacity-40`}>
                  <Printer size={15} />{t('quizBuilder.printQuiz')}
                </button>
                <button type="button" onClick={() => print(true)} disabled={!keep.some(Boolean)}
                  className={`${button} border border-gray-200 text-gray-700 disabled:opacity-40`}>
                  <Printer size={15} />{t('quizBuilder.printKey')}
                </button>
                <button type="button" onClick={() => setQuiz(null)} className={`${button} border border-gray-200 text-gray-700`}>
                  {t('quizBuilder.again')}
                </button>
                {onEdit && (
                  <button type="button" disabled={!keep.some(Boolean)}
                    onClick={() => quiz && onEdit({ ...quiz, questions: chosen() })}
                    className={`${button} border border-sage-200 text-sage-800 disabled:opacity-40`}>
                    {t('quizBuilder.editAsTeacher')}
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  )
}
