import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'

/**
 * An icon control that says what it is — on a touch screen too.
 *
 * ## The gap this closes
 *
 * The writing canvas is mostly icon-only controls: pen, pencil, eraser, three
 * brush sizes, eight ink colours, six paper styles. Every one of them carried
 * a `title` attribute and nothing else.
 *
 * `title` renders a tooltip **on hover**, and a tablet has no hover. Bede's
 * primary device is a child's tablet, so the one affordance explaining what
 * any of these buttons did was unreachable on the device almost every user
 * holds. On a phone it is worse: the action buttons hide their text labels
 * below the `sm` breakpoint, so Undo, Redo, New page, Save and Print become
 * unlabelled icons as well.
 *
 * There were also zero `aria-label`s in either canvas. `title` can serve as an
 * accessible name, but it is the fallback of last resort in the accessible-name
 * calculation, and it is the wrong primitive to be relying on.
 *
 * ## How the label is revealed
 *
 * Three triggers, because three different people are using this:
 *
 * - **Hover** (mouse) — the conventional desktop behaviour, preserved.
 * - **Focus** (keyboard) — so tabbing through the toolbar narrates it too.
 * - **After a touch activation** — the tooltip appears for {@link TOUCH_HINT_MS}
 *   when the control is tapped, and the tap still does what it always did.
 *
 * That third one is the important one, and it is deliberately *not* a
 * long-press. A long-press is a gesture a child has to already know about, and
 * on this component in particular it would compete with drawing. Showing the
 * label on the tap that already happened means every press quietly names what
 * it just did — no gesture to learn, no manual, and nothing to discover. A
 * child who taps the pencil sees "Pencil" and has learned the toolbar by using
 * it.
 *
 * The tooltip never blocks the action and never swallows the event.
 *
 * ## Why it is positioned `fixed`
 *
 * Both toolbar rows are `overflow-x-auto`. A computed `overflow-x` of `auto`
 * forces `overflow-y` to `auto` as well, so an absolutely-positioned tooltip
 * inside those rows would be clipped vertically — it would simply not appear.
 * Measuring the trigger and positioning against the viewport avoids that
 * entirely, at the cost of recalculating on show, which is once per reveal.
 */

/** How long the label stays up after a touch activation. */
export const TOUCH_HINT_MS = 1600

interface IconButtonProps {
  /**
   * What this control is, in a word or two, already translated by the caller.
   * Used as BOTH the accessible name and the tooltip text — one string, so the
   * two can never disagree.
   */
  label: string
  onClick: () => void
  /** Optional: the colour swatches are bare circles styled by className,
   *  with no icon inside them. */
  children?: ReactNode
  className?: string
  /** The ink and paper swatches carry their own colour inline. */
  style?: CSSProperties
  disabled?: boolean
  /** For toggle controls (the pen/pencil/eraser group). */
  pressed?: boolean
  /**
   * Set when the control renders its own visible text.
   *
   * `aria-label` OVERRIDES an element's text content in the accessible-name
   * calculation, so applying it unconditionally would rename every button
   * that already had a perfectly good visible name — "New page" would start
   * announcing as "Start a new page", and WCAG's label-in-name expectation
   * (the accessible name should contain the visible text) would be broken
   * along with it. Caught by the existing canvas tests, which query these
   * buttons by their visible names.
   *
   * When true, the visible text stays the accessible name and `label` is
   * used only for the tooltip.
   */
  textual?: boolean
  /**
   * Optional visible text beside the icon. Callers pass their own responsive
   * classes; the tooltip works the same either way, which matters because the
   * action buttons show their text on a tablet and hide it on a phone.
   */
  visibleLabel?: ReactNode
}

export default function IconButton({
  label,
  onClick,
  children = null,
  className = '',
  style,
  disabled = false,
  pressed,
  textual = false,
  visibleLabel,
}: IconButtonProps) {
  const buttonRef = useRef<HTMLButtonElement>(null)
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Set on pointerdown, read on click: a click event does not carry
  // pointerType, and we only want the timed reveal for touch.
  const lastPointerWasTouch = useRef(false)
  const [tip, setTip] = useState<{ top: number; left: number } | null>(null)

  const clearHideTimer = useCallback(() => {
    if (hideTimer.current) {
      clearTimeout(hideTimer.current)
      hideTimer.current = null
    }
  }, [])

  const show = useCallback(() => {
    const element = buttonRef.current
    if (!element) return
    const rect = element.getBoundingClientRect()
    // Below the control, horizontally centred. Below rather than above because
    // these toolbars sit at the top of the screen, where there is nothing above
    // them to render into.
    setTip({ top: rect.bottom + 6, left: rect.left + rect.width / 2 })
  }, [])

  const hide = useCallback(() => {
    clearHideTimer()
    setTip(null)
  }, [clearHideTimer])

  // A tooltip that outlives its trigger would be stranded on screen with
  // nothing to dismiss it — the canvas unmounts whenever the child returns to
  // the chat.
  useEffect(() => clearHideTimer, [clearHideTimer])

  const handlePointerDown = (event: React.PointerEvent<HTMLButtonElement>) => {
    lastPointerWasTouch.current = event.pointerType === 'touch'
  }

  const handleClick = () => {
    // The action always happens first. The label is an explanation of what
    // just occurred, never a gate in front of it.
    onClick()
    if (lastPointerWasTouch.current) {
      show()
      clearHideTimer()
      hideTimer.current = setTimeout(() => setTip(null), TOUCH_HINT_MS)
    }
  }

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={handleClick}
        onPointerDown={handlePointerDown}
        // Hover is mouse-only by construction: a touch tap also fires
        // pointerenter on many browsers, and letting it through here would
        // leave the label stuck up until the child touched something else.
        onPointerEnter={(e) => { if (e.pointerType === 'mouse') show() }}
        onPointerLeave={hide}
        onFocus={show}
        onBlur={hide}
        disabled={disabled}
        aria-label={textual ? undefined : label}
        aria-pressed={pressed}
        className={className}
        style={style}
      >
        {children}
        {visibleLabel}
      </button>
      {tip && (
        <span
          role="tooltip"
          // Presentational only — the accessible name is already on the
          // button, so a screen reader must not read this a second time.
          aria-hidden="true"
          style={{ top: tip.top, left: tip.left }}
          className="fixed z-[60] -translate-x-1/2 pointer-events-none whitespace-nowrap rounded-md bg-gray-900/90 px-2 py-1 text-xs font-medium text-white shadow-lg"
        >
          {label}
        </span>
      )}
    </>
  )
}
