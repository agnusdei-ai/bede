import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import type { MapCell, MapLesson, MapPracticeTransport, MapReveal, MapTask } from './mapPracticeTypes'
import MapScene, { KNOWN_SYMBOLS, SideView, cellLabel } from './MapScene'
import RoutineShell, { type RoutineStep } from './RoutineShell'
import { PrintPracticeButton, mapPrintItems, printPractice } from './k2PrintSheet'

/**
 * Map-reading practice for K-2: Watch, Together, Your turn.
 *
 * The server builds each map and works out every answer
 * (homeschool-api/services/map_practice.py); this screen draws what it is
 * sent and asks the server whether a tap or a choice is right. It keeps
 * nothing after it closes, and it never asks for or sends a real place.
 */

const WORDS = ['above', 'below', 'left_of', 'right_of', 'north', 'south', 'east', 'west', 'land', 'water']

/** The words of a question, from its key and the ids the server sent. */
export function promptText(t: TFunction, prompt: MapTask['prompt']): string {
  const args: Record<string, string | number> = {}
  for (const [name, value] of Object.entries(prompt.args)) {
    if (Array.isArray(value)) continue
    if (typeof value === 'string' && KNOWN_SYMBOLS.includes(value)) {
      args[`${name}The`] = t(`mapPractice.symbolThe.${value}`)
      args[`${name}Of`] = t(`mapPractice.symbolOf.${value}`)
    } else if (typeof value === 'string' && WORDS.includes(value)) {
      args[name] = t(`mapPractice.word.${value}`)
    } else {
      args[name] = value
    }
  }
  return t(`mapPractice.prompt.${prompt.key}`, args)
}

export function choiceText(t: TFunction, choice: string): string {
  if (KNOWN_SYMBOLS.includes(choice)) return t(`mapPractice.symbol.${choice}`)
  if (WORDS.includes(choice)) return t(`mapPractice.word.${choice}`)
  return choice
}

type Feedback =
  | { kind: 'right' }
  | { kind: 'again' }
  | { kind: 'shown'; reveal: MapReveal }
  | { kind: 'trouble' }

export default function MapPractice({
  onClose, onSpeak, transport,
}: {
  onClose: () => void
  /** Reads a question aloud in Bede's own voice, when the session has it on. */
  onSpeak?: (text: string) => void
  /** The caller supplies its authenticated transport and data boundary. */
  transport: MapPracticeTransport
}) {
  const { t } = useTranslation()
  const [lesson, setLesson] = useState<MapLesson | null>(null)
  const [failed, setFailed] = useState(false)
  const [printTrouble, setPrintTrouble] = useState(false)
  const [step, setStep] = useState<RoutineStep>('watch')
  const [index, setIndex] = useState(0)
  const [done, setDone] = useState(false)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [picked, setPicked] = useState<MapCell | undefined>()
  const [busy, setBusy] = useState(false)
  const [flat, setFlat] = useState(false)
  const loadId = useRef(0)
  const transportRef = useRef(transport)
  transportRef.current = transport

  const load = useCallback(() => {
    const mine = ++loadId.current
    setLesson(null); setFailed(false); setStep('watch'); setIndex(0); setDone(false)
    setFeedback(null); setPicked(undefined); setFlat(false)
    transportRef.current.load()
      .then((l) => { if (mine === loadId.current) setLesson(l) })
      .catch(() => { if (mine === loadId.current) setFailed(true) })
  }, [])

  useEffect(() => { load(); return () => { loadId.current += 1 } }, [load])

  // Watch: the picture starts tilted, as if seen from the side, and settles
  // flat, as a map seen from above.
  // Then the way is shown one square at a time, and only after it the
  // answer, so the child sees how Bede got there. "Watch again" replays it;
  // with reduced motion everything is shown at once.
  const [lit, setLit] = useState(0)
  const [replay, setReplay] = useState(0)
  const reduced = useRef(prefersReducedMotion())
  const guideLength = lesson?.watch.guide_cells?.length ?? 0
  useEffect(() => {
    if (!lesson || step !== 'watch') return
    if (reduced.current) { setFlat(true); setLit(guideLength); return }
    setFlat(false)
    setLit(0)
    let n = 0
    let timer: ReturnType<typeof setInterval> | undefined
    const settle = setTimeout(() => {
      setFlat(true)
      timer = setInterval(() => {
        n += 1
        setLit(n)
        if (n >= guideLength) clearInterval(timer)
      }, MAP_WATCH_STEP_MS)
    }, MAP_WATCH_PAUSE_MS)
    return () => { clearTimeout(settle); if (timer) clearInterval(timer) }
  }, [lesson, step, replay, guideLength])

  const task: MapTask | null = !lesson || done ? null
    : step === 'watch' ? lesson.watch
      : step === 'together' ? lesson.together[index] : lesson.your_turn[index]
  const question = task ? promptText(t, task.prompt) : ''

  const speakRef = useRef(onSpeak)
  speakRef.current = onSpeak
  useEffect(() => { if (question) speakRef.current?.(question) }, [question])

  const next = () => {
    if (!lesson) return
    setFeedback(null); setPicked(undefined)
    if (step === 'watch') { setStep('together'); setIndex(0); return }
    const list = step === 'together' ? lesson.together : lesson.your_turn
    if (index + 1 < list.length) { setIndex(index + 1); return }
    if (step === 'together') { setStep('your_turn'); setIndex(0); return }
    setDone(true)
  }

  const settled = feedback?.kind === 'right' || feedback?.kind === 'shown'

  const send = async (answer: { cell: MapCell } | { choice: string }) => {
    if (!lesson || !task || busy || settled || step === 'watch') return
    setBusy(true)
    if ('cell' in answer) setPicked(answer.cell)
    try {
      const result = await transportRef.current.answer(lesson.lesson_id, step, index, answer)
      if (result.correct) setFeedback({ kind: 'right' })
      else if (result.reveal) setFeedback({ kind: 'shown', reveal: result.reveal })
      else setFeedback({ kind: 'again' })
    } catch {
      // The answer could not be checked. Nothing was counted; the child can try again.
      setFeedback({ kind: 'trouble' })
    } finally {
      setBusy(false)
    }
  }

  const title = t('mapPractice.title')

  if (failed) {
    return (
      <RoutineShell title={title} step="watch" onClose={onClose}>
        <p role="alert" className="text-gray-700 text-center">{t('mapPractice.loadTrouble')}</p>
        <button type="button" onClick={load} className={primary}>{t('mapPractice.tryAgain')}</button>
      </RoutineShell>
    )
  }
  if (!lesson) {
    return (
      <RoutineShell title={title} step="watch" onClose={onClose}>
        <p role="status" className="text-gray-500">{t('mapPractice.loading')}</p>
      </RoutineShell>
    )
  }
  if (done || !task) {
    return (
      <RoutineShell title={title} step="your_turn" done onClose={onClose}>
        <p className="text-lg font-semibold text-navy-700 text-center">{t('mapPractice.finished')}</p>
        <div className="flex flex-wrap justify-center gap-3">
          <button type="button" onClick={onClose} className={primary}>{t('mapPractice.backToBede')}</button>
          <button type="button" onClick={load} className={secondary}>{t('mapPractice.anotherMap')}</button>
          <PrintPracticeButton t={t} className={secondary} onPrint={() => {
            setPrintTrouble(false)
            void printPractice(t, title, mapPrintItems(t, lesson, (task) => promptText(t, task.prompt), (c) => choiceText(t, c))).then((ok) => setPrintTrouble(!ok))
          }} />
        </div>
        {printTrouble && <p role="alert" className="text-base text-navy-700 text-center">{t('printSheet.failed')}</p>}
      </RoutineShell>
    )
  }

  const watching = step === 'watch'
  const watchDone = flat && lit >= guideLength
  const reveal: MapReveal | undefined = watching ? (watchDone ? lesson.watch.answer : undefined)
    : feedback?.kind === 'shown' ? feedback.reveal : undefined
  const guide = step === 'your_turn' ? undefined
    : watching ? task.guide_cells?.slice(0, lit) : task.guide_cells

  return (
    <RoutineShell title={title} step={step} onClose={onClose}>
      <p className="text-sm text-gray-500">{t(`mapPractice.lead.${step}`)}</p>
      <p className="text-lg font-medium text-navy-700 text-center" data-testid="map-question">{question}</p>

      {task.side_view && <SideView symbols={task.side_view} />}

      {task.answer_kind === 'scene_choice' && task.options ? (
        <div className="flex flex-wrap justify-center gap-3" role="group" aria-label={t('mapPractice.pickAMap')}>
          {task.options.map((option, i) => {
            const shown = reveal?.choice === String(i)
            return (
              <button
                key={i} type="button" disabled={watching || busy || settled}
                onClick={() => send({ choice: String(i) })}
                aria-label={t('mapPractice.mapNumber', { n: i + 1 })}
                className={`rounded-xl p-1.5 border-4 min-h-[44px] ${shown ? 'border-emerald-600' : 'border-transparent'} ${watching ? '' : 'hover:border-sage-300'}`}
                data-revealed={shown ? '' : undefined}
              >
                <MapScene scene={option} small tilted={watching && !flat} />
              </button>
            )
          })}
        </div>
      ) : (
        <MapScene
          scene={task.scene}
          onTap={task.answer_kind === 'tap' && !watching ? (cell) => send({ cell }) : undefined}
          disabled={busy || settled}
          guide={guide} marked={task.marked} picked={picked}
          revealed={reveal?.cell} tilted={watching && !flat}
        />
      )}

      {task.answer_kind === 'choice' && task.choices && (
        <div className="flex flex-wrap justify-center gap-2" role="group" aria-label={t('mapPractice.pickAnAnswer')}>
          {task.choices.map((choice) => {
            const shown = reveal?.choice === choice
            return (
              <button
                key={choice} type="button" disabled={watching || busy || settled}
                onClick={() => send({ choice })}
                data-revealed={shown ? '' : undefined}
                className={`min-h-[44px] min-w-[72px] rounded-xl border-2 px-4 py-2 text-base font-medium ${
                  shown ? 'border-emerald-600 bg-emerald-50 text-emerald-800' : 'border-sage-300 bg-white text-navy-700'
                }`}
              >
                {choiceText(t, choice)}
              </button>
            )
          })}
        </div>
      )}

      <div aria-live="polite" className="min-h-[1.75rem] text-center text-base">
        {watching && !watchDone && <span className="text-navy-700">{t('mapPractice.watchLook')}</span>}
        {watching && reveal && (
          <span className="text-emerald-700">
            {reveal.cell ? t('mapPractice.watchShownSquare') : t('mapPractice.watchShownChoice')}
          </span>
        )}
        {feedback?.kind === 'right' && <span className="text-emerald-700 font-medium">{t('mapPractice.right')}</span>}
        {feedback?.kind === 'again' && <span className="text-navy-700">{t('mapPractice.again')}</span>}
        {feedback?.kind === 'shown' && (
          <span className="text-navy-700">
            {feedback.reveal.cell
              ? t('mapPractice.shownSquare', { square: cellLabel(feedback.reveal.cell) })
              : t('mapPractice.shownChoice')}
          </span>
        )}
        {feedback?.kind === 'trouble' && <span role="alert" className="text-navy-700">{t('mapPractice.checkTrouble')}</span>}
      </div>

      {watching && !reduced.current && (
        <button type="button" onClick={() => setReplay((r) => r + 1)} className={secondary}>
          {t('mapPractice.watchAgain')}
        </button>
      )}
      {(watching || settled) && (
        <button type="button" onClick={next} className={primary}>
          {watching ? t('mapPractice.letsTry') : t('mapPractice.next')}
        </button>
      )}
    </RoutineShell>
  )
}

const primary = 'min-h-[44px] rounded-xl bg-navy-700 px-6 py-2.5 text-base font-medium text-white hover:bg-navy-600'
const secondary = 'min-h-[44px] rounded-xl border-2 border-sage-300 bg-white px-6 py-2.5 text-base font-medium text-navy-700'

/** Watch: how long the picture takes to settle flat, then each square of the way. */
export const MAP_WATCH_PAUSE_MS = 900
export const MAP_WATCH_STEP_MS = 600

function prefersReducedMotion(): boolean {
  try {
    return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}
