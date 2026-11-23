import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CANVAS_SPEECH_GRACE_MS, useCanvasAfterSpeech } from './useCanvasAfterSpeech'

function setup() {
  const open = vi.fn()
  const hook = renderHook(({ speaking }) => useCanvasAfterSpeech(speaking, open), { initialProps: { speaking: false } })
  return { open, hook }
}

afterEach(() => vi.useRealTimers())

describe('useCanvasAfterSpeech', () => {
  it('opens when the turn ends and nothing is being said', () => {
    const { open, hook } = setup()
    act(() => hook.result.current.invite())
    expect(open).not.toHaveBeenCalled()
    act(() => hook.result.current.turnEnded(false))
    expect(open).toHaveBeenCalledTimes(1)
    expect(hook.result.current.waiting).toBe(false)
  })

  it('waits for speech that is reported a moment late, then for it to finish', () => {
    vi.useFakeTimers()
    const { open, hook } = setup()
    act(() => hook.result.current.invite())
    act(() => hook.result.current.turnEnded(true))
    // A render where the voice has not yet reported speaking must not count as finished.
    expect(open).not.toHaveBeenCalled()
    hook.rerender({ speaking: true })
    act(() => { vi.advanceTimersByTime(CANVAS_SPEECH_GRACE_MS * 5) })
    expect(open).not.toHaveBeenCalled()
    expect(hook.result.current.waiting).toBe(true)
    hook.rerender({ speaking: false })
    expect(open).toHaveBeenCalledTimes(1)
  })

  it('opens anyway if no speech ever starts', () => {
    vi.useFakeTimers()
    const { open, hook } = setup()
    act(() => hook.result.current.invite())
    act(() => hook.result.current.turnEnded(true))
    act(() => { vi.advanceTimersByTime(CANVAS_SPEECH_GRACE_MS - 1) })
    expect(open).not.toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(1) })
    expect(open).toHaveBeenCalledTimes(1)
  })

  it('does nothing without an invitation, and stops waiting when cancelled', () => {
    const { open, hook } = setup()
    act(() => hook.result.current.turnEnded(false))
    expect(open).not.toHaveBeenCalled()
    act(() => hook.result.current.invite())
    act(() => hook.result.current.cancel())
    act(() => hook.result.current.turnEnded(false))
    expect(open).not.toHaveBeenCalled()
  })
})
