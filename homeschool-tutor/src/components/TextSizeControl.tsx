import { useEffect, useRef, useState } from 'react'
import { Minus, Plus, Type } from 'lucide-react'
import { useTextScale } from '../hooks/useTextScale'
import { useReadingPresentation } from '../hooks/useReadingPresentation'
import { useSessionStore } from '../store/sessionStore'
import type { LetterSpacing, LineSpacing } from '../utils/readingPresentation'

// How long the expanded panel stays open after the last tap before
// collapsing itself back down to the small icon-only button.
const AUTO_COLLAPSE_MS = 4000

/**
 * The reading settings, always within reach.
 *
 * Rendered once from AppShell so it's present on every page, including the
 * login screen, not duplicated per page. Sits below full-screen
 * modals/overlays (z-40, one under HandwritingCanvas/VoiceEnrollment/etc.'s
 * z-50) so it's naturally covered rather than floating on top of them.
 *
 * Text size is here because of WCAG 2.1 SC 1.4.4 (text must be resizable
 * without loss of content or functionality) and is available on every screen.
 * Letter and line spacing joined it, and only appear once a session is
 * loaded: they restyle the lesson text, so on a screen with no lesson on it
 * they would be three buttons that visibly do nothing.
 *
 * WHY THE SPACING ROWS ARE HERE AT ALL, given they are also a per-student
 * parent setting: see `useReadingPresentation.ts`. Short version — the
 * parent still owns the value and still has the last word, but the reader can
 * move it on the device in front of them, because an accommodation nobody can
 * reach mid-passage is not much of an accommodation.
 *
 * NOTHING HERE NAMES A CONDITION. The evidence behind each row lives in its
 * `title` and in `docs/SPECIAL_NEEDS.md`; the visible labels say what the
 * setting DOES. A control named after a diagnosis would have this software
 * assert one, which `_learning_support_note` already forbids Bede from doing
 * in words — see decision register entry 24.
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
 * The panel adds a third constraint of the same kind: `max-w`/`flex-wrap`/
 * `max-h` + `overflow-y-auto`, because at the top text step on a narrow phone
 * a fixed-width panel hangs off the edge of the screen and takes the "Normal"
 * option — the one a reader needs to undo a change they disliked — with it.
 */
export default function TextSizeControl() {
  const { scale, increase, decrease, canIncrease, canDecrease } = useTextScale()
  const sessionConfig = useSessionStore((s) => s.sessionConfig)
  const { presentation, setLetterSpacing, setLineSpacing } = useReadingPresentation(
    sessionConfig,
    sessionConfig?.student_name,
  )
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

  // No lesson on screen means nothing for the spacing rows to restyle.
  const showSpacing = !!sessionConfig?.student_name

  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => { setExpanded(true); scheduleCollapse() }}
        aria-label={
          showSpacing
            ? `Reading settings. Text size ${Math.round(scale)}%. Tap to adjust.`
            : `Text size, ${Math.round(scale)}%. Tap to adjust.`
        }
        title={showSpacing ? 'Reading settings' : 'Text size'}
        className="fixed top-3 right-3 z-40 flex items-center justify-center w-11 h-11 min-w-[44px] min-h-[44px] rounded-full bg-white/95 backdrop-blur border border-navy-200 shadow-md pt-safe pr-safe text-navy-500 hover:bg-navy-50 hover:text-navy-700 transition-colors"
      >
        <Type size={16} aria-hidden="true" />
      </button>
    )
  }

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
      aria-label={showSpacing ? 'Reading settings' : 'Text size'}
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

      {showSpacing && (
        <>
          <div>
            <span className="block text-xs text-navy-600 mb-1">Space between letters</span>
            <div
              className="flex flex-wrap gap-1"
              title="The best-supported of these. In a study of dyslexic 8-14 year olds, extra letter spacing doubled reading accuracy and made reading over 20% faster. Word spacing widens with it, so word boundaries stay clear."
            >
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
          </div>

          <div>
            <span className="block text-xs text-navy-600 mb-1">Space between lines</span>
            <div
              className="flex flex-wrap gap-1"
              title="Helps some readers keep their place when moving from one line to the next. General readability guidance rather than a measured result."
            >
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
          </div>
        </>
      )}
    </div>
  )
}
