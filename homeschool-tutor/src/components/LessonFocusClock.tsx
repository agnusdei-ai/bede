import { useEffect, useRef, useState } from 'react'
import { Clock3, Pause } from 'lucide-react'
import { effectiveSessionCap } from '../utils/gradeTimer'

type Mode = 'elapsed' | 'remaining'
const MODE_KEY = 'bede.instructor.lesson-clock-mode'

function readInstructorMode(): Mode {
  try { return window.localStorage.getItem(MODE_KEY) === 'remaining' ? 'remaining' : 'elapsed' }
  catch { return 'elapsed' }
}

/** Instruction-time display; enforcement remains on the existing wall-clock timers. */
export default function LessonFocusClock({
  paused, instructor = false, capMinutes,
}: {
  paused: boolean
  instructor?: boolean
  capMinutes?: number | null
}) {
  const accruedMs = useRef(0)
  const lastSampleMs = useRef(Date.now())
  const pausedRef = useRef(paused)
  const [elapsedMs, setElapsedMs] = useState(0)
  const [mode, setMode] = useState<Mode>(() => instructor ? readInstructorMode() : 'elapsed')

  useEffect(() => {
    const sample = () => {
      const now = Date.now()
      if (!pausedRef.current) accruedMs.current += Math.max(0, now - lastSampleMs.current)
      lastSampleMs.current = now
      setElapsedMs(accruedMs.current)
    }
    sample()
    pausedRef.current = paused
    const id = window.setInterval(sample, 1000)
    return () => window.clearInterval(id)
  }, [paused])

  const remaining = instructor && mode === 'remaining'
  const seconds = Math.floor(elapsedMs / 1000)
  const shownSeconds = remaining
    ? Math.max(0, effectiveSessionCap(capMinutes) * 60 - seconds)
    : seconds
  const time = `${Math.floor(shownSeconds / 60)}:${String(shownSeconds % 60).padStart(2, '0')}`
  const description = remaining
    ? 'Instruction-time countdown; breaks pause the clock. The separate wall-clock session limit remains enforced.'
    : 'Active lesson time; breaks pause the clock. Session and screen-time limits remain enforced.'
  const accessibleLabel = `${paused ? 'Paused for a break. ' : ''}${remaining ? 'Lesson time remaining' : 'Lesson time elapsed'}: ${time}`

  const face = (
    <>
      {paused ? <Pause size={12} aria-hidden="true" /> : <Clock3 size={13} aria-hidden="true" />}
      <span className="font-mono text-xs font-semibold tabular-nums">{time}</span>
    </>
  )
  const compact = 'inline-flex shrink-0 items-center gap-1.5 rounded-full border border-sage-200 bg-parchment-100 px-2.5 py-1 text-sage-800 shadow-sm'
  return instructor ? (
    <button
      type="button"
      aria-label={`${accessibleLabel}. Tap to show ${remaining ? 'elapsed' : 'remaining'} time.`}
      title={`${description} Tap to switch between elapsed and countdown.`}
      className={`${compact} focus-visible:outline focus-visible:outline-2 focus-visible:outline-sage-600`}
      onClick={() => {
        const next = remaining ? 'elapsed' : 'remaining'
        setMode(next)
        try { window.localStorage.setItem(MODE_KEY, next) } catch { /* Private browsing: session-only choice */ }
      }}
    >{face}</button>
  ) : (
    <div role="timer" aria-label={accessibleLabel} aria-live="off" title={description} className={compact}>
      {face}
    </div>
  )
}
