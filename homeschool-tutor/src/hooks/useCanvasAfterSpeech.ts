import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

/**
 * Opens the writing pad Bede invited the child to, but only once Bede has
 * finished saying what to draw or write.
 *
 * Bede's turn is spoken after it finishes streaming, so opening the pad the
 * moment its card arrived put the pad on screen while Bede was still talking:
 * the child was drawing over the instructions instead of hearing them, and
 * Bede never paused for their work. This waits for the turn to end and, when
 * the turn is being spoken, for the speech to start and stop.
 *
 * "Start" is observed rather than assumed: the voice's speaking flag can
 * reach the screen a moment after the turn's own end, so a render in between
 * would otherwise look finished. If no speech is seen within
 * CANVAS_SPEECH_GRACE_MS (no voice set up, a line that failed at once), the
 * pad opens anyway, so it can never be held back.
 *
 * Mirrored byte for byte in demo/src/useCanvasAfterSpeech.ts
 * (demo/src/canvasAfterSpeech.test.ts asserts it).
 */
export const CANVAS_SPEECH_GRACE_MS = 2000

type Wait = 'none' | 'turn' | 'speech'

export function useCanvasAfterSpeech(isSpeaking: boolean, open: () => void) {
  const [wait, setWaitState] = useState<Wait>('none')
  const waitRef = useRef<Wait>('none')
  const sawSpeaking = useRef(false)
  const openRef = useRef(open)
  useEffect(() => { openRef.current = open })

  const setWait = useCallback((next: Wait) => {
    waitRef.current = next
    setWaitState(next)
  }, [])

  /** Bede's turn invited the pad: open it when the turn is over. */
  const invite = useCallback(() => setWait('turn'), [setWait])

  /** The turn finished; `willSpeak` says whether it is being read aloud. */
  const turnEnded = useCallback((willSpeak: boolean) => {
    if (waitRef.current !== 'turn') return
    if (willSpeak) {
      sawSpeaking.current = false
      setWait('speech')
    } else {
      setWait('none')
      openRef.current()
    }
  }, [setWait])

  /** A new turn started, or the pad was opened by hand: stop waiting. */
  const cancel = useCallback(() => setWait('none'), [setWait])

  useEffect(() => {
    if (wait !== 'speech') return
    if (isSpeaking) {
      sawSpeaking.current = true
      return
    }
    if (sawSpeaking.current) {
      setWait('none')
      openRef.current()
      return
    }
    const timer = setTimeout(() => {
      if (waitRef.current === 'speech' && !sawSpeaking.current) {
        setWait('none')
        openRef.current()
      }
    }, CANVAS_SPEECH_GRACE_MS)
    return () => clearTimeout(timer)
  }, [wait, isSpeaking, setWait])

  const waiting = wait !== 'none'
  return useMemo(() => ({ invite, turnEnded, cancel, waiting }), [invite, turnEnded, cancel, waiting])
}
