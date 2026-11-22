import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { Volume2 } from 'lucide-react'
import type { MathLesson, MathPracticeTransport, MathTask } from './k2MathTypes'
import RoutineShell, { type RoutineStep } from './RoutineShell'
import { Counter, MathPicture, TenFrameBuilder } from './MathPieces'
import { PrintPracticeButton, mathPrintItems, printPractice } from './k2PrintSheet'
import { PRACTICE_PRIMARY as PRIMARY, PRACTICE_TARGET as TARGET } from './practiceStyles'

/**
 * Practical math for K-2: Watch, Together, Your turn with counters, a
 * ten-frame and a number bond (docs/K2_PRACTICE.md §5.3).
 *
 * The server chooses every number and works out every answer
 * (homeschool-api/services/k2_practice/practical_math.py); this screen draws
 * what it is sent, says every line aloud, and asks the server whether an
 * answer is right. An answer is a tapped choice, or the number of counters on
 * the frame after the child dragged or tapped them; nothing is typed. It keeps
 * nothing after it closes, shows no score, timer or streak, and never says
 * "wrong": a miss shows the way again.
 */

/** The words of an instruction, from its key and the server's arguments. */
export function mathPromptText(t: TFunction, task: MathTask): string {
  return t(`k2Math.prompt.${task.prompt.key}`, task.prompt.args)
}

/** What Bede says while demonstrating the Watch step. */
export function mathWatchText(t: TFunction, watch: NonNullable<MathLesson['watch']>): string {
  const answer = watch.answer.choice
  return t(`k2Math.watch.${watch.prompt.key}`, {
    ...watch.prompt.args, answer,
    result: watch.choice_kind === 'color' ? t(`k2Math.compareResult.${answer}`) : '',
  })
}

function prefersReducedMotion(): boolean {
  try {
    return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

type Feedback =
  | { kind: 'right' }
  | { kind: 'again' }
  | { kind: 'shown'; choice: string }
  | { kind: 'trouble' }

export default function K2MathPractice({
  onClose, onSpeak, canSpeak, transport, showTopicPicker = false,
}: {
  onClose: () => void
  /** Reads a line aloud in Bede's own voice. Every instruction is spoken as well as shown. */
  onSpeak?: (text: string) => void
  /** Whether this device can speak the round (null while checking). No math
   * question works only by ear, so this only decides what the server is told. */
  canSpeak?: boolean | null
  /** The caller supplies its authenticated transport and data boundary. */
  transport: MathPracticeTransport
  /** Let demo visitors inspect built topics without implying saved mastery. */
  showTopicPicker?: boolean
}) {
  const { t } = useTranslation()
  const [lesson, setLesson] = useState<MathLesson | null>(null)
  const [failed, setFailed] = useState(false)
  const [printTrouble, setPrintTrouble] = useState(false)
  const [step, setStep] = useState<RoutineStep>('watch')
  const [index, setIndex] = useState(0)
  const [done, setDone] = useState(false)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [busy, setBusy] = useState(false)
  // How many counters are on the frame, remembered for the question it was
  // set on: a new question starts from its own counters on its very first
  // frame, never from the last question's count.
  const [builtFor, setBuiltFor] = useState<{ task: MathTask | null; n: number }>({ task: null, n: 0 })
  const [selectedTopic, setSelectedTopic] = useState<string>()
  const selectedTopicRef = useRef<string | undefined>(undefined)
  const loadId = useRef(0)
  const reduced = useRef(prefersReducedMotion())
  const pendingSubmission = useRef<{ fingerprint: string; id: string } | null>(null)
  const transportRef = useRef(transport)
  transportRef.current = transport

  const audio = canSpeak === undefined ? !!onSpeak : canSpeak
  const load = useCallback((topic = selectedTopicRef.current) => {
    if (audio === null) return
    const mine = ++loadId.current
    setLesson(null); setFailed(false); setStep('watch'); setIndex(0); setDone(false); setFeedback(null)
    transportRef.current.load(audio, topic ?? selectedTopic)
      .then((l) => { if (mine === loadId.current) setLesson(l) })
      .catch(() => { if (mine === loadId.current) setFailed(true) })
  }, [audio])

  useEffect(() => { load(); return () => { loadId.current += 1 } }, [load])

  const task: MathTask | null = !lesson || done || lesson.needs_audio ? null
    : step === 'watch' ? lesson.watch
      : step === 'together' ? lesson.together[index] : lesson.your_turn[index]
  const watching = step === 'watch'
  const line = !task || !lesson ? '' : watching && lesson.watch ? mathWatchText(t, lesson.watch) : mathPromptText(t, task)

  const speakRef = useRef(onSpeak)
  speakRef.current = onSpeak
  useEffect(() => { if (line) speakRef.current?.(line) }, [line, step, index, lesson])

  // A building question starts from the counters already on the frame. In
  // Watch they are put on (or taken off) one at a time while Bede says the
  // line; with reduced motion the frame shows the end straight away.
  const buildStart = task?.build?.start ?? 0
  const watchTarget = watching && lesson?.watch && task?.choice_kind === 'build'
    ? Number(lesson.watch.answer.choice) : null
  // Reduced motion shows the end of the demonstration on the first frame.
  const built = builtFor.task === task ? builtFor.n
    : watchTarget !== null && reduced.current ? watchTarget : buildStart
  const setBuilt = (n: number) => setBuiltFor({ task, n })
  // "Watch again" replays the demonstration from the start.
  const [replay, setReplay] = useState(0)
  useEffect(() => {
    if (watchTarget === null || reduced.current) return
    // A pause first, so Bede's line is heard before anything moves; then one
    // counter at a time, slow enough to count along with.
    let n = buildStart
    setBuiltFor({ task, n })
    let timer: ReturnType<typeof setInterval> | undefined
    const wait = setTimeout(() => {
      timer = setInterval(() => {
        n += n < watchTarget ? 1 : -1
        setBuiltFor({ task, n })
        if (n === watchTarget) clearInterval(timer)
      }, WATCH_STEP_MS)
    }, WATCH_PAUSE_MS)
    return () => { clearTimeout(wait); if (timer) clearInterval(timer) }
  }, [task, buildStart, watchTarget, replay])

  const next = () => {
    if (!lesson) return
    setFeedback(null)
    if (step === 'watch') { setStep('together'); setIndex(0); return }
    const list = step === 'together' ? lesson.together : lesson.your_turn
    if (index + 1 < list.length) { setIndex(index + 1); return }
    if (step === 'together') { setStep('your_turn'); setIndex(0); return }
    setDone(true)
  }

  const settled = feedback?.kind === 'right' || feedback?.kind === 'shown'

  const send = async (choice: string) => {
    if (!lesson || !task || busy || settled || watching) return
    const fingerprint = JSON.stringify([lesson.lesson_id, step, index, choice])
    const submissionId = pendingSubmission.current?.fingerprint === fingerprint
      ? pendingSubmission.current.id
      : typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2)}`
    pendingSubmission.current = { fingerprint, id: submissionId }
    setBusy(true)
    try {
      const result = await transportRef.current.answer(
        lesson.lesson_id, step as 'together' | 'your_turn', index, choice, submissionId,
      )
      pendingSubmission.current = null
      if (result.correct) { setFeedback({ kind: 'right' }); speakRef.current?.(t('k2Math.right')) }
      else if (result.reveal) {
        setFeedback({ kind: 'shown', choice: result.reveal.choice })
        if (task.choice_kind === 'build') setBuilt(Number(result.reveal.choice))
        speakRef.current?.(t('k2Math.shown'))
      } else { setFeedback({ kind: 'again' }); speakRef.current?.(t('k2Math.again')) }
    } catch {
      // Not checked, so not counted; the child can try again.
      setFeedback({ kind: 'trouble' })
    } finally {
      setBusy(false)
    }
  }

  const title = t('k2Math.title')
  const topicPicker = showTopicPicker && lesson?.available_topics && (
    <label className="flex max-w-full flex-wrap items-center justify-center gap-2 text-sm text-gray-700">
      <span>{t('k2Math.chooseTopic')}</span>
      <select
        value={selectedTopic ?? lesson.topic}
        onChange={(event) => {
          const value = event.currentTarget.value
          selectedTopicRef.current = value
          setSelectedTopic(value)
          load(value)
        }}
        className="min-h-11 max-w-full rounded-lg border border-sage-300 bg-white px-3 text-base"
      >
        {lesson.available_topics.map((topic) => (
          <option key={topic} value={topic}>{t(`k2Math.topic.${topic}`)}</option>
        ))}
      </select>
    </label>
  )

  if (failed) {
    return (
      <RoutineShell title={title} step="watch" onClose={onClose}>
        <p role="alert" className="text-lg text-gray-700 text-center">{t('k2Math.loadTrouble')}</p>
        <button type="button" onClick={() => load()} className={PRIMARY}>{t('k2Math.tryAgain')}</button>
        {topicPicker}
      </RoutineShell>
    )
  }
  if (!lesson) {
    return (
      <RoutineShell title={title} step="watch" onClose={onClose}>
        <p role="status" className="text-lg text-gray-600">{t('k2Math.loading')}</p>
      </RoutineShell>
    )
  }
  if (done || !task) {
    return (
      <RoutineShell title={title} step="your_turn" done onClose={onClose}>
        <p className="text-xl font-semibold text-navy-700 text-center">{t('k2Math.finished')}</p>
        {topicPicker}
        <div className="flex flex-wrap justify-center gap-2">
          <button type="button" onClick={onClose} className={PRIMARY}>{t('k2Math.backToBede')}</button>
          <button type="button" onClick={() => load()} className={SECONDARY}>{t('k2Math.another')}</button>
          <PrintPracticeButton t={t} className={SECONDARY} onPrint={() => {
            setPrintTrouble(false)
            void printPractice(t, title, mathPrintItems(t, lesson)).then((ok) => setPrintTrouble(!ok))
          }} />
        </div>
        {printTrouble && <p role="alert" className="text-base text-navy-700 text-center">{t('printSheet.failed')}</p>}
      </RoutineShell>
    )
  }

  const shownChoice = watching ? lesson.watch?.answer.choice
    : feedback?.kind === 'shown' ? feedback.choice : undefined
  const { display } = task
  const building = task.choice_kind === 'build'
  const choiceLabel = (c: string) => (task.choice_kind === 'color' ? t(`k2Math.choice.${c}`) : c)

  return (
    <RoutineShell title={title} step={step} onClose={onClose}>
      {topicPicker}
      <p className="text-base text-gray-600 text-center">{t(`k2Math.lead.${step}`)}</p>
      <div className="flex flex-wrap items-center justify-center gap-2">
        <p className="text-xl font-medium text-navy-700 text-center" data-testid="math-line">{line}</p>
        <button
          type="button" onClick={() => speakRef.current?.(line)}
          aria-label={t('k2Math.hearAgain')} title={t('k2Math.hearAgain')}
          className={`${TARGET} rounded-xl border-2 border-sage-300 bg-white text-navy-700 flex items-center justify-center`}
        >
          <Volume2 aria-hidden="true" className="h-6 w-6" />
        </button>
      </div>

      {building && task.build ? (
        <>
          {watching && watchTarget !== null && (
            <p aria-live="polite" data-testid="watch-count" className="text-5xl font-bold text-navy-800 text-center tabular-nums">
              {built}
            </p>
          )}
          <TenFrameBuilder
            frames={task.build.capacity / 10} start={task.build.start} count={built}
            onChange={(n) => { setBuilt(n); if (feedback?.kind === 'again' || feedback?.kind === 'trouble') setFeedback(null) }}
            ghost={display.ghost} takeAway={task.build.take_away} disabled={watching || busy || settled}
          />
          {!watching && !settled && (
            <button type="button" onClick={() => send(String(built))} disabled={busy} className={PRIMARY}>
              {t('k2Math.check')}
            </button>
          )}
        </>
      ) : (
        <>
          <MathPicture d={display.diagram} guide={display.guide} />
          <div className="flex flex-wrap justify-center gap-2" role="group" aria-label={t('k2Math.pickAnAnswer')}>
            {task.choices.map((choice) => {
              const revealed = shownChoice === choice
              return (
                <button
                  key={choice} type="button" disabled={watching || busy || settled}
                  onClick={() => send(choice)}
                  data-revealed={revealed ? '' : undefined}
                  aria-label={choiceLabel(choice)}
                  className={`${TARGET} rounded-2xl border-4 px-3 py-1 flex flex-col items-center justify-center ${
                    revealed ? 'border-sage-700 bg-sage-50' : 'border-sage-200 bg-white'
                  } text-3xl font-semibold text-navy-800`}
                >
                  {task.choice_kind === 'color' ? (
                    <span className="flex items-center gap-1 text-lg">
                      {choice !== 'yellow' && <Counter color="red" />}
                      {choice !== 'red' && <Counter color="yellow" />}
                      <span>{choiceLabel(choice)}</span>
                    </span>
                  ) : choice}
                  {revealed && <span className="text-base font-medium text-sage-800">✓ {t('k2Math.thisOne')}</span>}
                </button>
              )
            })}
          </div>
        </>
      )}

      <div aria-live="polite" className="min-h-[2rem] text-center text-lg">
        {feedback?.kind === 'right' && <span className="font-medium text-sage-800">{t('k2Math.right')}</span>}
        {feedback?.kind === 'again' && <span className="text-navy-700">{t('k2Math.again')}</span>}
        {feedback?.kind === 'shown' && <span className="text-navy-700">{t('k2Math.shown')}</span>}
        {feedback?.kind === 'trouble' && <span role="alert" className="text-navy-700">{t('k2Math.checkTrouble')}</span>}
      </div>

      {watching && watchTarget !== null && !reduced.current && (
        <button type="button" onClick={() => setReplay((r) => r + 1)} className={SECONDARY}>
          {t('k2Math.watchAgain')}
        </button>
      )}
      {(watching || settled) && (
        <button type="button" onClick={next} className={PRIMARY}>
          {watching ? t('k2Math.letsTry') : t('k2Math.next')}
        </button>
      )}
    </RoutineShell>
  )
}

const SECONDARY = 'min-h-16 min-w-16 rounded-2xl border-2 border-sage-300 bg-white px-6 py-3 text-lg font-medium text-navy-700'

/** How long Watch waits before anything moves, and between counters: slow
 *  enough for a five-year-old to count along. */
export const WATCH_PAUSE_MS = 1200
export const WATCH_STEP_MS = 800
