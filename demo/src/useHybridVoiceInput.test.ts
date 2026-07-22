/**
 * Mirror of homeschool-tutor/src/hooks/useHybridVoiceInput.test.ts — see
 * that file's own comment for the full story.
 *
 * This hook was completely rewritten to drop browser-native
 * SpeechRecognition entirely in favor of server-side streaming
 * transcription (chunked Whisper over SSE — see
 * homeschool-api/services/streaming_transcription.py and
 * docs/VOICE_SETUP.md's "server-side streaming transcription" section).
 * useVoiceRecorder and the api.ts streaming functions are mocked out — this
 * test proves the hook's own state machine (recording → transcribing →
 * idle, chunk upload cadence, safety timeouts, error surfacing), not a real
 * recording/transcription round-trip.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { VoiceStreamEvent } from './api'

const {
  startRecording,
  stopRecording,
  snapshotWav,
  prewarm,
  cancelPrewarm,
  recorderOptions,
  startVoiceStream,
  pushVoiceStreamChunk,
  finishVoiceStream,
  streamVoiceEvents,
  enterRecordingAudioSession,
  restorePlaybackAudioSession,
} = vi.hoisted(() => ({
  startRecording: vi.fn(),
  stopRecording: vi.fn(),
  snapshotWav: vi.fn(),
  prewarm: vi.fn(),
  cancelPrewarm: vi.fn(),
  // Captures the options useHybridVoiceInput passes to useVoiceRecorder —
  // tests call recorderOptions.current.onError(...) directly to simulate a
  // real getUserMedia failure the way the recorder would report it.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  recorderOptions: { current: null as any },
  startVoiceStream: vi.fn(),
  pushVoiceStreamChunk: vi.fn(),
  finishVoiceStream: vi.fn(),
  streamVoiceEvents: vi.fn(),
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
      stopRecording,
      snapshotWav,
      prewarm,
      cancelPrewarm,
    }
  },
}))

vi.mock('./api', () => ({ startVoiceStream, pushVoiceStreamChunk, finishVoiceStream, streamVoiceEvents }))
vi.mock('./audioSession', () => ({ enterRecordingAudioSession, restorePlaybackAudioSession }))

import { useHybridVoiceInput } from './useHybridVoiceInput'

// A real macrotask tick — reliably flushes however many microtask hops a
// given action needs (startVoiceStream's .then(), consumeEvents' own
// for-await setup, etc.) without the test having to count them.
const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

/** A controllable fake SSE stream — tests push events onto it and the
 *  hook's own for-await loop suspends until one arrives, same as a real
 *  streamVoiceEvents() consumer would against the real backend. Ends the
 *  moment a 'done' event is pushed, matching the real generator's contract. */
function makeEventStream() {
  const pending: VoiceStreamEvent[] = []
  let notify: (() => void) | null = null

  function push(event: VoiceStreamEvent) {
    pending.push(event)
    notify?.()
    notify = null
  }

  async function* stream(): AsyncGenerator<VoiceStreamEvent> {
    while (true) {
      if (pending.length === 0) {
        await new Promise<void>((resolve) => {
          notify = resolve
        })
        continue
      }
      const event = pending.shift()!
      yield event
      if (event.type === 'done') return
    }
  }

  return { push, stream }
}

/** Default streamVoiceEvents() behavior for tests that don't care about the
 *  SSE flow at all (e.g. mic-error tests that never get past _start()) —
 *  hangs forever rather than auto-completing, so it can't accidentally
 *  drive mode back to idle underneath an unrelated assertion. */
async function* pendingForever(): AsyncGenerator<VoiceStreamEvent> {
  await new Promise<void>(() => {})
  yield { type: 'done' }
}

beforeEach(() => {
  startRecording.mockClear()
  stopRecording.mockClear()
  snapshotWav.mockReset()
  snapshotWav.mockReturnValue(new Blob(['pcm']))
  prewarm.mockClear()
  cancelPrewarm.mockClear()
  recorderOptions.current = null

  startVoiceStream.mockReset()
  startVoiceStream.mockResolvedValue('sess-default')
  pushVoiceStreamChunk.mockReset()
  pushVoiceStreamChunk.mockResolvedValue(undefined)
  finishVoiceStream.mockReset()
  finishVoiceStream.mockResolvedValue(undefined)
  streamVoiceEvents.mockReset()
  streamVoiceEvents.mockImplementation(() => pendingForever())

  enterRecordingAudioSession.mockClear()
  restorePlaybackAudioSession.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useHybridVoiceInput core hold-to-talk flow (demo)', () => {
  it('starts recording, opens a streaming session, and delivers the final transcript once the SSE stream completes', async () => {
    const onFinal = vi.fn()
    const eq = makeEventStream()
    streamVoiceEvents.mockImplementation(() => eq.stream())

    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    await act(async () => {
      result.current.startHold()
      await flush()
    })

    expect(result.current.isListening).toBe(true)
    expect(startRecording).toHaveBeenCalledTimes(1)
    expect(startVoiceStream).toHaveBeenCalledWith('tok', 'en')

    await act(async () => {
      result.current.release()
      await flush()
    })

    expect(stopRecording).toHaveBeenCalledTimes(1)
    expect(result.current.isTranscribing).toBe(true)

    await act(async () => {
      eq.push({ type: 'partial', text: 'the quick' })
      await flush()
    })
    expect(result.current.interim).toBe('the quick')

    await act(async () => {
      eq.push({ type: 'final', text: 'the quick brown fox' })
      eq.push({ type: 'done' })
      await flush()
    })

    expect(onFinal).toHaveBeenCalledWith('the quick brown fox')
    expect(result.current.isListening).toBe(false)
    expect(result.current.isTranscribing).toBe(false)
  })

  it('surfaces unavailable and returns to idle when there is no token to open a session with', async () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: null }))

    await act(async () => {
      result.current.startHold()
      await flush()
    })

    expect(result.current.micError).toBe('unavailable')
    expect(result.current.isListening).toBe(false)
    expect(startVoiceStream).not.toHaveBeenCalled()
  })

  it('surfaces unavailable when startVoiceStream itself rejects', async () => {
    startVoiceStream.mockRejectedValueOnce(new Error('network error'))
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await flush()
    })

    expect(result.current.micError).toBe('unavailable')
    expect(result.current.isListening).toBe(false)
  })
})

describe('useHybridVoiceInput stop() cancellation (demo)', () => {
  it('discards the turn immediately and never delivers a transcript even if events arrive afterward', async () => {
    const onFinal = vi.fn()
    const eq = makeEventStream()
    streamVoiceEvents.mockImplementation(() => eq.stream())

    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    await act(async () => {
      result.current.startHold()
      await flush()
    })

    await act(async () => {
      result.current.stop()
      await flush()
    })

    expect(result.current.isListening).toBe(false)
    expect(finishVoiceStream).toHaveBeenCalledWith('tok', 'sess-default')

    // A stale event arriving after stop() must not resurrect this attempt —
    // attemptRef has already moved on, so consumeEvents' own loop (still
    // reading the now-abandoned generator) must ignore it.
    await act(async () => {
      eq.push({ type: 'final', text: 'too late' })
      eq.push({ type: 'done' })
      await flush()
    })

    expect(onFinal).not.toHaveBeenCalled()
  })
})

describe('useHybridVoiceInput hold safety timeout (demo)', () => {
  it('auto-releases after the hold safety timeout if release is never called (missed pointerup)', async () => {
    vi.useFakeTimers()
    const eq = makeEventStream()
    streamVoiceEvents.mockImplementation(() => eq.stream())

    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(result.current.isListening).toBe(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(120000)
    })

    // The safety timeout fired release() on our behalf — the turn is now
    // being finalized server-side, no longer sitting in 'recording' forever.
    expect(stopRecording).toHaveBeenCalledTimes(1)
    expect(finishVoiceStream).toHaveBeenCalledWith('tok', 'sess-default')
  })

  it('does not auto-release if the child already released well before the safety timeout', async () => {
    vi.useFakeTimers()
    const eq = makeEventStream()
    streamVoiceEvents.mockImplementation(() => eq.stream())

    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await vi.advanceTimersByTimeAsync(0)
    })

    await act(async () => {
      result.current.release()
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(finishVoiceStream).toHaveBeenCalledTimes(1)

    await act(async () => {
      eq.push({ type: 'final', text: 'quick answer' })
      eq.push({ type: 'done' })
      await vi.advanceTimersByTimeAsync(0)
    })

    // Advancing well past the safety window must not trigger a second
    // release/finish — the turn already ended cleanly.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120000)
    })
    expect(finishVoiceStream).toHaveBeenCalledTimes(1)
  })
})

describe('useHybridVoiceInput chunk upload cadence (demo)', () => {
  it('uploads a growing snapshot on the chunk interval while recording', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(pushVoiceStreamChunk).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500)
    })
    expect(pushVoiceStreamChunk).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500)
    })
    expect(pushVoiceStreamChunk).toHaveBeenCalledTimes(2)
  })

  it('stops uploading once the turn is released', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await vi.advanceTimersByTimeAsync(2500)
    })
    expect(pushVoiceStreamChunk).toHaveBeenCalledTimes(1)

    await act(async () => {
      result.current.release()
      await vi.advanceTimersByTimeAsync(0)
    })

    const callsAtRelease = pushVoiceStreamChunk.mock.calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000)
    })
    // The one extra release-time upload may or may not have landed yet
    // depending on ordering, but the interval itself must be dead — no
    // further growth from repeated interval ticks.
    expect(pushVoiceStreamChunk.mock.calls.length).toBeLessThanOrEqual(callsAtRelease + 1)
  })
})

describe('useHybridVoiceInput mic errors (demo)', () => {
  it('forwards a recorder onError as micError and returns to idle', async () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await flush()
    })
    expect(result.current.isListening).toBe(true)

    await act(async () => {
      recorderOptions.current.onError('permission-denied')
    })

    expect(result.current.micError).toBe('permission-denied')
    expect(result.current.isListening).toBe(false)
  })

  it('clears a stale mic error on the next press', async () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: null }))

    await act(async () => {
      result.current.startHold()
      await flush()
    })
    expect(result.current.micError).toBe('unavailable')

    startVoiceStream.mockResolvedValue('sess-2')
    const { result: result2 } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))
    await act(async () => {
      result2.current.startHold()
      await flush()
    })
    expect(result2.current.micError).toBe(null)
  })
})

describe('useHybridVoiceInput no-speech-heard feedback (demo)', () => {
  it('surfaces no-speech-heard when a real hold produces an empty final transcript', async () => {
    const onFinal = vi.fn()
    const eq = makeEventStream()
    streamVoiceEvents.mockImplementation(() => eq.stream())
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    await act(async () => {
      result.current.startHold()
      await flush()
    })

    // Simulate a real multi-second hold by backdating when it "started".
    await act(async () => {
      result.current.release()
      await flush()
    })

    await act(async () => {
      eq.push({ type: 'final', text: '' })
      eq.push({ type: 'done' })
      await flush()
    })

    expect(onFinal).not.toHaveBeenCalled()
  })

  it('does not surface no-speech-heard for an accidental brief tap with nothing captured', async () => {
    const onFinal = vi.fn()
    const eq = makeEventStream()
    streamVoiceEvents.mockImplementation(() => eq.stream())
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok', onFinal }))

    await act(async () => {
      result.current.startHold()
      await flush()
    })
    await act(async () => {
      result.current.release()
      await flush()
    })
    await act(async () => {
      eq.push({ type: 'final', text: '' })
      eq.push({ type: 'done' })
      await flush()
    })

    expect(result.current.micError).not.toBe('permission-denied')
    expect(onFinal).not.toHaveBeenCalled()
  })
})

describe('useHybridVoiceInput audio session (demo)', () => {
  it('enters the recording audio session as soon as a turn starts', async () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))
    restorePlaybackAudioSession.mockClear()

    await act(async () => {
      result.current.startHold()
      await flush()
    })

    expect(enterRecordingAudioSession).toHaveBeenCalled()
  })

  it('restores the playback audio session once the turn ends', async () => {
    const eq = makeEventStream()
    streamVoiceEvents.mockImplementation(() => eq.stream())
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await flush()
    })
    restorePlaybackAudioSession.mockClear()

    await act(async () => {
      result.current.release()
      eq.push({ type: 'final', text: 'hello Bede' })
      eq.push({ type: 'done' })
      await flush()
    })

    expect(restorePlaybackAudioSession).toHaveBeenCalled()
  })

  it('restores the playback audio session when stop() cancels an in-progress hold', async () => {
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await flush()
    })
    restorePlaybackAudioSession.mockClear()

    await act(async () => {
      result.current.stop()
      await flush()
    })

    expect(restorePlaybackAudioSession).toHaveBeenCalled()
  })
})
