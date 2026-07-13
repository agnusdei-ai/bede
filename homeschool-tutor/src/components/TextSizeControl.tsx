import { Minus, Plus, Type } from 'lucide-react'
import { useTextScale } from '../hooks/useTextScale'

/**
 * Always-available text-size control (WCAG 2.1 SC 1.4.4: text must be
 * resizable without loss of content or functionality). Rendered once from
 * AppShell so it's present on every page, including the login screen, not
 * duplicated per page. Sits below full-screen modals/overlays (z-40, one
 * under HandwritingCanvas/VoiceEnrollment/etc.'s z-50) so it's naturally
 * covered rather than floating on top of them while one is open.
 */
export default function TextSizeControl() {
  const { scale, increase, decrease, canIncrease, canDecrease } = useTextScale()

  return (
    <div
      role="group"
      aria-label="Text size"
      className="fixed top-3 right-3 z-40 flex items-center gap-0.5 rounded-full bg-white/95 backdrop-blur border border-navy-200 shadow-md pt-safe pr-safe px-1.5 py-1"
    >
      <Type size={14} className="text-navy-400 mx-1" aria-hidden="true" />
      <button
        type="button"
        onClick={decrease}
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
        onClick={increase}
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
