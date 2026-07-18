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
