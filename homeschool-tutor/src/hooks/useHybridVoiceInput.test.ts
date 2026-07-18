/**
 * Regression coverage for a real reported failure: on Safari/iOS, dictation
 * would show as "listening" but never deliver anything to Bede — the
 * session just went quiet mid-conversation. Root cause: the native-Safari
 * stall watchdog (see useHybridVoiceInput.ts) was disarmed FOREVER the
 * moment a single interim result arrived, rather than reset on each one.
 * Safari's documented failure mode is stalling out PARTWAY through a
 * longer utterance (see useSpeechRecognition.ts's own comments), not just
 * at the very start — a one-shot disarm left every later stall in a
 * session with no fallback-to-recording safety net at all.
 *
 * useVoiceRecorder is mocked out entirely — this test only needs to prove
 * the fallback recording path gets STARTED after a stall, not that a full
 * recording/transcription round-trip completes.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { startRecording } = vi.hoisted(() => ({ startRecording: vi.fn() }))

vi.mock('./useVoiceRecorder', () => ({
  useVoiceRecorder: () => ({
    isRecording: false,
    level: 0,
    startRecording,
    stopRecording: vi.fn(),
  }),
}))

import { useHybridVoiceInput } from './useHybridVoiceInput'

class FakeSpeechRecognition {
  continuous = false
  interimResults = false
  lang = 'en-US'
  maxAlternatives = 1
  onstart: (() => void) | null = null
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onresult: ((e: any) => void) | null = null
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onerror: ((e: any) => void) | null = null
  onend: (() => void) | null = null
  started = false
  stopped = false

  start() {
    this.started = true
    this.onstart?.()
  }

  stop() {
    this.stopped = true
    this.onend?.()
  }

  emitInterim(text: string) {
    this.onresult?.({
      resultIndex: 0,
      results: [{ 0: { transcript: text }, isFinal: false, length: 1 }],
    })
  }

  emitFinal(text: string) {
    this.onresult?.({
      resultIndex: 0,
      results: [{ 0: { transcript: text }, isFinal: true, length: 1 }],
    })
  }
}

let lastInstance: FakeSpeechRecognition
// Counts how many native recognition sessions were ever constructed — the
// walkie-talkie invariant is that exactly ONE is created per explicit user
// press, and nothing (no timer, no effect) ever spins up another on its own.
let constructCount = 0

beforeEach(() => {
  vi.useFakeTimers()
  startRecording.mockClear()
  constructCount = 0
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).SpeechRecognition = class {
    constructor() {
      constructCount++
      lastInstance = new FakeSpeechRecognition()
      return lastInstance
    }
  }
})

afterEach(() => {
  vi.useRealTimers()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (window as any).SpeechRecognition
})

describe('useHybridVoiceInput stall watchdog', () => {
  it('falls back to recording when native recognition stalls mid-utterance after an interim result', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.start())
    act(() => lastInstance.emitInterim('the quick'))

    // Safari accepted the utterance, produced one interim result, then
    // went completely silent for good — no further onresult/onerror/onend.
    act(() => vi.advanceTimersByTime(4100))

    expect(startRecording).toHaveBeenCalledTimes(1)
  })

  it('does not fall back when interim results keep arriving before each stall window elapses', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.start())
    act(() => lastInstance.emitInterim('the'))
    act(() => vi.advanceTimersByTime(2000))
    act(() => lastInstance.emitInterim('the quick brown'))
    act(() => vi.advanceTimersByTime(2000))
    act(() => lastInstance.emitInterim('the quick brown fox'))
    act(() => vi.advanceTimersByTime(2000))

    // Chrome's real pattern: interim results throughout, no stall — must
    // never have been dumped into the fallback despite the total elapsed
    // time (6s) exceeding the 4s stall window.
    expect(startRecording).not.toHaveBeenCalled()
  })

  it('falls back immediately when native start() throws synchronously, without waiting for the stall watchdog', () => {
    // Reported failure: on iOS Safari, tapping the mic left the session
    // stuck showing "Listening…" forever with no interim text and nothing
    // ever reaching Bede. Root cause: start() throwing synchronously (a
    // real WebKit behavior for some permission/already-started edge cases)
    // happened BEFORE the stall watchdog's setTimeout was registered, so no
    // safety net was ever armed — the mode got stuck at 'native' permanently.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(window as any).SpeechRecognition = class {
      constructor() {
        throw new DOMException('already started', 'InvalidStateError')
      }
    }

    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.start())

    expect(startRecording).toHaveBeenCalledTimes(1)
  })
})

describe('useHybridVoiceInput walkie-talkie (hold-to-talk)', () => {
  it('keeps one session open across natural pauses and sends the accumulated transcript once on release', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    // Press and hold: a single CONTINUOUS native session starts.
    act(() => result.current.startHold())
    expect(constructCount).toBe(1)
    expect(lastInstance.continuous).toBe(true)

    // The child talks in bursts with real pauses between them. Each burst
    // settles into a FINAL segment; nothing is sent yet — it accumulates.
    act(() => lastInstance.emitInterim('the quick'))
    act(() => lastInstance.emitFinal('the quick brown fox'))
    act(() => vi.advanceTimersByTime(3000))
    act(() => lastInstance.emitFinal('jumps over'))
    expect(onFinal).not.toHaveBeenCalled()

    // A pause longer than the tap-mode stall window must NOT fall back to
    // recording in hold mode — the child, not a timer, decides when it ends.
    act(() => vi.advanceTimersByTime(6000))
    expect(startRecording).not.toHaveBeenCalled()

    // Child lets go: the whole utterance is delivered exactly once.
    act(() => result.current.release())
    expect(onFinal).toHaveBeenCalledTimes(1)
    expect(onFinal).toHaveBeenCalledWith('the quick brown fox jumps over')
    // Still only ever ONE native session — nothing restarted it.
    expect(constructCount).toBe(1)
  })

  it('salvages the latest interim on release when the engine never promoted it to a final segment', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    // The child spoke but the engine only ever produced interim text (no
    // final settled before release) — release must still send what it heard.
    act(() => lastInstance.emitInterim('hello Bede'))
    act(() => result.current.release())

    expect(onFinal).toHaveBeenCalledTimes(1)
    expect(onFinal).toHaveBeenCalledWith('hello Bede')
  })

  it('does not send anything when the child releases without having spoken', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    act(() => result.current.release())

    expect(onFinal).not.toHaveBeenCalled()
  })

  it('never restarts recognition on its own after a tap utterance settles (no auto-restart loop)', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.start())
    expect(constructCount).toBe(1)

    // A finished tap utterance sends and goes idle.
    act(() => lastInstance.emitFinal('done'))
    expect(onFinal).toHaveBeenCalledTimes(1)

    // Let a long time pass with no user interaction whatsoever. The old
    // "voice mode" would have re-armed the mic on a timer here; the hook must
    // never construct a second session on its own.
    act(() => vi.advanceTimersByTime(60000))
    expect(constructCount).toBe(1)
    expect(startRecording).not.toHaveBeenCalled()
  })

  it('discards the utterance on stop() (cancel) without sending, even mid-hold', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    act(() => lastInstance.emitFinal('never mind'))
    // stop() is cancel, not release — nothing should be delivered.
    act(() => result.current.stop())

    expect(onFinal).not.toHaveBeenCalled()
    expect(constructCount).toBe(1)
  })

  it('auto-releases after the hold safety timeout if release is never called (missed pointerup)', () => {
    // Regression guard for a real risk introduced by removing the walkie-talkie
    // toggle: with the mic ALWAYS in hold mode and no manual toggle to clear a
    // stuck state, a dropped pointerup (common on some Android WebViews, or a
    // finger sliding off the button) must not leave the mic listening forever
    // with zero recourse.
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    act(() => lastInstance.emitFinal('are you still there'))
    // No release() call at all — simulates a pointerup that never arrived.
    act(() => vi.advanceTimersByTime(60000))

    expect(onFinal).toHaveBeenCalledTimes(1)
    expect(onFinal).toHaveBeenCalledWith('are you still there')
    expect(result.current.isListening).toBe(false)
  })

  it('does not auto-release if the child already released well before the safety timeout', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    act(() => lastInstance.emitFinal('quick answer'))
    act(() => result.current.release())
    expect(onFinal).toHaveBeenCalledTimes(1)

    // Letting the old safety timer's window elapse afterward must not fire
    // a second, stale release.
    act(() => vi.advanceTimersByTime(60000))
    expect(onFinal).toHaveBeenCalledTimes(1)
  })
})
