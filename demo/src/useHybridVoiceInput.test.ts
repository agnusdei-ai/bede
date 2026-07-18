/**
 * Mirror of homeschool-tutor/src/hooks/useHybridVoiceInput.test.ts — see
 * that file's own comment for the full story. Regression coverage for a
 * real reported failure: on Safari/iOS, dictation would show as
 * "listening" but never deliver anything to Bede — the session just went
 * quiet mid-conversation. Root cause: the native-Safari stall watchdog was
 * disarmed FOREVER the moment a single interim result arrived, rather than
 * reset on each one.
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

beforeEach(() => {
  vi.useFakeTimers()
  startRecording.mockClear()
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).SpeechRecognition = class {
    constructor() {
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

describe('useHybridVoiceInput stall watchdog (demo)', () => {
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

describe('useHybridVoiceInput walkie-talkie hold safety (demo)', () => {
  // Mirror of the same-named tests in
  // homeschool-tutor/src/hooks/useHybridVoiceInput.test.ts — see that
  // file's comment for the full rationale: with the mic ALWAYS in hold
  // mode and no manual toggle left to clear a stuck state, a missed
  // release event must not leave the mic listening forever.
  it('auto-releases after the hold safety timeout if release is never called (missed pointerup)', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    act(() => lastInstance.emitFinal('are you still there'))
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

    act(() => vi.advanceTimersByTime(60000))
    expect(onFinal).toHaveBeenCalledTimes(1)
  })

  it('falls back to recording if native produces zero signal for the whole hold-start window (Safari silent-hold bug)', () => {
    // Real reported failure: on iOS Safari, holding the mic showed
    // "Listening..." the whole time, but releasing after several seconds
    // of real speech sent nothing at all and no transcript ever appeared.
    // See homeschool-tutor/src/hooks/useHybridVoiceInput.test.ts for the
    // full rationale.
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    expect(startRecording).not.toHaveBeenCalled()

    act(() => vi.advanceTimersByTime(4100))

    expect(startRecording).toHaveBeenCalledTimes(1)
    expect(result.current.isListening).toBe(true)
  })

  it('does not fall back to recording in hold mode once native has proven it is alive, even across a long pause', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    act(() => vi.advanceTimersByTime(1000))
    act(() => lastInstance.emitInterim('hi'))

    act(() => vi.advanceTimersByTime(10000))
    expect(startRecording).not.toHaveBeenCalled()

    act(() => lastInstance.emitFinal('hi there'))
    act(() => result.current.release())
    expect(onFinal).toHaveBeenCalledWith('hi there')
  })
})
