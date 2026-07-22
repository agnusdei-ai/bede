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

const { startRecording, prewarm, cancelPrewarm, recorderOptions, transcribeFallback, enterRecordingAudioSession, restorePlaybackAudioSession } = vi.hoisted(() => ({
  startRecording: vi.fn(),
  prewarm: vi.fn(),
  cancelPrewarm: vi.fn(),
  // Captures the options useHybridVoiceInput passes to useVoiceRecorder —
  // tests below call recorderOptions.current.onError(...)/onComplete(...)
  // directly to simulate the recorder finishing (or failing) a real
  // recording, the same way it would report it back for real.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  recorderOptions: { current: null as any },
  transcribeFallback: vi.fn(),
  enterRecordingAudioSession: vi.fn(),
  restorePlaybackAudioSession: vi.fn(),
}))

vi.mock('./useVoiceRecorder', () => ({
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  useVoiceRecorder: (opts: any) => {
    recorderOptions.current = opts
    return {
      isRecording: false,
      level: 0,
      startRecording,
      stopRecording: vi.fn(),
      prewarm,
      cancelPrewarm,
    }
  },
}))

vi.mock('./api', () => ({ transcribeFallback }))
vi.mock('./audioSession', () => ({ enterRecordingAudioSession, restorePlaybackAudioSession }))

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

  emitError(error: string) {
    this.onerror?.({ error })
  }
}

let lastInstance: FakeSpeechRecognition

beforeEach(() => {
  vi.useFakeTimers()
  startRecording.mockClear()
  prewarm.mockClear()
  cancelPrewarm.mockClear()
  transcribeFallback.mockReset()
  transcribeFallback.mockResolvedValue('')
  enterRecordingAudioSession.mockClear()
  restorePlaybackAudioSession.mockClear()
  recorderOptions.current = null
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
    act(() => vi.advanceTimersByTime(120000))

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

    act(() => vi.advanceTimersByTime(120000))
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

  it('primes the fallback recorder\'s mic stream synchronously at press-time, not when the watchdog fires', () => {
    // iOS Safari only honors getUserMedia() when it's initiated directly
    // inside a user gesture's call stack — see homeschool-tutor's mirror
    // test for the full rationale.
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    expect(prewarm).toHaveBeenCalledTimes(1)

    act(() => vi.advanceTimersByTime(4100))
    expect(startRecording).toHaveBeenCalledTimes(1)
    expect(prewarm).toHaveBeenCalledTimes(1)
  })

  it('does not fall back to recording in hold mode once native has proven it is alive, even across a long pause', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    expect(prewarm).toHaveBeenCalledTimes(1)
    act(() => vi.advanceTimersByTime(1000))
    act(() => lastInstance.emitInterim('hi'))
    expect(cancelPrewarm).toHaveBeenCalledTimes(1)

    act(() => vi.advanceTimersByTime(10000))
    expect(startRecording).not.toHaveBeenCalled()

    act(() => lastInstance.emitFinal('hi there'))
    act(() => result.current.release())
    expect(onFinal).toHaveBeenCalledWith('hi there')
  })

  it('does not send a second time when the native engine delivers a trailing final AFTER release (real duplicate-send repro)', () => {
    // Real reported bug, confirmed live via on-screen tracing: release()
    // sets holdModeRef.current = false and releasedRef.current = true
    // synchronously, then calls native.stop() — but stop() does not cut
    // off an in-flight SpeechRecognition instantly. Safari/Chrome can
    // still deliver one more (often longer/more complete) final onresult
    // a tick later. The live trace showed release() sending "And feeling"
    // (salvaged from the interim) immediately on release, then a trailing
    // native final "And feeling good" arriving ~40ms afterward with
    // holdModeRef.current already false — which used to fall through to
    // the unconditional tap-to-speak send path (no releasedRef check
    // there), sending the same turn again as a second chat bubble.
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    act(() => lastInstance.emitInterim('And feeling'))
    act(() => result.current.release())
    expect(onFinal).toHaveBeenCalledTimes(1)
    expect(onFinal).toHaveBeenCalledWith('And feeling')

    // The browser's own trailing final, arriving after release() already
    // ran — exactly what the live trace captured.
    act(() => lastInstance.emitFinal('And feeling good'))

    expect(onFinal).toHaveBeenCalledTimes(1)
  })
})

describe('useHybridVoiceInput mic errors (demo)', () => {
  // Mirror of homeschool-tutor/src/hooks/useHybridVoiceInput.test.ts's same
  // block — see that file's comment for the full rationale. Regression
  // coverage for a real gap: pressing the mic when the browser has blocked
  // microphone access used to do nothing at all — no error, no way out.

  it('surfaces a permission-denied error and returns to idle when native reports not-allowed, without a redundant fallback attempt', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    act(() => lastInstance.emitError('not-allowed'))

    expect(result.current.micError).toBe('permission-denied')
    expect(result.current.isListening).toBe(false)
    expect(startRecording).not.toHaveBeenCalled()
  })

  it('falls back to the recorder for service-not-allowed instead of assuming the mic itself is blocked', () => {
    // Real reported case: iOS in-app browsers (WhatsApp, Instagram, etc.)
    // return 'service-not-allowed' near-instantly with no permission
    // prompt ever shown, because the on-device Speech RECOGNITION SERVICE
    // isn't available to third-party WebViews — but plain getUserMedia
    // microphone capture (what the recorder fallback needs) is often still
    // fine in that same context.
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.start())
    act(() => lastInstance.emitError('service-not-allowed'))

    expect(startRecording).toHaveBeenCalledTimes(1)
    expect(result.current.micError).toBe(null)
  })

  it('still falls back to the recorder for a non-permission native error', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.start())
    act(() => lastInstance.emitError('network'))

    expect(startRecording).toHaveBeenCalledTimes(1)
    expect(result.current.micError).toBe(null)
  })

  it('surfaces the recorder fallback\'s own getUserMedia failure and returns to idle instead of hanging in "recording" mode', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (window as any).SpeechRecognition

    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    expect(result.current.isListening).toBe(true)

    act(() => recorderOptions.current.onError('unavailable'))

    expect(result.current.micError).toBe('unavailable')
    expect(result.current.isListening).toBe(false)
  })

  it('ignores a recorder error while native is still the active attempt (prewarm is speculative)', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    act(() => recorderOptions.current.onError('permission-denied'))

    expect(result.current.micError).toBe(null)
    expect(result.current.isListening).toBe(true)

    act(() => lastInstance.emitFinal('hello'))
    act(() => result.current.release())
    expect(onFinal).toHaveBeenCalledWith('hello')
    expect(result.current.micError).toBe(null)
  })

  it('clears a stale mic error on the next press', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    act(() => lastInstance.emitError('not-allowed'))
    expect(result.current.micError).toBe('permission-denied')

    act(() => result.current.startHold())
    expect(result.current.micError).toBe(null)
  })
})

describe('useHybridVoiceInput stuck-mode recovery (recorder fallback, demo)', () => {
  // Mirror of homeschool-tutor/src/hooks/useHybridVoiceInput.test.ts's same
  // block — see that file's comment for the full rationale. Regression
  // coverage for a real reported failure: a child interrupted Bede
  // mid-speech, native recognition produced nothing, the recorder fallback
  // kicked in, and the mic never recovered for the rest of the session.

  beforeEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (window as any).SpeechRecognition
  })

  it('returns to idle and surfaces an error when the transcription call rejects, instead of stranding mode at transcribing', async () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    expect(result.current.isListening).toBe(true)

    transcribeFallback.mockRejectedValueOnce(new Error('network error'))
    await act(async () => {
      await recorderOptions.current.onComplete(new Blob())
    })

    expect(result.current.isTranscribing).toBe(false)
    expect(result.current.isListening).toBe(false)
    expect(result.current.micError).toBe('unavailable')
    expect(onFinal).not.toHaveBeenCalled()
  })

  it('still delivers the transcript and clears any error when transcription succeeds', async () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    transcribeFallback.mockResolvedValueOnce('hello Bede')
    await act(async () => {
      await recorderOptions.current.onComplete(new Blob())
    })

    expect(onFinal).toHaveBeenCalledWith('hello Bede')
    expect(result.current.isTranscribing).toBe(false)
    expect(result.current.micError).toBe(null)
  })

  it('the recording safety timeout forces mode back to idle if the recorder never reports completion', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    expect(result.current.isListening).toBe(true)

    act(() => vi.advanceTimersByTime(10000))

    expect(result.current.isListening).toBe(false)
    expect(result.current.micError).toBe('unavailable')
  })

  it('does not fire the recording safety timeout once the recording completes in time', async () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    transcribeFallback.mockResolvedValueOnce('quick answer')
    await act(async () => {
      await recorderOptions.current.onComplete(new Blob())
    })
    expect(result.current.micError).toBe(null)

    act(() => vi.advanceTimersByTime(10000))
    expect(result.current.micError).toBe(null)
    expect(result.current.isListening).toBe(false)
  })

  it('cancelling with stop() disarms the recording safety timeout too', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    act(() => result.current.stop())
    expect(result.current.isListening).toBe(false)

    act(() => vi.advanceTimersByTime(10000))
    expect(result.current.micError).toBe(null)
  })

  // Regression coverage for a real reported bug, found via a live
  // debug-panel trace: the 10s recording safety timeout used to be the
  // ONLY thing that ever cleared, and it only cleared on onComplete — so a
  // child who held the mic and genuinely kept talking past 10 seconds got
  // cut off mid-answer, mode wiped back to idle and an "unavailable" error
  // shown, even though the recording was never actually stuck. onStarted
  // now clears the safety timeout as soon as recording is CONFIRMED
  // underway, not just once it completes.
  it('does not fire the recording safety timeout against a hold that is confirmed started and still in progress', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    act(() => recorderOptions.current.onStarted())

    // Well past the old 10s cap — the hold is still legitimately ongoing,
    // nothing has completed or errored.
    act(() => vi.advanceTimersByTime(15000))

    expect(result.current.isListening).toBe(true)
    expect(result.current.micError).toBe(null)
  })

  // Regression coverage for the other half of the same trace: a hold
  // released before MIN_RECORDING_MS while already in the fallback-recorder
  // path gets silently discarded inside useVoiceRecorder (onComplete never
  // fires for it) — onStopped is the only remaining signal, and used to be
  // absent entirely, leaving mode stuck at 'recording' until the 10s safety
  // timeout eventually bailed it out, silently swallowing every press in
  // between.
  it('returns to idle immediately when a too-short recording is discarded, without waiting for the safety timeout', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    expect(result.current.isListening).toBe(true)

    // Simulates useVoiceRecorder's own too-short-to-transcribe discard path:
    // onStopped fires, onComplete never does.
    act(() => recorderOptions.current.onStopped())

    expect(result.current.isListening).toBe(false)
    expect(result.current.micError).toBe(null)

    // A fresh press right after must actually start a new attempt, not be
    // silently swallowed by a mode still stuck at 'recording'.
    act(() => result.current.startHold())
    expect(result.current.isListening).toBe(true)
  })

  it('onStopped does not interfere with a completed recording already past the recording stage', async () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    transcribeFallback.mockResolvedValueOnce('a real answer')
    await act(async () => {
      await recorderOptions.current.onComplete(new Blob())
      // useVoiceRecorder always calls onStopped right after onComplete —
      // mode is already 'transcribing' by then, so this must be a no-op.
      recorderOptions.current.onStopped()
    })

    expect(onFinal).toHaveBeenCalledWith('a real answer')
    expect(result.current.isTranscribing).toBe(false)
    expect(result.current.micError).toBe(null)
  })
})

describe('useHybridVoiceInput audio session', () => {
  // Mirror of homeschool-tutor/src/hooks/useHybridVoiceInput.test.ts's own
  // "audio session" block — see that file for the full story. Regression
  // coverage for a real reported bug: on iOS Safari, using the press-to-talk
  // mic mid-session caused Bede's spoken replies to switch from whatever
  // output was selected (Bluetooth speaker, headphones) to the device's own
  // built-in "browser embedded" speaker, and never settle back. See
  // audioSession.ts.
  it('enters the recording audio session as soon as native listening starts', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))
    // Mounting idle already fires the "restore playback" branch once —
    // clear that before asserting on the transition this test cares about.
    restorePlaybackAudioSession.mockClear()

    act(() => result.current.start())

    expect(enterRecordingAudioSession).toHaveBeenCalled()
    expect(restorePlaybackAudioSession).not.toHaveBeenCalled()
  })

  it('restores the playback audio session once release() delivers the transcript', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    expect(enterRecordingAudioSession).toHaveBeenCalled()
    restorePlaybackAudioSession.mockClear()

    act(() => lastInstance.emitFinal('hello Bede'))
    act(() => result.current.release())

    expect(restorePlaybackAudioSession).toHaveBeenCalled()
  })

  it('restores the playback audio session when the recorder fallback finishes transcribing', async () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    restorePlaybackAudioSession.mockClear()

    transcribeFallback.mockResolvedValueOnce('hello Bede')
    await act(async () => {
      await recorderOptions.current.onComplete(new Blob())
    })

    expect(restorePlaybackAudioSession).toHaveBeenCalled()
  })

  it('restores the playback audio session when stop() cancels an in-progress hold', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    restorePlaybackAudioSession.mockClear()

    act(() => result.current.stop())

    expect(restorePlaybackAudioSession).toHaveBeenCalled()
  })

  it('enters the recording audio session before opening any getUserMedia stream (prewarm), not after', () => {
    // Regression test for a real reported bug: a real debug-panel trace
    // showed getUserMedia() rejecting with "AudioSession category is not
    // compatible with audio capture" right after Bede finished speaking —
    // the FIRST press-and-hold after Bede talks captured nothing at all.
    // Root cause: the audio-session switch used to only happen in the
    // mode-driven effect below, which runs after the render commits — a
    // beat AFTER prewarm()/native.start() had already called getUserMedia()
    // synchronously in the same call stack as _start() itself, while the
    // session was still pinned to 'playback'. Call order (not just "was it
    // called") is what actually distinguishes the fix: enterRecordingAudioSession
    // must happen before prewarm, not merely by the time this assertion runs.
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())

    expect(enterRecordingAudioSession).toHaveBeenCalled()
    expect(prewarm).toHaveBeenCalled()
    const audioSessionCallOrder = enterRecordingAudioSession.mock.invocationCallOrder[0]
    const prewarmCallOrder = prewarm.mock.invocationCallOrder[0]
    expect(audioSessionCallOrder).toBeLessThan(prewarmCallOrder)
  })
})

describe('useHybridVoiceInput no-speech-heard feedback', () => {
  // Mirror of homeschool-tutor/src/hooks/useHybridVoiceInput.test.ts's own
  // "no-speech-heard feedback" block — see that file for the full story.
  // Regression coverage for a real reported failure, confirmed via a
  // debug-panel trace: a child held the mic and answered for ~3.3-3.5s,
  // native recognition produced NO interim and NO final the entire time,
  // and the child released just under the old 4000ms stall watchdog — so
  // the whole answer was silently lost with nothing sent to Bede and no
  // sign anything went wrong. See NATIVE_STALL_TIMEOUT_MS/
  // MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK.
  it('surfaces no-speech-heard when a hold produces nothing and is released before the stall watchdog fires', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    act(() => vi.advanceTimersByTime(1800))
    act(() => result.current.release())

    expect(onFinal).not.toHaveBeenCalled()
    expect(result.current.micError).toBe('no-speech-heard')
  })

  it('falls back to the recorder instead once the stall watchdog fires mid-hold', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    act(() => vi.advanceTimersByTime(2600))

    expect(startRecording).toHaveBeenCalledTimes(1)
  })

  it('does not surface no-speech-heard for an accidental brief tap', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    act(() => vi.advanceTimersByTime(150))
    act(() => result.current.release())

    expect(onFinal).not.toHaveBeenCalled()
    expect(result.current.micError).toBe(null)
  })

  it('does not surface no-speech-heard when the hold actually captured something', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    act(() => lastInstance.emitInterim('the'))
    act(() => vi.advanceTimersByTime(3300))
    act(() => lastInstance.emitFinal('the quick brown fox'))
    act(() => result.current.release())

    expect(onFinal).toHaveBeenCalledWith('the quick brown fox')
    expect(result.current.micError).toBe(null)
  })
})
