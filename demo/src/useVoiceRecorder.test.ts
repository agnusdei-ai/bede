/**
 * Regression coverage for a real risk surfaced during walkie-talkie manual
 * testing: an accidental micro-tap (a misfired press-release, a stray touch)
 * that starts and stops the recorder almost instantly was still being sent
 * to Whisper for transcription. Whisper is documented to hallucinate
 * plausible-looking text on silence/near-silence rather than returning
 * empty — that hallucinated text then slips right past the "only send
 * non-empty transcripts" guard upstream (useHybridVoiceInput's release()),
 * producing what looks like a phantom reply to a question nobody asked.
 * MIN_RECORDING_MS (see useVoiceRecorder.ts) discards recordings that short
 * before they ever reach transcription.
 *
 * Also covers the raw-PCM capture path itself (ScriptProcessorNode →
 * Float32Array chunks → WAV) added to replace the old MediaRecorder →
 * decodeAudioData round trip, which iOS Safari could silently fail to
 * complete for its own MediaRecorder output.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useVoiceRecorder } from './useVoiceRecorder'

class FakeGainNode {
  gain = { value: 1 }
  connect = vi.fn()
  disconnect = vi.fn()
}

class FakeScriptProcessorNode {
  onaudioprocess: ((e: { inputBuffer: { getChannelData: (ch: number) => Float32Array } }) => void) | null = null
  connect = vi.fn()
  disconnect = vi.fn()
}

class FakeAnalyserNode {
  fftSize = 0
  frequencyBinCount = 4
  getByteFrequencyData(arr: Uint8Array) {
    arr.fill(0)
  }
}

class FakeAudioContext {
  sampleRate = 44100
  destination = {}
  createMediaStreamSource() {
    return { connect: vi.fn() }
  }
  createAnalyser() {
    return new FakeAnalyserNode()
  }
  createScriptProcessor() {
    return new FakeScriptProcessorNode()
  }
  createGain() {
    return new FakeGainNode()
  }
  close = vi.fn(async () => {})
}

beforeEach(() => {
  vi.useFakeTimers()

  const fakeTrack = { stop: vi.fn() }
  const fakeStream = { getTracks: () => [fakeTrack] } as unknown as MediaStream

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(navigator as any).mediaDevices = {
    getUserMedia: vi.fn(async () => fakeStream),
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).AudioContext = FakeAudioContext as any
  // requestAnimationFrame/cancelAnimationFrame aren't polyfilled in jsdom by default.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).requestAnimationFrame = vi.fn(() => 1)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).cancelAnimationFrame = vi.fn()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useVoiceRecorder minimum-duration guard', () => {
  it('skips transcription for a recording shorter than the minimum duration', async () => {
    const onComplete = vi.fn()
    const { result } = renderHook(() => useVoiceRecorder({ onComplete }))

    await act(async () => {
      await result.current.startRecording()
    })
    // An accidental micro-tap: started and stopped almost instantly.
    act(() => vi.advanceTimersByTime(50))
    await act(async () => {
      await result.current.stopRecording()
    })

    expect(onComplete).not.toHaveBeenCalled()
  })

  it('still transcribes a recording at or above the minimum duration', async () => {
    const onComplete = vi.fn()
    const { result } = renderHook(() => useVoiceRecorder({ onComplete }))

    await act(async () => {
      await result.current.startRecording()
    })
    act(() => vi.advanceTimersByTime(500))
    await act(async () => {
      await result.current.stopRecording()
    })

    expect(onComplete).toHaveBeenCalledTimes(1)
    const wavBlob = onComplete.mock.calls[0][0] as Blob
    expect(wavBlob.type).toBe('audio/wav')
  })
})

describe('useVoiceRecorder raw PCM capture', () => {
  it('captures audio directly off the live graph (no MediaRecorder/decodeAudioData round trip) and encodes it into the WAV passed to onComplete', async () => {
    const onComplete = vi.fn()
    const { result } = renderHook(() => useVoiceRecorder({ onComplete }))

    let processor: FakeScriptProcessorNode | undefined
    const originalCreate = FakeAudioContext.prototype.createScriptProcessor
    FakeAudioContext.prototype.createScriptProcessor = function (this: FakeAudioContext) {
      processor = new FakeScriptProcessorNode()
      return processor
    }

    await act(async () => {
      await result.current.startRecording()
    })

    // Simulate two buffers of captured audio arriving while recording.
    const fakeChannelData = new Float32Array(4096).fill(0.5)
    act(() => {
      processor?.onaudioprocess?.({ inputBuffer: { getChannelData: () => fakeChannelData } })
      processor?.onaudioprocess?.({ inputBuffer: { getChannelData: () => fakeChannelData } })
    })

    act(() => vi.advanceTimersByTime(500))
    await act(async () => {
      await result.current.stopRecording()
    })

    expect(onComplete).toHaveBeenCalledTimes(1)
    const wavBlob = onComplete.mock.calls[0][0] as Blob
    // 44-byte WAV header + 2 buffers of 4096 samples * 2 bytes/sample
    // (resampled from 44100 → 16000, so smaller than the raw capture, but
    // still comfortably larger than an empty/header-only WAV).
    expect(wavBlob.size).toBeGreaterThan(44)

    FakeAudioContext.prototype.createScriptProcessor = originalCreate
  })
})

describe('useVoiceRecorder re-entrant stopRecording (iOS Safari duplicate release)', () => {
  it('does not double-process the same recording when stopRecording is called again before the first call\'s audioCtx.close() resolves', async () => {
    // Regression test for a real bug: release() in useHybridVoiceInput can
    // fire twice for one press on iOS Safari while mode is still
    // 'recording' (nothing there moves mode away from 'recording' until
    // THIS hook's own onComplete callback runs). stopRecording() used to
    // leave processorRef/audioCtxRef/streamRef populated across its
    // `await audioCtx.close()` call, so a second overlapping call would
    // read those same non-null refs, pass the null-guard, and re-encode +
    // re-send the exact same captured audio a second time — the child's
    // one spoken turn showing up twice, back to back, with identical text.
    const onComplete = vi.fn()
    const { result } = renderHook(() => useVoiceRecorder({ onComplete }))

    await act(async () => {
      await result.current.startRecording()
    })
    act(() => vi.advanceTimersByTime(500))

    // Fire the calls back to back, without awaiting the first one before
    // starting the second — this is what reproduces the race: the first
    // call's synchronous prefix (through the ref-nulling) runs to
    // completion before the second call starts, but the first call's
    // `await audioCtx.close()` hasn't resolved yet when it does.
    await act(async () => {
      const first = result.current.stopRecording()
      const second = result.current.stopRecording()
      await Promise.all([first, second])
    })

    expect(onComplete).toHaveBeenCalledTimes(1)
  })
})

describe('useVoiceRecorder mic prewarming (iOS Safari user-gesture requirement)', () => {
  it('reuses the stream opened by prewarm() instead of calling getUserMedia() again in startRecording', async () => {
    const { result } = renderHook(() => useVoiceRecorder({}))

    act(() => {
      result.current.prewarm()
    })
    // The prewarm getUserMedia() call is async even though it's *initiated*
    // synchronously — flush it before startRecording tries to consume it.
    await act(async () => {})
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1)

    await act(async () => {
      await result.current.startRecording()
    })

    // startRecording must NOT have requested a second stream — a second,
    // later getUserMedia() call is exactly the case that's unreliable on
    // iOS Safari once the original user gesture has passed.
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1)
  })

  it('stops the prewarmed stream\'s tracks when cancelPrewarm is called before it is ever used', async () => {
    const { result } = renderHook(() => useVoiceRecorder({}))

    act(() => {
      result.current.prewarm()
    })
    await act(async () => {})

    const fakeStream = await (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mock.results[0].value
    act(() => {
      result.current.cancelPrewarm()
    })
    await act(async () => {})

    expect(fakeStream.getTracks()[0].stop).toHaveBeenCalledTimes(1)
  })

  it('still works when startRecording is called with no prior prewarm (falls back to a fresh request)', async () => {
    const onComplete = vi.fn()
    const { result } = renderHook(() => useVoiceRecorder({ onComplete }))

    await act(async () => {
      await result.current.startRecording()
    })
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1)

    act(() => vi.advanceTimersByTime(500))
    await act(async () => {
      await result.current.stopRecording()
    })
    expect(onComplete).toHaveBeenCalledTimes(1)
  })
})

describe('useVoiceRecorder getUserMedia failure reporting', () => {
  // Mirror of homeschool-tutor/src/hooks/useVoiceRecorder.test.ts's same
  // block — see that file's comment for the full rationale. Regression
  // coverage for a real gap: getUserMedia() rejecting used to be swallowed
  // into a bare console.error with no way for a caller to know.

  it('classifies NotAllowedError as permission-denied', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(navigator as any).mediaDevices.getUserMedia = vi.fn(async () => {
      throw new DOMException('Permission denied', 'NotAllowedError')
    })
    const onError = vi.fn()
    const { result } = renderHook(() => useVoiceRecorder({ onError }))

    await act(async () => {
      await result.current.startRecording()
    })

    expect(onError).toHaveBeenCalledWith('permission-denied')
  })

  it('classifies the legacy PermissionDeniedError name as permission-denied too', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(navigator as any).mediaDevices.getUserMedia = vi.fn(async () => {
      throw new DOMException('Permission denied', 'PermissionDeniedError')
    })
    const onError = vi.fn()
    const { result } = renderHook(() => useVoiceRecorder({ onError }))

    await act(async () => {
      await result.current.startRecording()
    })

    expect(onError).toHaveBeenCalledWith('permission-denied')
  })

  it('classifies any other getUserMedia failure as unavailable', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(navigator as any).mediaDevices.getUserMedia = vi.fn(async () => {
      throw new DOMException('No microphone found', 'NotFoundError')
    })
    const onError = vi.fn()
    const { result } = renderHook(() => useVoiceRecorder({ onError }))

    await act(async () => {
      await result.current.startRecording()
    })

    expect(onError).toHaveBeenCalledWith('unavailable')
  })

  it('does not start recording (isRecording stays false) after a getUserMedia failure', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(navigator as any).mediaDevices.getUserMedia = vi.fn(async () => {
      throw new DOMException('Permission denied', 'NotAllowedError')
    })
    const { result } = renderHook(() => useVoiceRecorder({}))

    await act(async () => {
      await result.current.startRecording()
    })

    expect(result.current.isRecording).toBe(false)
  })
})

describe('useVoiceRecorder retries fresh getUserMedia when a prewarmed stream failed', () => {
  // Regression test for a real reported bug: prewarm() opens its
  // getUserMedia() stream in parallel with native Web Speech Recognition's
  // own internal mic capture at the start of a hold. On some devices those
  // two contend and prewarm's call rejects (e.g. NotReadableError) — a
  // transient race, not a real "no mic" situation. By the time the fallback
  // actually needs the mic (seconds later, after native has stalled out and
  // released its own grab), that contention has typically cleared. But
  // startRecording() used to reuse the stale, already-failed prewarm promise
  // (a settled promise is truthy, so `??` never fell through to a fresh
  // call) and give up outright — turning a one-off race into a hard,
  // silent failure for the whole press, with no retry ever attempted.
  it('retries getUserMedia() fresh and succeeds once the contention has cleared', async () => {
    const fakeTrack = { stop: vi.fn() }
    const fakeStream = { getTracks: () => [fakeTrack] } as unknown as MediaStream
    const getUserMedia = vi
      .fn()
      .mockRejectedValueOnce(new DOMException('Device in use', 'NotReadableError'))
      .mockResolvedValueOnce(fakeStream)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(navigator as any).mediaDevices.getUserMedia = getUserMedia

    const onComplete = vi.fn()
    const onError = vi.fn()
    const { result } = renderHook(() => useVoiceRecorder({ onComplete, onError }))

    act(() => {
      result.current.prewarm()
    })
    // Flush the failed prewarm attempt before the fallback ever asks for it.
    await act(async () => {})
    expect(onError).toHaveBeenCalledWith('unavailable')

    await act(async () => {
      await result.current.startRecording()
    })

    expect(getUserMedia).toHaveBeenCalledTimes(2)
    expect(result.current.isRecording).toBe(true)

    act(() => vi.advanceTimersByTime(500))
    await act(async () => {
      await result.current.stopRecording()
    })
    expect(onComplete).toHaveBeenCalledTimes(1)
  })

  it('still reports unavailable if the retry also fails', async () => {
    const getUserMedia = vi.fn(async () => {
      throw new DOMException('Device in use', 'NotReadableError')
    })
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(navigator as any).mediaDevices.getUserMedia = getUserMedia

    const onError = vi.fn()
    const { result } = renderHook(() => useVoiceRecorder({ onError }))

    act(() => {
      result.current.prewarm()
    })
    await act(async () => {})

    await act(async () => {
      await result.current.startRecording()
    })

    expect(getUserMedia).toHaveBeenCalledTimes(2)
    expect(onError).toHaveBeenCalledTimes(2)
    expect(onError).toHaveBeenLastCalledWith('unavailable')
    expect(result.current.isRecording).toBe(false)
  })
})
