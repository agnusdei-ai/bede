/**
 * Pointer-event wiring for a press-and-hold ("walkie-talkie") button.
 *
 * Why this exists: the mic button's handlers used to be
 *
 *     onPointerDown={holdStart}
 *     onPointerUp={holdEnd}
 *     onPointerLeave={holdEnd}     // <- the bug
 *     onPointerCancel={holdEnd}
 *
 * with no pointer capture. `pointerleave` fires the moment the pointer
 * crosses outside the element's box, so a finger that drifts a few pixels
 * off a ~38px button mid-hold fired `holdEnd` and ENDED THE RECORDING —
 * silently, mid-sentence, with no error and nothing in the transcript to
 * explain it. On a tablet, held by a child, against a small target, that is
 * not an edge case; it is the common case, and it reads to a parent as "the
 * voice button is unreliable."
 *
 * `setPointerCapture()` is the fix. Once the pointer is captured, the
 * capturing element receives every subsequent event for that pointer no
 * matter where it travels, and boundary events (`pointerleave`/`pointerout`)
 * are suppressed while capture is held. The hold then ends only when the
 * child actually lifts their finger, which is the entire contract of a
 * press-and-hold control.
 *
 * This app already knew the technique — HandwritingCanvas.tsx captures the
 * pointer so a drawing stroke survives leaving the canvas bounds. The mic
 * button simply never got the same treatment.
 *
 * `onPointerLeave` is kept, but only as a fallback for the case where
 * capture could not be established at all (very old WebViews, or a
 * synthetic pointer with no real id). When capture succeeded, a leave event
 * is ignored, because the whole point is that leaving the box is not the
 * end of the gesture.
 */

export interface HoldGestureCallbacks {
  /** Begin the hold. Receives the original event so the caller can preventDefault. */
  onStart: (e: React.PointerEvent) => void
  /** End the hold — send. Called exactly once per gesture. */
  onEnd: (e: React.PointerEvent) => void
}

export interface HoldGestureHandlers {
  onPointerDown: (e: React.PointerEvent) => void
  onPointerUp: (e: React.PointerEvent) => void
  onPointerLeave: (e: React.PointerEvent) => void
  onPointerCancel: (e: React.PointerEvent) => void
}

/**
 * Builds the pointer handlers for a press-and-hold button.
 *
 * `captureState` is an object the caller owns (a `useRef().current`-style
 * box) so the handlers stay pure with respect to React rendering — nothing
 * here reaches for module state, and two buttons never share capture
 * status.
 */
export function createHoldHandlers(
  callbacks: HoldGestureCallbacks,
  gestureState: { active: boolean; captured: boolean } = { active: false, captured: false },
): HoldGestureHandlers {
  // `active` is tracked separately from `captured` on purpose. Releasing
  // capture necessarily clears `captured`, and the spec allows a deferred
  // `pointerleave` to arrive immediately afterwards — so a single flag
  // would let that trailing leave fall through the "capture unavailable"
  // branch below and fire a SECOND send for one gesture. (Caught by
  // holdGesture.test.ts; the callers happen to carry their own
  // `holdingRef` guard, but this helper must be correct on its own rather
  // than depending on every call site to re-derive that.)
  //
  // `active` is therefore the single authority for "a gesture is still in
  // progress", and `end()` is the only place it is cleared.
  const end = (e: React.PointerEvent) => {
    if (!gestureState.active) return
    gestureState.active = false

    if (gestureState.captured) {
      gestureState.captured = false
      try {
        // Best-effort: the element may already have lost capture
        // implicitly (pointercancel does exactly that), in which case
        // this throws and there is nothing left to clean up.
        e.currentTarget.releasePointerCapture?.(e.pointerId)
      } catch {
        /* already released */
      }
    }

    callbacks.onEnd(e)
  }

  return {
    onPointerDown: (e) => {
      gestureState.active = true
      gestureState.captured = false
      try {
        e.currentTarget.setPointerCapture?.(e.pointerId)
        gestureState.captured = true
      } catch {
        // No capture available. The onPointerLeave fallback below stays
        // live for this gesture so the hold can still be ended by leaving
        // the button — the old, lossy behavior, but far better than a hold
        // that can only end at the 120-second safety ceiling.
        gestureState.captured = false
      }
      callbacks.onStart(e)
    },

    onPointerUp: end,

    // Only meaningful when capture failed — see this module's header.
    onPointerLeave: (e) => {
      if (gestureState.captured) return
      end(e)
    },

    // A genuine cancellation (the OS took the pointer away: an incoming
    // call, a system gesture). Capture is already implicitly lost.
    onPointerCancel: (e) => {
      gestureState.captured = false
      end(e)
    },
  }
}
