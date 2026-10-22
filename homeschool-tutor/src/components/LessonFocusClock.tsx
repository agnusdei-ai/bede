import { useEffect, useRef, useState } from 'react'
import { Clock3, Pause } from 'lucide-react'

/**
 * A quiet, informational focus clock. Unlike the enforced session and eye-rest
 * limits (which remain wall-clock based), this displays time spent in a lesson
 * and excludes both mandatory and voluntary break time while mounted.
 */
export default function LessonFocusClock({ paused }: { paused: boolean }) {
  const accruedMs = useRef(0)
  const lastSampleMs = useRef(Date.now())
  const pausedRef = useRef(paused)
  const [elapsedMs, setElapsedMs] = useState(0)

  useEffect(() => {
    const sample = () => {
      const now = Date.now()
      if (!pausedRef.current) accruedMs.current += Math.max(0, now - lastSampleMs.current)
      lastSampleMs.current = now
      setElapsedMs(accruedMs.current)
    }
    // Account for the time between the last tick and a break transition.
    sample()
    pausedRef.current = paused
    const id = window.setInterval(sample, 1000)
    return () => window.clearInterval(id)
  }, [paused])

  const totalSeconds = Math.floor(elapsedMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = String(totalSeconds % 60).padStart(2, '0')
  return (
    <div
      role="timer"
      aria-label={paused ? 'Lesson timer paused for a break' : 'Active lesson time'}
      aria-live="off"
      title="Active lesson time only. Breaks are excluded. Session and screen-time limits remain in effect."
      className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-sage-200 bg-parchment-100 px-2.5 py-1 text-sage-800 shadow-sm"
    >
      {paused ? <Pause size={12} aria-hidden="true" /> : <Clock3 size={13} aria-hidden="true" />}
      <span className="font-serif text-[11px] font-medium tracking-wide">{paused ? 'Break' : 'Lesson'}</span>
      <span className="font-mono text-xs font-semibold tabular-nums">{minutes}:{seconds}</span>
    </div>
  )
}
