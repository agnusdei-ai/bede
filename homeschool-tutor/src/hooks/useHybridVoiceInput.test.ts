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

vi.mock('../services/voiceApi', () => ({ transcribeFallback }))
vi.mock('../utils/audioSession', () => ({ enterRecordingAudioSession, restorePlaybackAudioSession }))

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
// Counts how many native recognition sessions were ever constructed — the
// walkie-talkie invariant is that exactly ONE is created per explicit user
// press, and nothing (no timer, no effect) ever spins up another on its own.
let constructCount = 0

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

  it('falls back to recording if native produces zero signal for the whole hold-start window (Safari silent-hold bug)', () => {
    // Real reported failure: on iOS Safari, holding the mic showed
    // "Listening..." the whole time, but releasing after several seconds
    // of real speech sent nothing at all and no transcript ever appeared.
    // Root cause: unlike tap-to-speak, hold mode armed NO watchdog at all
    // at start, so if native never fires a single onresult for the ENTIRE
    // hold (a documented Safari failure mode), release() has nothing to
    // salvage. release() also can't rely on onEndWithoutResult firing
    // afterward, since it marks stoppedByUserRef before stopping native
    // specifically to suppress that signal. This test presses, lets the
    // hold-start window elapse with zero interim/final ever emitted (the
    // silent-Safari case), and expects the recorder fallback to have
    // started WHILE still held, so release() still has real audio to send.
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    expect(startRecording).not.toHaveBeenCalled()

    // Native never produces a single onresult the whole time — the exact
    // Safari silent-stall failure mode.
    act(() => vi.advanceTimersByTime(4100))

    expect(startRecording).toHaveBeenCalledTimes(1)
    expect(result.current.isListening).toBe(true)
  })

  it('primes the fallback recorder\'s mic stream synchronously at press-time, not when the watchdog fires', () => {
    // iOS Safari only honors getUserMedia() when it's initiated directly
    // inside a user gesture's call stack. If the recorder only requested
    // its stream once the hold-start watchdog actually fired (4s later,
    // from a setTimeout callback), that request would run well outside
    // any gesture and Safari can silently block it — even though the
    // fallback "started", it would never actually capture audio. prewarm()
    // must fire in the same synchronous tick as startHold() so the stream
    // request is made at the right moment regardless of whether native
    // ends up needing the fallback at all.
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    expect(prewarm).toHaveBeenCalledTimes(1)

    act(() => vi.advanceTimersByTime(4100))
    expect(startRecording).toHaveBeenCalledTimes(1)
    // No SECOND getUserMedia request should happen when the watchdog
    // fires — the fallback must reuse the stream prewarm() already opened.
    expect(prewarm).toHaveBeenCalledTimes(1)
  })

  it('does not fall back to recording in hold mode once native has proven it is alive, even across a long pause', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    expect(prewarm).toHaveBeenCalledTimes(1)
    // Native responds well within the hold-start window — proof of life.
    act(() => vi.advanceTimersByTime(1000))
    act(() => lastInstance.emitInterim('hi'))
    // The prewarmed stream is no longer needed once native has proven it's
    // alive — release it rather than holding the mic open for nothing.
    expect(cancelPrewarm).toHaveBeenCalledTimes(1)

    // A long natural pause afterward, well past the hold-start window,
    // must NOT be mistaken for the silent-Safari case now that native has
    // already proven it's working.
    act(() => vi.advanceTimersByTime(10000))
    expect(startRecording).not.toHaveBeenCalled()

    act(() => lastInstance.emitFinal('hi there'))
    act(() => result.current.release())
    expect(onFinal).toHaveBeenCalledWith('hi there')
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

    // Letting the old safety timer's window elapse afterward must not fire
    // a second, stale release.
    act(() => vi.advanceTimersByTime(120000))
    expect(onFinal).toHaveBeenCalledTimes(1)
  })

  it('does not send a second time when the native engine delivers a trailing final AFTER release (real duplicate-send repro)', () => {
    // Mirror of the demo app's same-named test — see that file's comment.
    // Real reported bug, confirmed live via on-screen tracing on the demo
    // app (same hook): release() sets holdModeRef.current = false and
    // releasedRef.current = true synchronously, then calls native.stop()
    // — but stop() does not cut off an in-flight SpeechRecognition
    // instantly. Safari/Chrome can still deliver one more (often
    // longer/more complete) final onresult a tick later, with
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
    // ran.
    act(() => lastInstance.emitFinal('And feeling good'))

    expect(onFinal).toHaveBeenCalledTimes(1)
  })
})

describe('useHybridVoiceInput mic errors', () => {
  // Regression coverage for a real gap: pressing the mic when the browser
  // has blocked microphone access used to do nothing at all — no error, no
  // way out, `mode` just stuck (see useVoiceRecorder.ts's startRecording,
  // whose `if (!stream) return` had no way to tell this hook anything went
  // wrong). These tests prove the hook now surfaces a `micError` and always
  // returns to idle instead of hanging.

  it('surfaces a permission-denied error and returns to idle when native reports not-allowed, without a redundant fallback attempt', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    act(() => lastInstance.emitError('not-allowed'))

    expect(result.current.micError).toBe('permission-denied')
    expect(result.current.isListening).toBe(false)
    // Falling back would just hit the same blocked permission again — the
    // hook should report the failure directly instead of wasting a round trip.
    expect(startRecording).not.toHaveBeenCalled()
  })

  it('falls back to the recorder for service-not-allowed instead of assuming the mic itself is blocked', () => {
    // Real reported case: iOS in-app browsers (WhatsApp, Instagram, etc.)
    // return 'service-not-allowed' near-instantly with no permission
    // prompt ever shown, because the on-device Speech RECOGNITION SERVICE
    // isn't available to third-party WebViews — but plain getUserMedia
    // microphone capture (what the recorder fallback needs) is often still
    // fine in that same context. Treating this the same as 'not-allowed'
    // (a real prior bug) told a family their mic was blocked without ever
    // giving the working fallback a chance.
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

    // Unrelated to permissions — the existing fallback behavior must be unchanged.
    expect(startRecording).toHaveBeenCalledTimes(1)
    expect(result.current.micError).toBe(null)
  })

  it('surfaces the recorder fallback\'s own getUserMedia failure and returns to idle instead of hanging in "recording" mode', () => {
    // Native unsupported at all (e.g. Firefox) — goes straight to the
    // recorder fallback, which is where a real permission/hardware failure
    // would otherwise leave `mode` stuck forever with isListening still true.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (window as any).SpeechRecognition

    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    expect(result.current.isListening).toBe(true)

    // Simulates useVoiceRecorder.ts's getStream() catch calling back with
    // 'unavailable' (e.g. NotFoundError — no microphone hardware).
    act(() => recorderOptions.current.onError('unavailable'))

    expect(result.current.micError).toBe('unavailable')
    expect(result.current.isListening).toBe(false)
  })

  it('ignores a recorder error while native is still the active attempt (prewarm is speculative)', () => {
    // recorder.prewarm() fires speculatively alongside every native attempt,
    // before it's known whether the fallback will even be needed (see
    // useHybridVoiceInput.ts's _start). A prewarm failure must not kill a
    // native session that's still live and might succeed on its own.
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    act(() => recorderOptions.current.onError('permission-denied'))

    expect(result.current.micError).toBe(null)
    expect(result.current.isListening).toBe(true)

    // Native goes on to work fine despite the prewarm's speculative failure.
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

    // A fresh press (permission granted this time, or the child just tries
    // again) must not carry the old error forward.
    act(() => result.current.startHold())
    expect(result.current.micError).toBe(null)
  })
})

describe('useHybridVoiceInput stuck-mode recovery (recorder fallback)', () => {
  // Regression coverage for a real reported failure: a child interrupted
  // Bede mid-speech, native recognition produced nothing at all (see the
  // stall-watchdog tests above), the recorder fallback kicked in, and the
  // mic never recovered for the rest of the session — later presses
  // silently did nothing. Root cause: the recorder's onComplete had no
  // try/catch around the transcription network call, so a thrown/rejected
  // call skipped straight past the setMode('idle') that was supposed to
  // run after it, permanently stranding `mode` at 'transcribing' (which
  // disables the mic button via isTranscribing, with no event ever left to
  // clear it). native is unsupported for every test in this block so
  // _start() goes straight to the recorder fallback.

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

    // Simulates useVoiceRecorder.ts's stopRecording() silently no-op'ing
    // (its own `if (!processor || !audioCtx || !stream) return` guard) —
    // onComplete is never invoked, so nothing would otherwise ever move
    // mode off 'recording' again.
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

    // Letting the safety window elapse afterward must not retroactively
    // set a stray error once the turn already completed successfully.
    act(() => vi.advanceTimersByTime(10000))
    expect(result.current.micError).toBe(null)
    expect(result.current.isListening).toBe(false)
  })

  it('cancelling with stop() disarms the recording safety timeout too', () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    act(() => result.current.startHold())
    act(() => result.current.stop())
    expect(result.current.isListening).toBe(false)

    // stop() already forced idle; the safety timer firing later on top of
    // that must not spuriously set micError for a turn the child cancelled.
    act(() => vi.advanceTimersByTime(10000))
    expect(result.current.micError).toBe(null)
  })
})

describe('useHybridVoiceInput audio session', () => {
  // Regression coverage for a real reported bug: on iOS Safari, using the
  // press-to-talk mic mid-lesson caused Bede's spoken replies to switch
  // from whatever output the family had selected (Bluetooth speaker,
  // headphones) to the device's own built-in "browser embedded" speaker,
  // and it never settled back — every subsequent mic press re-triggered the
  // same switch. Root cause: opening a getUserMedia mic stream flips
  // WebKit's audio session category; nothing ever told it to switch back.
  // See utils/audioSession.ts.
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
})

describe('useHybridVoiceInput no-speech-heard feedback', () => {
  // Regression coverage for a real reported failure, confirmed via a
  // debug-panel trace: a child held the mic and answered for ~3.3-3.5s,
  // native recognition produced NO interim and NO final the entire time
  // (the documented "Safari can accept the mic press and never fire one
  // single onresult" failure mode), and the child released just under the
  // old 4000ms stall watchdog — so the whole answer was silently lost with
  // nothing sent to Bede and no sign anything went wrong. See
  // NATIVE_STALL_TIMEOUT_MS/MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK.
  it('surfaces no-speech-heard when a hold produces nothing and is released before the stall watchdog fires', () => {
    const onFinal = vi.fn()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    act(() => result.current.startHold())
    // No interim, no final. Released between MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK
    // (1200ms) and NATIVE_STALL_TIMEOUT_MS (2500ms) — long enough to be a
    // real speech attempt, but before the watchdog itself would have
    // switched over to the recorder fallback.
    act(() => vi.advanceTimersByTime(1800))
    act(() => result.current.release())

    expect(onFinal).not.toHaveBeenCalled()
    expect(result.current.micError).toBe('no-speech-heard')
  })

  it('falls back to the recorder instead once the stall watchdog fires mid-hold', () => {
    // The real trace this regression covers (~3.3-3.5s of nothing) now
    // hits the (lowered) stall watchdog WHILE STILL HELD rather than
    // reaching release() with nothing at all — the watchdog switching to
    // the Whisper fallback partway through is the better outcome, and
    // no-speech-heard becomes the narrower safety net for holds released
    // just before that point (see the test above).
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
    // An early interim is proof native is alive — permanently disarms the
    // stall watchdog for this hold (see the interim effect), same as a
    // real long answer with natural pauses.
    act(() => lastInstance.emitInterim('the'))
    act(() => vi.advanceTimersByTime(3300))
    act(() => lastInstance.emitFinal('the quick brown fox'))
    act(() => result.current.release())

    expect(onFinal).toHaveBeenCalledWith('the quick brown fox')
    expect(result.current.micError).toBe(null)
  })
})
