import { useEffect, useRef, useState } from 'react'
import { Minus, Plus, Type } from 'lucide-react'
import { useTextScale } from './useTextScale'
import { useReadingPresentation } from './useReadingPresentation'
import type { LetterSpacing, LineSpacing } from './readingPresentation'

// How long the expanded panel stays open after the last interaction before
// collapsing itself back down to the small icon-only button.
const AUTO_COLLAPSE_MS = 8000

/**
 * Always-available reading controls: text size, letter spacing, line spacing.
 * Rendered once from main.tsx so it's present on every screen. Sits below
 * full-screen overlays (z-40, one under HandwritingCanvas etc.'s z-50) so
 * it's naturally covered rather than floating on top of them while one is
 * open.
 *
 * WHY TEXT SIZE AND SPACING SHARE ONE CONTROL
 *
 * This began as text size alone (WCAG 2.1 SC 1.4.4: text must be resizable
 * without loss of content or functionality). Letter and line spacing joined
 * it because they are the same question a reader is asking — "make this
 * easier to read" — and a second floating button would crowd a corner that
 * already reserves clearance on narrow viewports.
 *
 * The three are NOT equally well founded, and the panel says so rather than
 * presenting three equal-looking sliders:
 *
 *   - Letter spacing is the one with real evidence. Zorzi et al. (2012,
 *     PNAS) found extra letter spacing doubled reading accuracy and raised
 *     reading speed over 20% in dyslexic 8-14 year olds, replicated across
 *     two languages. It widens word spacing with it, deliberately — see
 *     readingPresentation.ts.
 *   - Line spacing rests on general readability guidance, not a measured
 *     effect for that population.
 *   - Text size is a preference: bigger is not reliably better and the
 *     direction reverses with age (Katzir et al. 2013).
 *
 * See docs/ACCESSIBILITY_RESEARCH.md. There is deliberately no dyslexia
 * font: the peer-reviewed evidence for those is negative.
 *
 * Minimized to a small icon-only button by default rather than the full
 * panel — fixed-position at top-right, it was sitting directly over chat
 * text on narrower/tablet viewports since it floats above page content
 * rather than reserving layout space. Tapping it expands; it auto-collapses
 * after AUTO_COLLAPSE_MS of no further interaction, so the larger panel is
 * only ever on screen while actively being used, not permanently blocking
 * text.
 */
export default function TextSizeControl() {
  const { scale, increase, decrease, canIncrease, canDecrease } = useTextScale()
  const { presentation, setLetterSpacing, setLineSpacing } = useReadingPresentation()
  const [expanded, setExpanded] = useState(false)
  const collapseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // SIZING, measured across real device viewports in real Chromium rather
  // than reasoned about — jsdom performs no layout, so none of this is
  // visible to a component test. The first cut failed three ways at once and
  // every one hit a phone hardest, which is the device this runs on:
  //
  //   - 420px wide at the top text-size step against a 360-390px phone, so
  //     the panel hung 81px off the left edge and took the "Normal" option in
  //     both rows with it — the one a visitor needs to undo a change they did
  //     not like. max-w clamps it; flex-wrap lets the rows stack rather than
  //     crushing three buttons into what is left.
  //   - 17px tap targets, at every scale on every device. WCAG 2.5.8 asks for
  //     24px and 2.5.5 for 44; this is a child's tablet, so 44 it is, as a
  //     PIXEL floor rather than a rem one: a finger does not get smaller when
  //     someone scales text down.
  //   - every label pinned at 10-11px, because `text-[11px]` is a literal
  //     pixel value and useTextScale works by scaling the ROOT font size. The
  //     panel that exists to make text bigger was the one thing that never
  //     got bigger. Everything is a rem-based class now.
  //
  // max-h + overflow-y-auto is the fourth: at the top step on a landscape
  // phone the panel is taller than the 390px viewport, and a settings panel
  // you cannot scroll to the bottom of is one with hidden settings.
  //
  // After: 44px minimum tap target and no overflow across seven viewports at
  // three scales; labels 12.08 / 13.8 / 24.15px at 87.5 / 100 / 175%.

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
        aria-label={`Reading settings. Text size ${Math.round(scale)}%. Tap to adjust.`}
        title="Reading settings"
        className="fixed top-3 right-3 z-40 flex items-center justify-center w-9 h-9 rounded-full bg-white/95 backdrop-blur border border-navy-200 shadow-md pt-safe pr-safe text-navy-500 hover:bg-navy-50 hover:text-navy-700 transition-colors"
      >
        <Type size={16} aria-hidden="true" />
      </button>
    )
  }

  // Each row's options, with the honest label. `note` is what this setting is
  // and is not supported by — the thing a reader has no way to know, and the
  // reason three identical-looking rows would be misleading.
  const letterOptions: ReadonlyArray<{ value: LetterSpacing; label: string }> = [
    { value: 'normal', label: 'Normal' },
    { value: 'wide', label: 'Wide' },
    { value: 'wider', label: 'Widest' },
  ]
  const lineOptions: ReadonlyArray<{ value: LineSpacing; label: string }> = [
    { value: 'normal', label: 'Normal' },
    { value: 'relaxed', label: 'Relaxed' },
    { value: 'loose', label: 'Loosest' },
  ]

  const rowButton = (selected: boolean) =>
    `flex-1 min-h-[44px] px-2 py-1 rounded-md text-xs flex items-center justify-center text-center transition-colors ${
      selected
        ? 'bg-navy-500 text-white'
        : 'bg-white text-navy-600 border border-navy-200 hover:bg-navy-50'
    }`

  return (
    <div
      role="group"
      aria-label="Reading settings"
      onPointerDown={scheduleCollapse}
      className="fixed top-3 right-3 z-40 w-60 max-w-[calc(100vw-1.5rem)] max-h-[calc(100dvh-1.5rem)] overflow-y-auto rounded-2xl bg-white/97 backdrop-blur border border-navy-200 shadow-lg pt-safe pr-safe px-3 py-2.5 flex flex-col gap-2.5"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-navy-700">Reading</span>
        <button
          type="button"
          onClick={() => setExpanded(false)}
          aria-label="Close reading settings"
          className="text-xs text-navy-400 hover:text-navy-600 px-2 min-h-[44px] -my-2"
        >
          Done
        </button>
      </div>

      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-navy-600">Text size</span>
          <span className="text-xs text-navy-400 tabular-nums" aria-live="polite">
            {Math.round(scale)}%
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => { decrease(); scheduleCollapse() }}
            disabled={!canDecrease}
            aria-label="Decrease text size"
            title="Decrease text size"
            className="flex-1 min-h-[44px] flex items-center justify-center rounded-md border border-navy-200 text-navy-600 hover:bg-navy-50 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
          >
            <Minus size={14} />
          </button>
          <button
            type="button"
            onClick={() => { increase(); scheduleCollapse() }}
            disabled={!canIncrease}
            aria-label="Increase text size"
            title="Increase text size"
            className="flex-1 min-h-[44px] flex items-center justify-center rounded-md border border-navy-200 text-navy-600 hover:bg-navy-50 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
          >
            <Plus size={14} />
          </button>
        </div>
      </div>

      <div>
        <span className="block text-xs text-navy-600 mb-1">Space between letters</span>
        <div className="flex flex-wrap gap-1">
          {letterOptions.map((o) => (
            <button
              key={o.value}
              type="button"
              aria-pressed={presentation.letter_spacing === o.value}
              onClick={() => { setLetterSpacing(o.value); scheduleCollapse() }}
              className={rowButton(presentation.letter_spacing === o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>
        <p className="text-xs leading-snug text-navy-400 mt-1">
          The one with real evidence behind it: in a study of dyslexic 8-14
          year olds, extra letter spacing doubled reading accuracy.
        </p>
      </div>

      <div>
        <span className="block text-xs text-navy-600 mb-1">Space between lines</span>
        <div className="flex flex-wrap gap-1">
          {lineOptions.map((o) => (
            <button
              key={o.value}
              type="button"
              aria-pressed={presentation.line_spacing === o.value}
              onClick={() => { setLineSpacing(o.value); scheduleCollapse() }}
              className={rowButton(presentation.line_spacing === o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>
        <p className="text-xs leading-snug text-navy-400 mt-1">
          Helps some readers keep their place. General readability guidance,
          not a measured result.
        </p>
      </div>
    </div>
  )
}
