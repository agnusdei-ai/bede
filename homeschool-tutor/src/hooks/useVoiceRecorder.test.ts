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
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../utils/audioUtils', () => ({
  convertToWav: vi.fn(async () => new Blob(['fake-wav'], { type: 'audio/wav' })),
  getBestMimeType: () => 'audio/webm',
}))

import { useVoiceRecorder } from './useVoiceRecorder'

class FakeMediaRecorder {
  state: 'inactive' | 'recording' = 'inactive'
  stream: MediaStream
  ondataavailable: ((e: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null

  constructor(stream: MediaStream) {
    this.stream = stream
  }

  start() {
    this.state = 'recording'
    this.ondataavailable?.({ data: new Blob(['chunk']) })
  }

  stop() {
    this.state = 'inactive'
    this.onstop?.()
  }
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
  ;(window as any).MediaRecorder = FakeMediaRecorder as any
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(window as any).AudioContext = class {
    createMediaStreamSource() {
      return { connect: vi.fn() }
    }
    createAnalyser() {
      return {
        fftSize: 0,
        frequencyBinCount: 4,
        getByteFrequencyData: (arr: Uint8Array) => arr.fill(0),
      }
    }
  }
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
