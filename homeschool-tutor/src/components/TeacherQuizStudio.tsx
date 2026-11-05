import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, ClipboardList, Download, Loader2, Printer, Upload } from 'lucide-react'
import {
  approveTeacherQuiz,
  extractTeacherQuiz,
  fetchEducatorQuizOptions,
  finalizeTeacherQuiz,
  reviewTeacherQuiz,
  scoreTeacherQuiz,
  TeacherQuizProblems,
  type ProposedScore,
  type QuestionType,
  type QuizOptions,
  type QuizProblem,
  type TeacherQuiz,
} from '../services/api'
import {
  addQuestion,
  allSettled,
  blankQuiz,
  editQuestion,
  exportFile,
  initialSettlement,
  needsLook,
  parseImport,
  removeQuestion,
  settleQuestion,
} from '../utils/teacherQuiz'

const ACCEPT = 'image/jpeg,image/png,image/heic,image/heif,application/pdf,.pdf,.heic,.heif'
const MAX_PAGES = 6
const TYPES: QuestionType[] = ['multiple_choice', 'true_false', 'short_answer', 'fill_in_blank', 'computation', 'written_response']
const GRADES = ['K', '1', '2', '3', '4', '5', '6', '7', '8']

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

function readText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(file)
  })
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!))
}

const lines = (text: string) => text.split('\n').map((s) => s.trim()).filter(Boolean)

/**
 * A teacher's own quiz with a reviewable answer key, then scoring one
 * student's completed work against it. Everything is read on the school's own
 * AI model, nothing is stored, and no learner is named: the teacher keeps the
 * quiz as a file and writes the student's name on the printout by hand.
 */
export default function TeacherQuizStudio({ token, incoming }: {
  token: string
  /** A quiz handed over from the drafting tool, to edit and score here. */
  incoming?: TeacherQuiz | null
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [options, setOptions] = useState<QuizOptions | null>(null)
  const [quiz, setQuiz] = useState<TeacherQuiz | null>(null)
  const [problems, setProblems] = useState<QuizProblem[]>([])
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  // Starting a quiz
  const [subject, setSubject] = useState('')
  const [grade, setGrade] = useState('3')
  const [title, setTitle] = useState('')
  const [sourceText, setSourceText] = useState('')
  const [quizFiles, setQuizFiles] = useState<File[]>([])
  const [quizConsent, setQuizConsent] = useState(false)
  // Scoring a student's work: kept apart from the quiz and its key
  const [scoring, setScoring] = useState(false)
  const [workFiles, setWorkFiles] = useState<File[]>([])
  const [workConsent, setWorkConsent] = useState(false)
  const [typed, setTyped] = useState<Record<number, string>>({})
  const [results, setResults] = useState<ProposedScore[] | null>(null)
  const [settled, setSettled] = useState<Record<number, number | null>>({})
  const [final, setFinal] = useState<{ total: number; possible: number } | null>(null)

  useEffect(() => {
    if (!open || options) return
    let active = true
    fetchEducatorQuizOptions(token)
      .then((loaded) => {
        if (!active) return
        setOptions(loaded)
        setSubject((s) => s || loaded.subjects[0]?.id || '')
      })
      .catch(() => { if (active) setMessage(t('teacherQuiz.loadError')) })
    return () => { active = false }
  }, [open, options, token, t])

  const subjects = options?.subjects ?? []
  // Everything here runs on the school's own model; without one, say so up front.
  const noLocal = !!options && !options.route.local_available

  useEffect(() => {
    if (!incoming) return
    setOpen(true)
    setQuiz(incoming)
    setProblems([])
    resetScoring()
  }, [incoming])

  function resetScoring() {
    setScoring(false); setWorkFiles([]); setWorkConsent(false); setTyped({})
    setResults(null); setSettled({}); setFinal(null)
  }

  const fail = (err: unknown, fallback: string) => {
    if (err instanceof TeacherQuizProblems) {
      setProblems(err.problems)
      setMessage(t('teacherQuiz.problemsFound'))
    } else {
      setMessage(err instanceof Error && err.message ? err.message : t(fallback))
    }
  }

  const update = (next: TeacherQuiz) => {
    setQuiz(next)
    setProblems([])
    resetScoring()
  }

  const startBlank = () => {
    if (!subject) return
    update(blankQuiz(subject, grade, title.trim() || t('teacherQuiz.untitled')))
  }

  const readQuiz = async () => {
    if (!subject || (!quizFiles.length && !sourceText.trim())) return
    setBusy(true); setMessage('')
    try {
      const pages = await Promise.all(quizFiles.map(async (f) => ({ data: await readFile(f) })))
      const out = await extractTeacherQuiz(token, {
        subject, grade, pages, source_text: sourceText.trim() || undefined, upload_consent: quizConsent,
      })
      update(out.quiz)
      setProblems(out.problems)
      setQuizFiles([]); setQuizConsent(false); setSourceText('')
    } catch (err) {
      fail(err, 'teacherQuiz.readError')
    } finally {
      setBusy(false)
    }
  }

  const importFile = async (file: File | undefined) => {
    if (!file) return
    setMessage('')
    const parsed = parseImport(await readText(file))
    if (!parsed) { setMessage(t('teacherQuiz.importError')); return }
    try {
      const out = await reviewTeacherQuiz(token, parsed)
      update(out.quiz)
      setProblems(out.problems)
    } catch {
      setMessage(t('teacherQuiz.importError'))
    }
  }

  const approve = async () => {
    if (!quiz) return
    setBusy(true); setMessage('')
    try {
      const out = await approveTeacherQuiz(token, quiz)
      setQuiz(out.quiz)
      setProblems([])
    } catch (err) {
      fail(err, 'teacherQuiz.approveError')
    } finally {
      setBusy(false)
    }
  }

  const discard = () => {
    setQuiz(null); setProblems([]); setMessage(''); resetScoring()
  }

  const download = () => {
    if (!quiz) return
    const blob = new Blob([exportFile(quiz)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${quiz.title.replace(/[^\w-]+/g, '_') || 'quiz'}.bede-quiz.json`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }

  const printDoc = (heading: string, body: string) => {
    const win = window.open('', '_blank')
    if (!win) return
    win.document.write(`<!doctype html><meta charset="utf-8"><title>${escapeHtml(heading)}</title>
<style>body{font-family:Georgia,serif;margin:2rem;color:#1d2433}ol{list-style:none;padding:0}li{margin:0 0 1.2rem}ul{list-style:none;padding-left:1rem}.line{border-bottom:1px solid #999;height:2rem}.ans{font-weight:bold}.small{font-size:.85rem;color:#444}</style>
<h1>${escapeHtml(heading)}</h1>${body}`)
    win.document.close()
    win.print()
  }

  const printQuiz = (withKey: boolean) => {
    if (!quiz) return
    const rows = quiz.questions.map((q) => {
      const stim = q.stimulus ? `<p class="small">${escapeHtml(q.stimulus)}</p>` : ''
      const opts = q.options.length
        ? `<ul>${q.options.map((o, i) => `<li>${String.fromCharCode(65 + i)}) ${escapeHtml(o)}</li>`).join('')}</ul>` : ''
      let tail = '<div class="line"></div>'
      if (withKey) {
        tail = `<p class="ans">${escapeHtml(q.answer || '—')}</p>`
        if (q.accepted_answers.length) tail += `<p class="small">${escapeHtml(t('teacherQuiz.alsoAccept'))}: ${escapeHtml(q.accepted_answers.join('; '))}</p>`
        if (q.rubric) tail += `<p class="small">${escapeHtml(t('teacherQuiz.rubric'))}: ${escapeHtml(q.rubric)}</p>`
        if (q.scoring_guidance) tail += `<p class="small">${escapeHtml(q.scoring_guidance)}</p>`
      }
      const pts = t('teacherQuiz.pointsN', { count: q.points })
      return `<li><p>${q.number}. ${escapeHtml(q.prompt)} <span class="small">(${escapeHtml(pts)})</span></p>${stim}${opts}${tail}</li>`
    }).join('')
    const nameLine = withKey ? '' : `<p>${escapeHtml(t('teacherQuiz.nameLine'))} ____________________</p>`
    printDoc(withKey ? `${quiz.title}: ${t('teacherQuiz.answerKey')}` : quiz.title, `${nameLine}<ol>${rows}</ol>`)
  }

  const printResults = () => {
    if (!quiz || !results || !final) return
    const rows = results.map((r) => {
      const q = quiz.questions.find((x) => x.number === r.number)
      return `<li>${r.number}. ${escapeHtml(q?.prompt ?? '')}<br><span class="small">${escapeHtml(r.response ?? '—')}</span> · <b>${settled[r.number]} / ${r.max_points}</b></li>`
    }).join('')
    printDoc(`${quiz.title}: ${t('teacherQuiz.results')}`,
      `<p>${escapeHtml(t('teacherQuiz.nameLine'))} ____________________</p><ol>${rows}</ol><p><b>${escapeHtml(t('teacherQuiz.total', { total: final.total, possible: final.possible }))}</b></p>`)
  }

  const score = async () => {
    if (!quiz) return
    setBusy(true); setMessage('')
    try {
      const responses = workFiles.length ? [] : quiz.questions
        .filter((q) => (typed[q.number] ?? '').trim())
        .map((q) => ({ number: q.number, response: typed[q.number].trim() }))
      const pages = await Promise.all(workFiles.map(async (f) => ({ data: await readFile(f) })))
      const out = await scoreTeacherQuiz(token, { quiz, pages, responses, upload_consent: workConsent })
      setResults(out.results)
      setSettled(initialSettlement(out.results))
      setFinal(null)
      setWorkFiles([]); setWorkConsent(false)
    } catch (err) {
      fail(err, 'teacherQuiz.scoreError')
    } finally {
      setBusy(false)
    }
  }

  const finalize = async () => {
    if (!quiz || !results) return
    setBusy(true); setMessage('')
    try {
      const out = await finalizeTeacherQuiz(token, {
        quiz, results: results.map((r) => ({ number: r.number, points: settled[r.number] ?? null })),
      })
      setFinal({ total: out.total, possible: out.possible })
    } catch (err) {
      fail(err, 'teacherQuiz.finalizeError')
    } finally {
      setBusy(false)
    }
  }

  const nextStudent = () => { setResults(null); setSettled({}); setFinal(null); setTyped({}) }

  const field = 'mt-1 block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm'
  const label = 'block text-xs font-medium text-gray-600'
  const button = 'inline-flex min-h-[44px] items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-medium'
  const quiet = `${button} border border-gray-200 text-gray-700 disabled:opacity-40`
  const problemText = (p: QuizProblem) => p.number
    ? t('teacherQuiz.problemFor', { number: p.number, problem: t(`teacherQuiz.problems.${p.problem}`, { defaultValue: p.problem }) })
    : t(`teacherQuiz.problems.${p.problem}`, { defaultValue: p.problem })

  return (
    <section className="rounded-2xl border border-sage-100 bg-white p-4 sm:p-5 shadow-sm" aria-label={t('teacherQuiz.title')}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <ClipboardList size={18} className="mt-0.5 text-sage-700" aria-hidden />
          <div>
            <h2 className="font-display text-base font-semibold text-gray-800">{t('teacherQuiz.title')}</h2>
            <p className="text-xs text-gray-500">{t('teacherQuiz.description')}</p>
          </div>
        </div>
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
          className={`${button} border border-sage-200 text-sage-800 hover:bg-sage-50`}>
          {open ? t('teacherQuiz.close') : t('teacherQuiz.open')}
        </button>
      </div>

      {open && (
        <div className="mt-4 space-y-3 text-sm text-gray-700">
          <p className="text-xs text-gray-600">{t('teacherQuiz.privacy')}</p>
          {noLocal && <p className="text-xs text-madder-800">{t('teacherQuiz.noLocalModel')}</p>}
          {message && <p role="alert" className="rounded-lg bg-madder-50 px-3 py-2 text-madder-800">{message}</p>}
          {problems.length > 0 && (
            <ul aria-label={t('teacherQuiz.problemsFound')} className="list-disc rounded-lg bg-gold-50 py-2 pl-6 pr-3 text-xs text-gold-900">
              {problems.map((p, i) => <li key={i}>{problemText(p)}</li>)}
            </ul>
          )}

          {!quiz && (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <label className={label}>{t('teacherQuiz.subject')}
                  <select value={subject} onChange={(e) => setSubject(e.target.value)} className={field}>
                    {subjects.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
                  </select>
                </label>
                <label className={label}>{t('teacherQuiz.grade')}
                  <select value={grade} onChange={(e) => setGrade(e.target.value)} className={field}>
                    {GRADES.map((g) => <option key={g} value={g}>{g === 'K' ? t('quizBuilder.kindergarten') : t('quizBuilder.gradeN', { grade: g })}</option>)}
                  </select>
                </label>
                <label className={label}>{t('teacherQuiz.quizTitle')}
                  <input value={title} onChange={(e) => setTitle(e.target.value)} className={field} />
                </label>
              </div>
              <button type="button" onClick={startBlank} disabled={!subject} className={`${button} bg-navy-700 text-white disabled:opacity-40`}>
                {t('teacherQuiz.writeNew')}
              </button>

              <div className="space-y-2 rounded-lg border border-gray-100 p-3">
                <p className="font-medium text-gray-800">{t('teacherQuiz.readHeading')}</p>
                <label className={label}>{t('teacherQuiz.paste')}
                  <textarea value={sourceText} onChange={(e) => setSourceText(e.target.value)} rows={3} className={field} />
                </label>
                <label className={label}>{t('teacherQuiz.quizPages', { max: MAX_PAGES })}
                  <input type="file" accept={ACCEPT} multiple aria-label={t('teacherQuiz.quizPages', { max: MAX_PAGES })}
                    onChange={(e) => { setQuizFiles(Array.from(e.target.files ?? []).slice(0, MAX_PAGES)); e.target.value = '' }}
                    className="mt-1 block w-full text-xs" />
                </label>
                {quizFiles.length > 0 && (
                  <>
                    <p className="text-xs text-gray-500">{t('teacherQuiz.filesChosen', { count: quizFiles.length })}</p>
                    <label className="flex items-start gap-2 rounded-lg bg-gold-50 px-3 py-2 text-xs">
                      <input type="checkbox" checked={quizConsent} onChange={(e) => setQuizConsent(e.target.checked)} className="mt-0.5" />
                      <span>{t('teacherQuiz.uploadConsent')}</span>
                    </label>
                  </>
                )}
                <button type="button" onClick={() => void readQuiz()}
                  disabled={busy || noLocal || !subject || (!quizFiles.length && !sourceText.trim()) || (quizFiles.length > 0 && !quizConsent)}
                  className={`${button} bg-sage-700 text-white disabled:opacity-40`}>
                  {busy ? <><Loader2 size={15} className="animate-spin" />{t('teacherQuiz.reading')}</> : t('teacherQuiz.read')}
                </button>
              </div>

              <label className={`${quiet} cursor-pointer`}>
                <Upload size={15} />{t('teacherQuiz.import')}
                <input type="file" accept="application/json,.json" className="sr-only" aria-label={t('teacherQuiz.import')}
                  onChange={(e) => { void importFile(e.target.files?.[0]); e.target.value = '' }} />
              </label>
            </>
          )}

          {quiz && !scoring && (
            <>
              <label className={label}>{t('teacherQuiz.quizTitle')}
                <input value={quiz.title} onChange={(e) => update({ ...quiz, title: e.target.value, approved: false })} className={field} />
              </label>
              <p className="text-xs text-gray-600">{t('teacherQuiz.reviewNote')}</p>
              <ol className="space-y-3">
                {quiz.questions.map((q, index) => {
                  const set = (patch: Parameters<typeof editQuestion>[2]) => update(editQuestion(quiz, index, patch))
                  const look = needsLook(q)
                  return (
                    <li key={index} className={`space-y-2 rounded-lg border p-3 text-xs ${look ? 'border-gold-300 bg-gold-50' : 'border-gray-100'}`}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold">{q.number}.</span>
                        <select value={q.type} aria-label={t('teacherQuiz.typeFor', { number: q.number })}
                          onChange={(e) => set({ type: e.target.value as QuestionType })} className="rounded border border-gray-200 px-2 py-1">
                          {TYPES.map((ty) => <option key={ty} value={ty}>{t(`teacherQuiz.types.${ty}`)}</option>)}
                        </select>
                        <label className="flex items-center gap-1">{t('teacherQuiz.points')}
                          <input type="number" min={1} max={20} value={q.points} aria-label={t('teacherQuiz.pointsFor', { number: q.number })}
                            onChange={(e) => set({ points: Math.max(1, Math.min(20, Number(e.target.value) || 1)) })}
                            className="w-16 rounded border border-gray-200 px-2 py-1" />
                        </label>
                        <span data-testid={`source-${q.number}`}
                          className={q.key_source === 'teacher' ? 'rounded bg-sage-100 px-2 py-0.5 text-sage-800' : 'rounded bg-gold-100 px-2 py-0.5 text-gold-900'}>
                          {t(`teacherQuiz.source.${q.key_source}`)}
                        </span>
                        <button type="button" onClick={() => update(removeQuestion(quiz, index))} disabled={quiz.questions.length <= 1}
                          className="ml-auto text-madder-700 disabled:opacity-40">{t('teacherQuiz.remove')}</button>
                      </div>
                      <label className="block">{t('teacherQuiz.prompt')}
                        <textarea value={q.prompt} rows={2} aria-label={t('teacherQuiz.promptFor', { number: q.number })}
                          onChange={(e) => set({ prompt: e.target.value })} className={field} />
                      </label>
                      {q.stimulus && <p className="text-gray-600">{t('teacherQuiz.stimulus', { text: q.stimulus })}</p>}
                      {q.type === 'multiple_choice' && (
                        <label className="block">{t('teacherQuiz.options')}
                          <textarea value={q.options.join('\n')} rows={3} aria-label={t('teacherQuiz.optionsFor', { number: q.number })}
                            onChange={(e) => set({ options: lines(e.target.value) })} className={field} />
                        </label>
                      )}
                      <label className="block">{q.type === 'written_response' ? t('teacherQuiz.modelAnswer') : t('teacherQuiz.answer')}
                        <input value={q.answer} aria-label={t('teacherQuiz.answerFor', { number: q.number })}
                          onChange={(e) => set({ answer: e.target.value })} className={field} />
                      </label>
                      {(q.type === 'short_answer' || q.type === 'fill_in_blank' || q.type === 'computation') && (
                        <label className="block">{t('teacherQuiz.alsoAccept')}
                          <textarea value={q.accepted_answers.join('\n')} rows={2} aria-label={t('teacherQuiz.alsoAcceptFor', { number: q.number })}
                            onChange={(e) => set({ accepted_answers: lines(e.target.value) })} className={field} />
                        </label>
                      )}
                      {q.type === 'written_response' && (
                        <>
                          <label className="block">{t('teacherQuiz.rubric')}
                            <textarea value={q.rubric ?? ''} rows={2} aria-label={t('teacherQuiz.rubricFor', { number: q.number })}
                              onChange={(e) => set({ rubric: e.target.value || null })} className={field} />
                          </label>
                          <label className="block">{t('teacherQuiz.guidance')}
                            <input value={q.scoring_guidance ?? ''} onChange={(e) => update({ ...quiz, approved: false, questions: quiz.questions.map((x, i) => i === index ? { ...x, scoring_guidance: e.target.value || null } : x) })}
                              className={field} />
                          </label>
                        </>
                      )}
                      {q.reading_note && <p className="text-gold-900">{t('teacherQuiz.readingNote', { note: q.reading_note })}</p>}
                      {q.answer_check === 'computed' && <p className="text-sage-700">{t('quizBuilder.status.computed')}</p>}
                      {look && (
                        <button type="button" onClick={() => update(settleQuestion(quiz, index))}
                          aria-label={t('teacherQuiz.looksRightFor', { number: q.number })}
                          className="inline-flex min-h-[36px] items-center gap-1 rounded-lg bg-sage-700 px-3 py-1 text-white">
                          <Check size={13} /> {t('practiceCoach.looksRight')}
                        </button>
                      )}
                    </li>
                  )
                })}
              </ol>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => update(addQuestion(quiz))} className={quiet}>{t('teacherQuiz.add')}</button>
                {!quiz.approved && (
                  <button type="button" onClick={() => void approve()} disabled={busy} className={`${button} bg-navy-700 text-white disabled:opacity-40`}>
                    {t('teacherQuiz.approve')}
                  </button>
                )}
                {quiz.approved && <p role="status" className="self-center text-sage-800">{t('teacherQuiz.approved')}</p>}
                <button type="button" onClick={() => printQuiz(false)} disabled={!quiz.approved} className={quiet}>
                  <Printer size={15} />{t('teacherQuiz.printQuiz')}
                </button>
                <button type="button" onClick={() => printQuiz(true)} disabled={!quiz.approved} className={quiet}>
                  <Printer size={15} />{t('teacherQuiz.printKey')}
                </button>
                <button type="button" onClick={download} className={quiet}><Download size={15} />{t('teacherQuiz.export')}</button>
                <button type="button" onClick={() => setScoring(true)} disabled={!quiz.approved}
                  className={`${button} bg-sage-700 text-white disabled:opacity-40`}>{t('teacherQuiz.scoreWork')}</button>
                <button type="button" onClick={discard} className={quiet}>{t('teacherQuiz.discard')}</button>
              </div>
            </>
          )}

          {quiz && scoring && (
            <div className="space-y-3">
              <h3 className="font-semibold text-gray-800">{t('teacherQuiz.scoringHeading', { title: quiz.title })}</h3>
              {!results && (
                <>
                  <label className={label}>{t('teacherQuiz.workPages', { max: MAX_PAGES })}
                    <input type="file" accept={ACCEPT} multiple aria-label={t('teacherQuiz.workPages', { max: MAX_PAGES })}
                      disabled={noLocal}
                      onChange={(e) => { setWorkFiles(Array.from(e.target.files ?? []).slice(0, MAX_PAGES)); e.target.value = '' }}
                      className="mt-1 block w-full text-xs" />
                  </label>
                  {workFiles.length > 0 ? (
                    <>
                      <p className="text-xs text-gray-500">{t('teacherQuiz.filesChosen', { count: workFiles.length })}</p>
                      <label className="flex items-start gap-2 rounded-lg bg-gold-50 px-3 py-2 text-xs">
                        <input type="checkbox" checked={workConsent} onChange={(e) => setWorkConsent(e.target.checked)} className="mt-0.5" />
                        <span>{t('teacherQuiz.workConsent')}</span>
                      </label>
                    </>
                  ) : (
                    <details className="rounded-lg border border-gray-100 p-2 text-xs">
                      <summary className="cursor-pointer">{t('teacherQuiz.typeInstead')}</summary>
                      <div className="mt-2 space-y-1">
                        {quiz.questions.map((q) => (
                          <label key={q.number} className="flex items-center gap-2">
                            <span className="w-6">{q.number}.</span>
                            <input value={typed[q.number] ?? ''} aria-label={t('teacherQuiz.responseFor', { number: q.number })}
                              onChange={(e) => setTyped((v) => ({ ...v, [q.number]: e.target.value }))}
                              className="min-w-0 flex-1 rounded border border-gray-200 px-2 py-1" />
                          </label>
                        ))}
                      </div>
                    </details>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={() => void score()}
                      disabled={busy || (workFiles.length > 0 ? !workConsent : !Object.values(typed).some((v) => v.trim()))}
                      className={`${button} bg-navy-700 text-white disabled:opacity-40`}>
                      {busy ? <><Loader2 size={15} className="animate-spin" />{t('teacherQuiz.reading')}</> : t('teacherQuiz.propose')}
                    </button>
                    <button type="button" onClick={resetScoring} className={quiet}>{t('teacherQuiz.backToQuiz')}</button>
                  </div>
                </>
              )}

              {results && (
                <>
                  <p className="text-xs text-gray-600">{t('teacherQuiz.resultsNote')}</p>
                  <ol className="space-y-2">
                    {results.map((r) => {
                      const q = quiz.questions.find((x) => x.number === r.number)
                      const value = settled[r.number]
                      const waiting = typeof value !== 'number'
                      return (
                        <li key={r.number} className={`space-y-1 rounded-lg border p-2 text-xs ${waiting ? 'border-gold-300 bg-gold-50' : 'border-gray-100'}`}>
                          <p className="font-medium">{r.number}. {q?.prompt}</p>
                          <p>{t('teacherQuiz.studentWrote', { response: r.response ?? t('teacherQuiz.blank') })}</p>
                          {r.reasons.map((reason) => <p key={reason} className="text-gold-900">{t(`teacherQuiz.reasons.${reason}`)}</p>)}
                          {r.reading_note && <p className="text-gold-900">{t('teacherQuiz.readingNote', { note: r.reading_note })}</p>}
                          {r.rubric_reason && <p className="text-gray-600">{t('teacherQuiz.rubricReason', { reason: r.rubric_reason })}</p>}
                          <div className="flex flex-wrap items-center gap-2">
                            <span>{r.proposed_points === null
                              ? t('teacherQuiz.noProposal')
                              : t('teacherQuiz.proposed', { points: r.proposed_points, max: r.max_points })}</span>
                            <label className="flex items-center gap-1">{t('teacherQuiz.yourScore')}
                              <input type="number" min={0} max={r.max_points} step={0.5} value={value ?? ''}
                                aria-label={t('teacherQuiz.scoreFor', { number: r.number })}
                                onChange={(e) => {
                                  const raw = e.target.value
                                  const n = raw === '' ? null : Math.max(0, Math.min(r.max_points, Number(raw)))
                                  setSettled((s) => ({ ...s, [r.number]: n === null || Number.isNaN(n) ? null : n }))
                                  setFinal(null)
                                }}
                                className="w-20 rounded border border-gray-200 px-2 py-1" />
                            </label>
                            {waiting && r.proposed_points !== null && (
                              <button type="button" aria-label={t('teacherQuiz.looksRightFor', { number: r.number })}
                                onClick={() => { setSettled((s) => ({ ...s, [r.number]: r.proposed_points })); setFinal(null) }}
                                className="inline-flex min-h-[36px] items-center gap-1 rounded-lg bg-sage-700 px-3 py-1 text-white">
                                <Check size={13} /> {t('practiceCoach.looksRight')}
                              </button>
                            )}
                          </div>
                        </li>
                      )
                    })}
                  </ol>
                  {!allSettled(settled, results) && <p className="text-xs text-gold-900">{t('teacherQuiz.stillWaiting')}</p>}
                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={() => void finalize()} disabled={busy || !allSettled(settled, results)}
                      className={`${button} bg-navy-700 text-white disabled:opacity-40`}>{t('teacherQuiz.approveResults')}</button>
                    {final && <p role="status" className="self-center font-semibold text-sage-800">{t('teacherQuiz.total', final)}</p>}
                    <button type="button" onClick={printResults} disabled={!final} className={quiet}>
                      <Printer size={15} />{t('teacherQuiz.printResults')}
                    </button>
                    <button type="button" onClick={nextStudent} className={quiet}>{t('teacherQuiz.nextStudent')}</button>
                    <button type="button" onClick={resetScoring} className={quiet}>{t('teacherQuiz.backToQuiz')}</button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
