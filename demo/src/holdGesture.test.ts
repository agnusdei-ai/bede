import { describe, expect, it, vi } from 'vitest'
import { createHoldHandlers } from './holdGesture'

/**
 * The regression these cover: a finger drifting off the mic button used to
 * end the recording mid-sentence, because `onPointerLeave` was wired
 * straight to the "send" callback with no pointer capture. See
 * holdGesture.ts's header.
 */

function makeEvent(overrides: Partial<{ captureThrows: boolean; pointerId: number }> = {}) {
  const { captureThrows = false, pointerId = 1 } = overrides
  const calls = { set: 0, release: 0 }
  const target = {
    setPointerCapture: (_id: number) => {
      calls.set++
      if (captureThrows) throw new Error('capture unavailable')
    },
    releasePointerCapture: (_id: number) => {
      calls.release++
    },
  }
  return {
    event: { currentTarget: target, pointerId } as unknown as React.PointerEvent,
    calls,
  }
}

describe('createHoldHandlers — with working pointer capture', () => {
  it('captures the pointer on press', () => {
    const onStart = vi.fn()
    const h = createHoldHandlers({ onStart, onEnd: vi.fn() })
    const { event, calls } = makeEvent()

    h.onPointerDown(event)

    expect(calls.set).toBe(1)
    expect(onStart).toHaveBeenCalledOnce()
  })

  it('IGNORES pointerleave — the actual bug', () => {
    // A child's finger sliding off a ~38px button must not end the turn.
    const onEnd = vi.fn()
    const h = createHoldHandlers({ onStart: vi.fn(), onEnd })
    const { event } = makeEvent()

    h.onPointerDown(event)
    h.onPointerLeave(event)

    expect(onEnd).not.toHaveBeenCalled()
  })

  it('still ends on a real finger lift after drifting off the button', () => {
    const onEnd = vi.fn()
    const h = createHoldHandlers({ onStart: vi.fn(), onEnd })
    const { event, calls } = makeEvent()

    h.onPointerDown(event)
    h.onPointerLeave(event) // drifted off — ignored
    h.onPointerLeave(event) // and back and forth
    h.onPointerUp(event)    // actual release

    expect(onEnd).toHaveBeenCalledOnce()
    expect(calls.release).toBe(1)
  })

  it('ends on a genuine pointercancel', () => {
    const onEnd = vi.fn()
    const h = createHoldHandlers({ onStart: vi.fn(), onEnd })
    const { event } = makeEvent()

    h.onPointerDown(event)
    h.onPointerCancel(event)

    expect(onEnd).toHaveBeenCalledOnce()
  })

  it('does not end twice when leave follows the release', () => {
    // Per spec, releasing capture can emit a deferred pointerleave. That
    // must not fire a second send.
    const onEnd = vi.fn()
    const h = createHoldHandlers({ onStart: vi.fn(), onEnd })
    const { event } = makeEvent()

    h.onPointerDown(event)
    h.onPointerUp(event)
    h.onPointerLeave(event)

    expect(onEnd).toHaveBeenCalledOnce()
  })
})

describe('createHoldHandlers — when capture is unavailable', () => {
  it('degrades to the old leave-ends-hold behavior rather than hanging', () => {
    // Worse than capture, but a hold that can only end at the 120s safety
    // ceiling would be far worse than one that ends early.
    const onEnd = vi.fn()
    const h = createHoldHandlers({ onStart: vi.fn(), onEnd })
    const { event } = makeEvent({ captureThrows: true })

    h.onPointerDown(event)
    h.onPointerLeave(event)

    expect(onEnd).toHaveBeenCalledOnce()
  })

  it('does not throw when setPointerCapture is missing entirely', () => {
    const onStart = vi.fn()
    const h = createHoldHandlers({ onStart, onEnd: vi.fn() })
    const event = { currentTarget: {}, pointerId: 1 } as unknown as React.PointerEvent

    expect(() => h.onPointerDown(event)).not.toThrow()
    expect(onStart).toHaveBeenCalledOnce()
  })

  it('still ends normally on pointerup', () => {
    const onEnd = vi.fn()
    const h = createHoldHandlers({ onStart: vi.fn(), onEnd })
    const { event } = makeEvent({ captureThrows: true })

    h.onPointerDown(event)
    h.onPointerUp(event)

    expect(onEnd).toHaveBeenCalledOnce()
  })
})

describe('createHoldHandlers — gesture isolation', () => {
  it('treats a leave with no prior press as a no-op', () => {
    // SocraticChat's own comment states this requirement directly: "a stray
    // pointerleave with no prior press is a no-op". The `active` guard is
    // what enforces it here, independently of the caller's holdingRef.
    const onEnd = vi.fn()
    const h = createHoldHandlers({ onStart: vi.fn(), onEnd })

    h.onPointerLeave(makeEvent().event)
    h.onPointerUp(makeEvent().event)

    expect(onEnd).not.toHaveBeenCalled()
  })

  it('keeps gesture state per handler set, not global', () => {
    const endA = vi.fn()
    const endB = vi.fn()
    const a = createHoldHandlers({ onStart: vi.fn(), onEnd: endA })
    const b = createHoldHandlers({ onStart: vi.fn(), onEnd: endB })

    // Both start; ending one must not end or disarm the other.
    a.onPointerDown(makeEvent().event)
    b.onPointerDown(makeEvent({ pointerId: 2 }).event)

    b.onPointerUp(makeEvent({ pointerId: 2 }).event)

    expect(endB).toHaveBeenCalledOnce()
    expect(endA).not.toHaveBeenCalled()

    a.onPointerUp(makeEvent().event)
    expect(endA).toHaveBeenCalledOnce()
  })

  it('re-arms capture across consecutive holds', () => {
    const onEnd = vi.fn()
    const h = createHoldHandlers({ onStart: vi.fn(), onEnd })

    const first = makeEvent()
    h.onPointerDown(first.event)
    h.onPointerUp(first.event)

    const second = makeEvent({ pointerId: 2 })
    h.onPointerDown(second.event)
    h.onPointerLeave(second.event) // must still be ignored on the 2nd hold

    expect(onEnd).toHaveBeenCalledOnce()
    expect(second.calls.set).toBe(1)
  })
})
