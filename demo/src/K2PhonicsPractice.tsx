import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { Volume2 } from 'lucide-react'
import type { PhonicsLesson, PhonicsPracticeTransport, PhonicsTask } from './k2PhonicsTypes'
import { Picture } from './Diagram'
import { PrintPracticeButton, phonicsPrintItems, printPractice } from './k2PrintSheet'
import RoutineShell, { type RoutineStep } from './RoutineShell'
import { PRACTICE_PRIMARY, PRACTICE_TARGET } from './practiceStyles'

/**
 * Phonics practice for K-2: Watch, Together, Your turn
 * (docs/K2_PRACTICE.md §5.1).
 *
 * The server builds every word and works out every answer
 * (homeschool-api/services/k2_practice/phonics.py); this screen draws what it
 * is sent, says every line aloud, and asks the server whether a tap is right.
 * It keeps nothing after it closes, shows no score, timer or streak, and
 * never says "wrong": a miss shows the way again.
 *
 * Sizes are in rem (Tailwind's 14 = 3.5rem = 56px, 16 = 4rem = 64px at the
 * default text size), so every target grows with the text-size control and
 * nothing is a fixed width that would force sideways scrolling at 200%.
 */

/** The words of an instruction, from its key and the server's arguments. */
export function promptText(t: TFunction, task: PhonicsTask): string {
  return t(`k2Phonics.prompt.${task.prompt.key}`, task.prompt.args)
}

/**
 * The instruction as SHOWN. In "Your turn", where seeing the word written
 * would give the answer away (its first letter, or the very word to find),
 * the shown line leaves the word out; it is still spoken, because hearing it
 * is the question.
 */
export function shownPromptText(t: TFunction, task: PhonicsTask, step: RoutineStep): string {
  if (step === 'your_turn' && HIDDEN_WHEN_SHOWN.includes(task.prompt.key)) {
    return t(`k2Phonics.promptShown.${task.prompt.key}`)
  }
  return promptText(t, task)
}

const HIDDEN_WHEN_SHOWN = ['first_sound_choice', 'sight_word_choice']

/** Questions where reading the word is the skill: a missing picture must not
 *  show the word it stands for. */
const DECODING_KEYS = ['read_word_choice']

/** What Bede says while demonstrating the Watch step. */
export function watchText(t: TFunction, watch: NonNullable<PhonicsLesson['watch']>): string {
  const answer = watch.answer.choice
  const word = watch.display.word ?? watch.prompt.args.word ?? answer
  const sounds = (watch.display.graphemes ?? []).filter((g) => g.sound).map((g) => g.sound).join(', ')
  return t(`k2Phonics.watch.${watch.prompt.key}`, {
    word, answer, letter: answer, sound: watch.choice_sounds?.[answer] ?? '', sounds,
    // A question's own arguments win: "starts with" names its letter and sound.
    ...watch.prompt.args,
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

export default function K2PhonicsPractice({
  onClose, onSpeak, canSpeak, transport,
}: {
  onClose: () => void
  /** Reads a line aloud. Every instruction is spoken as well as shown. */
  onSpeak?: (text: string) => void
  /** Whether the round can be spoken: false with Bede's voice off, null while
   * still checking. Defaults to whether `onSpeak` was given. */
  canSpeak?: boolean | null
  /** The caller supplies its authenticated transport and data boundary. */
  transport: PhonicsPracticeTransport
}) {
  const { t } = useTranslation()
  const [lesson, setLesson] = useState<PhonicsLesson | null>(null)
  const [failed, setFailed] = useState(false)
  const [printTrouble, setPrintTrouble] = useState(false)
  const [step, setStep] = useState<RoutineStep>('watch')
  const [index, setIndex] = useState(0)
  const [done, setDone] = useState(false)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [busy, setBusy] = useState(false)
  const [lit, setLit] = useState(0)
  const loadId = useRef(0)
  const reduced = useRef(prefersReducedMotion())
  const transportRef = useRef(transport)
  transportRef.current = transport

  // A round the device cannot speak asks for a lesson without the questions
  // that only work by ear; until that is known, nothing is fetched.
  const audio = canSpeak === undefined ? !!onSpeak : canSpeak
  const load = useCallback(() => {
    if (audio === null) return
    const mine = ++loadId.current
    setLesson(null); setFailed(false); setStep('watch'); setIndex(0); setDone(false); setFeedback(null)
    transportRef.current.load(audio)
      .then((l) => { if (mine === loadId.current) setLesson(l) })
      .catch(() => { if (mine === loadId.current) setFailed(true) })
  }, [audio])

  useEffect(() => { load(); return () => { loadId.current += 1 } }, [load])

  const task: PhonicsTask | null = !lesson || done || lesson.needs_audio ? null
    : step === 'watch' ? lesson.watch
      : step === 'together' ? lesson.together[index] : lesson.your_turn[index]
  const watching = step === 'watch'
  const line = !task || !lesson ? '' : watching && lesson.watch ? watchText(t, lesson.watch) : promptText(t, task)
  const shownLine = !task || !lesson || watching ? line : shownPromptText(t, task, step)

  const speakRef = useRef(onSpeak)
  speakRef.current = onSpeak
  // Keyed on the question as well as the words: two questions can share an
  // instruction, and each one is still said aloud.
  useEffect(() => { if (line) speakRef.current?.(line) }, [line, step, index, lesson])

  // Watch: the letters light up one at a time as Bede says each sound, then
  // sit together as one word. With reduced motion they are all there at once.
  const letterCount = task?.display.graphemes?.length ?? 0
  const [replay, setReplay] = useState(0)
  useEffect(() => {
    if (!watching || !letterCount) { setLit(letterCount); return }
    if (reduced.current) { setLit(letterCount); return }
    setLit(0)
    let n = 0
    const timer = setInterval(() => {
      n += 1
      setLit(n)
      if (n >= letterCount) clearInterval(timer)
    }, 700)
    return () => clearInterval(timer)
  }, [watching, letterCount, lesson, replay])

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
    const sound = step === 'together' ? task.choice_sounds?.[choice] : undefined
    if (sound) speakRef.current?.(sound)
    setBusy(true)
    try {
      const result = await transportRef.current.answer(lesson.lesson_id, step, index, choice)
      if (result.correct) { setFeedback({ kind: 'right' }); speakRef.current?.(t('k2Phonics.right')) }
      else if (result.reveal) { setFeedback({ kind: 'shown', choice: result.reveal.choice }); speakRef.current?.(t('k2Phonics.shown')) }
      else { setFeedback({ kind: 'again' }); speakRef.current?.(t('k2Phonics.again')) }
    } catch {
      // Not checked, so not counted; the child can try again.
      setFeedback({ kind: 'trouble' })
    } finally {
      setBusy(false)
    }
  }

  const title = t('k2Phonics.title')

  if (failed) {
    return (
      <RoutineShell title={title} step="watch" onClose={onClose}>
        <p role="alert" className="text-lg text-gray-700 text-center">{t('k2Phonics.loadTrouble')}</p>
        <button type="button" onClick={load} className={PRIMARY}>{t('k2Phonics.tryAgain')}</button>
      </RoutineShell>
    )
  }
  if (!lesson) {
    return (
      <RoutineShell title={title} step="watch" onClose={onClose}>
        <p role="status" className="text-lg text-gray-600">{t('k2Phonics.loading')}</p>
      </RoutineShell>
    )
  }
  if (lesson.needs_audio) {
    return (
      <RoutineShell title={title} step="watch" onClose={onClose}>
        <p className="text-lg text-gray-700 text-center" data-testid="phonics-needs-sound">{t('k2Phonics.needsSound')}</p>
        <button type="button" onClick={onClose} className={PRIMARY}>{t('k2Phonics.backToBede')}</button>
      </RoutineShell>
    )
  }
  if (done || !task) {
    return (
      <RoutineShell title={title} step="your_turn" done onClose={onClose}>
        <p className="text-xl font-semibold text-navy-700 text-center">{t('k2Phonics.finished')}</p>
        <div className="flex flex-wrap justify-center gap-2">
          <button type="button" onClick={onClose} className={PRIMARY}>{t('k2Phonics.backToBede')}</button>
          <button type="button" onClick={load} className={SECONDARY}>{t('k2Phonics.another')}</button>
          <PrintPracticeButton t={t} className={SECONDARY} onPrint={() => {
            setPrintTrouble(false)
            void printPractice(t, title, phonicsPrintItems(t, lesson)).then((ok) => setPrintTrouble(!ok))
          }} />
        </div>
        {printTrouble && <p role="alert" className="text-base text-navy-700 text-center">{t('printSheet.failed')}</p>}
      </RoutineShell>
    )
  }

  // In Watch the answer is shown only once the demonstration has played.
  const watchDone = !watching || reduced.current || lit >= (task.display.graphemes?.length ?? 0)
  const shownChoice = watching ? (watchDone ? lesson.watch?.answer.choice : undefined)
    : feedback?.kind === 'shown' ? feedback.choice : undefined
  const { display } = task
  const tappable = step === 'together' || watching

  return (
    <RoutineShell title={title} step={step} onClose={onClose}>
      <p className="text-base text-gray-600 text-center">{t(`k2Phonics.lead.${step}`)}</p>
      <div className="flex flex-wrap items-center justify-center gap-2">
        <p className="text-xl font-medium text-navy-700 text-center" data-testid="phonics-line">{shownLine}</p>
        <button
          type="button" onClick={() => speakRef.current?.(line)}
          aria-label={t('k2Phonics.hearAgain')} title={t('k2Phonics.hearAgain')}
          className={`${TARGET} rounded-xl border-2 border-sage-300 bg-white text-navy-700 flex items-center justify-center`}
        >
          <Volume2 aria-hidden="true" className="h-6 w-6" />
        </button>
      </div>

      {display.kind === 'word' && display.graphemes && (
        <div className="flex flex-wrap justify-center gap-2" data-testid="phonics-word" aria-label={t('k2Phonics.theWord')}>
          {display.graphemes.map((g, i) => {
            // Reduced motion shows every letter on the first frame, rather
            // than waiting for an effect to light them.
            const shown = reduced.current || i < lit || !watching
            const cls = `${TARGET} rounded-xl border-2 px-3 text-4xl font-semibold ${
              g.silent ? 'border-gray-300 text-gray-500' : 'border-navy-300 text-navy-800'
            } bg-white motion-safe:transition-opacity motion-safe:duration-300 ${shown ? 'opacity-100' : 'opacity-0'}`
            return step === 'together' && g.sound ? (
              <button key={i} type="button" onClick={() => speakRef.current?.(g.sound ?? '')}
                aria-label={t('k2Phonics.hearLetter', { letter: g.text })} className={cls}>
                {g.text}
              </button>
            ) : (
              <span key={i} className={`${cls} inline-flex items-center justify-center`} data-silent={g.silent ? '' : undefined}>
                {g.text}
              </span>
            )
          })}
        </div>
      )}

      {display.kind === 'picture' && display.icon && (
        tappable ? (
          <button type="button" onClick={() => speakRef.current?.(display.word ?? '')}
            aria-label={t('k2Phonics.hearWord', { word: display.word })}
            className={`${TARGET} rounded-2xl border-2 border-sage-300 bg-white p-2 text-6xl`}>
            <Picture name={display.icon} label={display.word ?? display.icon} size="h-24 w-24" />
          </button>
        ) : (
          <Picture name={display.icon} label={display.word ?? display.icon} size="h-24 w-24" />
        )
      )}

      <div className="flex flex-wrap justify-center gap-2" role="group" aria-label={t('k2Phonics.pickAnAnswer')}>
        {task.choices.map((choice) => {
          const revealed = shownChoice === choice
          return (
            <button
              key={choice} type="button" disabled={watching || busy || settled}
              onClick={() => send(choice)}
              data-revealed={revealed ? '' : undefined}
              aria-label={task.choice_kind === 'picture' ? choice : undefined}
              className={`${TARGET} rounded-2xl border-4 px-3 py-1 flex flex-col items-center justify-center ${
                revealed ? 'border-sage-700 bg-sage-50' : 'border-sage-200 bg-white'
              } ${task.choice_kind === 'picture' ? 'text-5xl' : 'text-3xl font-semibold text-navy-800'}`}
            >
              {task.choice_kind === 'picture'
                ? <Picture name={choice} label={choice} size="h-20 w-20"
                  hideWord={DECODING_KEYS.includes(task.prompt.key)} />
                : choice}
              {revealed && <span className="text-base font-medium text-sage-800">✓ {t('k2Phonics.thisOne')}</span>}
            </button>
          )
        })}
      </div>

      <div aria-live="polite" className="min-h-[2rem] text-center text-lg">
        {feedback?.kind === 'right' && <span className="font-medium text-sage-800">{t('k2Phonics.right')}</span>}
        {feedback?.kind === 'again' && <span className="text-navy-700">{t('k2Phonics.again')}</span>}
        {feedback?.kind === 'shown' && <span className="text-navy-700">{t('k2Phonics.shown')}</span>}
        {feedback?.kind === 'trouble' && <span role="alert" className="text-navy-700">{t('k2Phonics.checkTrouble')}</span>}
      </div>

      {watching && letterCount > 0 && !reduced.current && (
        <button type="button" onClick={() => setReplay((r) => r + 1)} className={SECONDARY}>
          {t('k2Phonics.watchAgain')}
        </button>
      )}
      {(watching || settled) && (
        <button type="button" onClick={next} className={PRIMARY}>
          {watching ? t('k2Phonics.letsTry') : t('k2Phonics.next')}
        </button>
      )}
    </RoutineShell>
  )
}

/** A child's tap target: at least 56 CSS px at the default text size. */
export const TARGET = PRACTICE_TARGET
/** The main action: at least 64 CSS px. */
export const PRIMARY = PRACTICE_PRIMARY
const SECONDARY = 'min-h-16 min-w-16 rounded-2xl border-2 border-sage-300 bg-white px-6 py-3 text-lg font-medium text-navy-700'
