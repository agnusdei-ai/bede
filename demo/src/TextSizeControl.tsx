import { useEffect, useRef, useState } from 'react'
import { Minus, Plus, Type } from 'lucide-react'
import { useTextScale } from './useTextScale'

// How long the expanded +/- control stays open after the last tap before
// collapsing itself back down to the small icon-only button.
const AUTO_COLLAPSE_MS = 4000

/**
 * Always-available text-size control (WCAG 2.1 SC 1.4.4: text must be
 * resizable without loss of content or functionality). Rendered once from
 * main.tsx so it's present on every screen. Sits below full-screen
 * overlays (z-40, one under HandwritingCanvas etc.'s z-50) so it's
 * naturally covered rather than floating on top of them while one is open.
 *
 * Minimized to a small icon-only button by default rather than the full
 * +/-/percentage pill — fixed-position at top-right, it was sitting
 * directly over chat text on narrower/tablet viewports since it floats
 * above page content rather than reserving layout space. Tapping it
 * expands to the full control; it auto-collapses back to the icon after
 * AUTO_COLLAPSE_MS of no further taps, so the larger control is only ever
 * on screen while actively being used, not permanently blocking text.
 */
export default function TextSizeControl() {
  const { scale, increase, decrease, canIncrease, canDecrease } = useTextScale()
  const [expanded, setExpanded] = useState(false)
  const collapseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const scheduleCollapse = () => {
    if (collapseTimerRef.current) clearTimeout(collapseTimerRef.current)
    collapseTimerRef.current = setTimeout(() => setExpanded(false), AUTO_COLLAPSE_MS)
  }

  useEffect(() => {
    return () => {
      if (collapseTimerRef.current) clearTimeout(collapseTimerRef.current)
    }
  }, [])

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => { setExpanded(true); scheduleCollapse() }}
        aria-label={`Text size, ${Math.round(scale)}%. Tap to adjust.`}
        title="Text size"
        className="fixed top-3 right-3 z-40 flex items-center justify-center w-9 h-9 rounded-full bg-white/95 backdrop-blur border border-navy-200 shadow-md pt-safe pr-safe text-navy-500 hover:bg-navy-50 hover:text-navy-700 transition-colors"
      >
        <Type size={16} aria-hidden="true" />
      </button>
    )
  }

  return (
    <div
      role="group"
      aria-label="Text size"
      className="fixed top-3 right-3 z-40 flex items-center gap-0.5 rounded-full bg-white/95 backdrop-blur border border-navy-200 shadow-md pt-safe pr-safe px-1.5 py-1"
    >
      <Type size={14} className="text-navy-400 mx-1" aria-hidden="true" />
      <button
        type="button"
        onClick={() => { decrease(); scheduleCollapse() }}
        disabled={!canDecrease}
        aria-label="Decrease text size"
        title="Decrease text size"
        className="w-7 h-7 flex items-center justify-center rounded-full text-navy-600 hover:bg-navy-100 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
      >
        <Minus size={14} />
      </button>
      <span className="text-[11px] text-navy-500 w-10 text-center tabular-nums" aria-live="polite">
        {Math.round(scale)}%
      </span>
      <button
        type="button"
        onClick={() => { increase(); scheduleCollapse() }}
        disabled={!canIncrease}
        aria-label="Increase text size"
        title="Increase text size"
        className="w-7 h-7 flex items-center justify-center rounded-full text-navy-600 hover:bg-navy-100 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
      >
        <Plus size={14} />
      </button>
    </div>
  )
}
