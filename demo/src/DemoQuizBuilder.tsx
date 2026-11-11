import { useEffect, useState } from 'react'
import { providerName } from './providerName'
import { useTranslation } from 'react-i18next'
import { Check, Loader2, Printer } from 'lucide-react'
import { SOURCE_TEXT_MAX_CHARS, splitIntoParts, uploadProblem } from './uploadParts'
import Diagram, { diagramMarkup } from './Diagram'
import { printSheet } from './printDocument'
import ReadingProgressBar from './ReadingProgressBar'
import { newProgressId, overallPercent, watchProgress, withProgress, type ProgressState } from './readingProgress'
import type { DiagramSpec } from './Diagram'
import {
  copyDemoQuizSource,
  fetchDemoReadingProgress,
  fetchDemoQuizOptions,
  generateDemoQuiz,
  quizPrompt,
  type GeneratedQuiz,
  type QuizKind,
  type QuizLevel,
  type QuizOptions,
} from './api'

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

/**
 * Make a new quiz or exam from an existing one. Bede drafts the questions and
 * answers; maths answers are worked out again on the server and everything
 * else is marked for the adult to check. Nothing reaches the student until
 * the adult approves it here.
 */
export default function DemoQuizBuilder({
  token,
  onApproved,
}: {
  token: string
  onApproved: (items: { index: number; prompt: string; hint: string; diagram?: DiagramSpec | null }[]) => void
}) {
  const { t } = useTranslation()
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
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    fetchDemoQuizOptions(token)
      .then((loaded) => {
        if (!active) return
        setOptions(loaded)
        setSubject(loaded.subjects[0]?.id ?? '')
      })
      .catch(() => { if (active) setError(t('demoQuiz.loadError')) })
    return () => { active = false }
  }, [token, t])

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
    setError('')
    try {
      // A source that fits one request goes as pages; a longer one is copied
      // out as text a part at a time (each six pages is one demo message).
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
          const copied = await copyDemoQuizSource(token, {
            subject, pages: data, cloud_consent: usesCloud && consent, first_page: firstPage, progress_id: progressId,
          })
          firstPage += copied.pages_read
          return copied.text
        }, (id) => fetchDemoReadingProgress(token, id), setProgress)
        pagesText = texts.join('\n\n')
        trimmed = pagesText.length > SOURCE_TEXT_MAX_CHARS
        pagesText = pagesText.slice(0, SOURCE_TEXT_MAX_CHARS)
      }
      const draftId = newProgressId()
      if (files.length) setProgress({ stage: pagesText ? 'drafting' : 'sending', done: 0, total: null, part: 1, parts: 1, percent: pagesText ? 95 : 0 })
      const stop = files.length
        ? watchProgress((id) => fetchDemoReadingProgress(token, id), draftId, (snap) => setProgress((was) => {
          const percent = Math.max(was?.percent ?? 0, overallPercent(1, 1, snap))
          return { ...snap, part: 1, parts: 1, percent }
        }))
        : () => undefined
      let result
      try {
        result = await generateDemoQuiz(token, {
          subject, grade, kind, level, question_count: count,
          focus: focus.trim() || undefined,
          source_text: sourceText.trim() || undefined,
          pages,
          source_pages_text: pagesText,
          cloud_consent: usesCloud && consent,
          progress_id: draftId,
        })
      } finally {
        stop()
      }
      if (trimmed) setError(t('demoQuiz.sourceTrimmed'))
      setQuiz(result.quiz)
      setKeep(result.quiz.questions.map(() => true))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t('demoQuiz.draftError'))
    } finally {
      setProgress(null)
      setBusy(false)
    }
  }

  const editAnswer = (index: number, answer: string) => {
    setQuiz((previous) => previous && {
      ...previous,
      questions: previous.questions.map((q, i) => i === index ? { ...q, answer } : q),
    })
  }

  const approve = () => {
    if (!quiz) return
    const items = quiz.questions
      .filter((_, i) => keep[i])
      .map((q, index) => ({ index, prompt: quizPrompt(q), hint: '', ...(q.diagram ? { diagram: q.diagram } : {}) }))
    if (items.length) onApproved(items)
  }

  const print = async (withAnswers: boolean) => {
    if (!quiz) return
    const questions = quiz.questions.filter((_, i) => keep[i])
    if (!questions.length) return
    const started = await printSheet({
      title: quiz.title,
      items: questions.map((q) => ({
        prompt: q.prompt,
        options: q.options,
        diagramHtml: diagramMarkup(q.diagram, t),
        answer: q.answer,
      })),
      labels: { name: t('printSheet.name'), date: t('printSheet.date'), keyTitle: `${quiz.title}: ${t('demoQuiz.answerKey')}` },
      copies: [withAnswers ? 'key' : 'student'],
    })
    if (!started) setError(t('printSheet.failed'))
  }

  const label = 'block text-xs font-medium text-gray-600'
  const field = 'mt-1 block w-full rounded-lg border border-gray-200 bg-white px-3 py-2'
  const button = 'min-h-[44px] rounded-lg px-4 py-2 text-sm font-medium'

  if (!options) {
    return error
      ? <p role="alert" className="rounded-lg bg-madder-50 px-3 py-2 text-madder-800">{error}</p>
      : <p role="status">{t('demoQuiz.loading')}</p>
  }

  if (quiz) {
    return (
      <div className="space-y-3">
        <h3 className="font-semibold">{quiz.title}</h3>
        <p className="text-xs text-gray-600">
          {t('demoQuiz.summary', { count: quiz.questions.length, minutes: quiz.est_minutes })}
          {quiz.coverage.length > 0 && <> · {quiz.coverage.join(', ')}</>}
        </p>
        <p className="text-xs text-gray-600">{t('demoQuiz.checkNote')}</p>
        <ol className="space-y-2">
          {quiz.questions.map((q, index) => (
            <li key={q.number} className="flex gap-2 rounded-lg bg-white p-2 text-xs">
              <input
                type="checkbox"
                checked={keep[index] ?? true}
                aria-label={t('demoQuiz.include', { number: q.number })}
                onChange={(event) => setKeep((values) => values.map((v, i) => i === index ? event.target.checked : v))}
              />
              <div className="min-w-0 flex-1 space-y-1">
                <p className="whitespace-pre-line font-medium">{q.number}. {quizPrompt(q)}</p>
                <Diagram d={q.diagram} />
                <label className="flex items-center gap-2">
                  <span>{t('demoQuiz.answer')}</span>
                  <input
                    value={q.answer}
                    aria-label={t('demoQuiz.answerFor', { number: q.number })}
                    onChange={(event) => editAnswer(index, event.target.value)}
                    className="min-w-0 flex-1 rounded border border-gray-200 px-2 py-1"
                  />
                  <span className={q.answer_check === 'verify' ? 'text-gold-800' : 'text-sage-700'}>
                    {t(`demoQuiz.status.${q.answer_check}`)}
                  </span>
                </label>
                {q.second_answer && <p className="text-gold-800">{t('demoQuiz.secondAnswer', { answer: q.second_answer })}</p>}
              </div>
            </li>
          ))}
        </ol>
        {error && <p role="alert" className="rounded-lg bg-madder-50 px-3 py-2 text-madder-800">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={approve} disabled={!keep.some(Boolean)} className={`${button} bg-sage-700 text-white disabled:opacity-40`}>
            <Check size={15} className="mr-1 inline" />{t('demoQuiz.approve')}
          </button>
          <button type="button" onClick={() => void print(false)} disabled={!keep.some(Boolean)} className={`${button} border border-gray-200 text-gray-700 disabled:opacity-40`}>
            <Printer size={15} className="mr-1 inline" />{t('demoQuiz.printQuiz')}
          </button>
          <button type="button" onClick={() => void print(true)} disabled={!keep.some(Boolean)} className={`${button} border border-gray-200 text-gray-700 disabled:opacity-40`}>
            <Printer size={15} className="mr-1 inline" />{t('demoQuiz.printKey')}
          </button>
          <button type="button" onClick={() => setQuiz(null)} className={`${button} border border-gray-200 text-gray-700`}>
            {t('demoQuiz.again')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {error && <p role="alert" className="rounded-lg bg-madder-50 px-3 py-2 text-madder-800">{error}</p>}
      <div className="grid grid-cols-2 gap-3">
        <label className={label}>
          {t('demoQuiz.subject')}
          <select value={subject} onChange={(event) => setSubject(event.target.value)} className={field}>
            {options.subjects.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
          </select>
        </label>
        <label className={label}>
          {t('demoQuiz.grade')}
          <select value={grade} onChange={(event) => setGrade(event.target.value)} className={field}>
            {options.grades.map((g) => <option key={g} value={g}>{g === 'K' ? t('demoQuiz.kindergarten') : t('demoQuiz.gradeN', { grade: g })}</option>)}
          </select>
        </label>
        <label className={label}>
          {t('demoQuiz.kind')}
          <select value={kind} onChange={(event) => setKind(event.target.value as QuizKind)} className={field}>
            {options.kinds.map((k) => <option key={k} value={k}>{t(`demoQuiz.kinds.${k}`)}</option>)}
          </select>
        </label>
        <label className={label}>
          {t('demoQuiz.level')}
          <select value={level} onChange={(event) => setLevel(event.target.value as QuizLevel)} className={field}>
            {options.levels.map((l) => <option key={l} value={l}>{t(`demoQuiz.levels.${l}`)}</option>)}
          </select>
        </label>
        <label className={label}>
          {t('demoQuiz.count')}
          <input
            type="number"
            min={1}
            max={options.max_questions}
            value={count}
            onChange={(event) => setCount(Math.max(1, Math.min(options.max_questions, Number(event.target.value) || 1)))}
            className={field}
          />
        </label>
      </div>
      <label className={label}>
        {t('demoQuiz.focus')}
        <input value={focus} onChange={(event) => setFocus(event.target.value)} placeholder={t('demoQuiz.focusPlaceholder')} className={field} />
      </label>
      <label className={label}>
        {t('demoQuiz.source')}
        <textarea value={sourceText} onChange={(event) => setSourceText(event.target.value)} rows={3} className={field} />
      </label>
      <label className={label}>
        {t('demoQuiz.pages')}
        <input
          type="file"
          accept={ACCEPT}
          multiple
          aria-label={t('demoQuiz.pages')}
          disabled={!photosReadable}
          onChange={(event) => {
            const picked = Array.from(event.target.files ?? [])
            const problem = uploadProblem(picked)
            setError(problem ? t(problem === 'file' ? 'demoQuiz.fileTooLarge' : 'demoQuiz.uploadTooLarge') : '')
            setFiles(problem ? [] : picked)
            event.target.value = ''
          }}
          className="mt-1 block w-full text-xs"
        />
      </label>
      {!photosReadable && !noReader && <p className="text-xs text-gray-600">{t('demoQuiz.noPhotos')}</p>}
      {files.length > 0 && <p className="text-xs text-gray-500">{t('demoQuiz.pagesChosen', { count: files.length })}</p>}
      {usesCloud && (
        <label className="flex items-start gap-2 rounded-lg bg-gold-50 px-3 py-2 text-xs">
          <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} className="mt-0.5" />
          <span>{t('demoQuiz.cloud', { provider: providerName(provider) })}</span>
        </label>
      )}
      {usesCloud && files.length > 0 && (
        <>
          <p className="text-xs text-gray-600">{t('demoPractice.cloudRetention', { provider: providerName(provider) })}</p>
          <p className="text-xs text-gray-600">{t('demoPractice.cropTip')}</p>
        </>
      )}
      {noReader && <p className="text-xs text-madder-800">{t('demoQuiz.noReader')}</p>}
      <button type="button" onClick={() => void draft()} disabled={!canDraft} className={`${button} bg-navy-700 text-white disabled:opacity-40`}>
        {busy ? <><Loader2 size={15} className="mr-1 inline animate-spin" />{t('demoQuiz.drafting')}</> : t('demoQuiz.draft')}
      </button>
              <ReadingProgressBar state={progress} />
    </div>
  )
}
