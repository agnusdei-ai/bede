import { useEffect, useRef, useState } from 'react'
import { Minus, Plus, Type } from 'lucide-react'
import { useTextScale } from '../hooks/useTextScale'
import { useTranslation } from 'react-i18next'

// How long the expanded +/- control stays open after the last tap before
// collapsing itself back down to the small icon-only button.
const AUTO_COLLAPSE_MS = 4000

/**
 * Always-available text-size control (WCAG 2.1 SC 1.4.4: text must be
 * resizable without loss of content or functionality). Rendered once from
 * AppShell so it's present on every page, including the login screen, not
 * duplicated per page. Sits below full-screen modals/overlays (z-40, one
 * under HandwritingCanvas/VoiceEnrollment/etc.'s z-50) so it's naturally
 * covered rather than floating on top of them while one is open.
 *
 * SIZING, measured in real Chromium across device viewports rather than
 * reasoned about — jsdom performs no layout, so none of it is visible to a
 * component test. Two defects were found that way and are fixed here:
 *
 *   - the collapsed button was 36px and the +/- buttons 28px (24.5px at the
 *     smallest text step). WCAG 2.5.8 asks for 24 and 2.5.5 for 44; this runs
 *     on a child's tablet, so 44 it is, as a PIXEL floor rather than a rem
 *     one — a finger does not get smaller when someone scales text down.
 *   - the percentage readout was `text-[11px]`, a literal pixel value, and
 *     this control works by scaling the ROOT font size. The one number
 *     telling a reader what they just set was the one thing that never got
 *     bigger. It is a rem class now.
 *
 * Found while giving the demo's copy the same treatment — the two share a
 * lineage, so the defect was in both.
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
  const { t } = useTranslation()
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
        aria-label={t('reading.textSizeTap', { pct: Math.round(scale) })}
        title={t('reading.textSize')}
        className="fixed top-3 right-3 z-40 flex items-center justify-center w-11 h-11 min-w-[44px] min-h-[44px] rounded-full bg-white/95 backdrop-blur border border-navy-200 shadow-md pt-safe pr-safe text-navy-500 hover:bg-navy-50 hover:text-navy-700 transition-colors"
      >
        <Type size={16} aria-hidden="true" />
      </button>
    )
  }

  return (
    <div
      role="group"
      aria-label={t('reading.textSize')}
      className="fixed top-3 right-3 z-40 flex items-center gap-0.5 rounded-full bg-white/95 backdrop-blur border border-navy-200 shadow-md pt-safe pr-safe px-1.5 py-1"
    >
      <Type size={14} className="text-navy-400 mx-1" aria-hidden="true" />
      <button
        type="button"
        onClick={() => { decrease(); scheduleCollapse() }}
        disabled={!canDecrease}
        aria-label={t('reading.decrease')}
        title={t('reading.decrease')}
        className="w-11 h-11 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full text-navy-600 hover:bg-navy-100 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
      >
        <Minus size={14} />
      </button>
      <span className="text-xs text-navy-500 min-w-[2.75rem] text-center tabular-nums" aria-live="polite">
        {Math.round(scale)}%
      </span>
      <button
        type="button"
        onClick={() => { increase(); scheduleCollapse() }}
        disabled={!canIncrease}
        aria-label={t('reading.increase')}
        title={t('reading.increase')}
        className="w-11 h-11 min-w-[44px] min-h-[44px] flex items-center justify-center rounded-full text-navy-600 hover:bg-navy-100 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
      >
        <Plus size={14} />
      </button>
    </div>
  )
}
