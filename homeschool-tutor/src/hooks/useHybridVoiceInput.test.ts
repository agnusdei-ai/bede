/**
 * Mirror of demo/src/useHybridVoiceInput.test.ts — see that file's own
 * comment for the full story.
 *
 * This hook was completely rewritten to drop browser-native
 * SpeechRecognition entirely in favor of server-side streaming
 * transcription (chunked Whisper over SSE — see
 * homeschool-api/services/streaming_transcription.py and
 * docs/VOICE_SETUP.md's "server-side streaming transcription" section).
 * useVoiceRecorder and the services/voiceApi.ts streaming functions are
 * mocked out — this test proves the hook's own state machine (recording →
 * transcribing → idle, chunk upload cadence, safety timeouts, error
 * surfacing), not a real recording/transcription round-trip.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { VoiceStreamEvent } from '../services/voiceApi'

const {
  startRecording,
  stopRecording,
  snapshotWav,
  snapshotPcmDelta,
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
  snapshotPcmDelta: vi.fn(),
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
      snapshotPcmDelta,
      prewarm,
      cancelPrewarm,
    }
  },
}))

vi.mock('../services/voiceApi', () => ({ startVoiceStream, pushVoiceStreamChunk, finishVoiceStream, streamVoiceEvents }))
vi.mock('../utils/audioSession', () => ({ enterRecordingAudioSession, restorePlaybackAudioSession }))

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
  snapshotPcmDelta.mockReset()
  snapshotPcmDelta.mockReturnValue(new Blob(['pcm']))
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

describe('useHybridVoiceInput core hold-to-talk flow', () => {
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

  it('retries once after a transient startVoiceStream failure and still succeeds', async () => {
    // Real-world report: a "Load failed" network-layer error (not a server
    // rejection — the request never got a response) kept happening
    // mid-session, and with no retry at all every single hold gave up
    // immediately. One quick retry covers the common transient case.
    vi.useFakeTimers()
    startVoiceStream.mockRejectedValueOnce(new Error('Load failed'))
    startVoiceStream.mockResolvedValueOnce('sess-retry')
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    try {
      await act(async () => {
        result.current.startHold()
        await vi.advanceTimersByTimeAsync(0)
      })
      // First attempt has failed but the retry hasn't fired yet — no error
      // surfaced to the user for what should resolve itself shortly.
      expect(result.current.micError).toBe(null)
      expect(startVoiceStream).toHaveBeenCalledTimes(1)

      await act(async () => {
        await vi.advanceTimersByTimeAsync(500)
      })

      expect(startVoiceStream).toHaveBeenCalledTimes(2)
      expect(result.current.micError).toBe(null)
      expect(result.current.isListening).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('surfaces unavailable only after every retry attempt is exhausted', async () => {
    vi.useFakeTimers()
    startVoiceStream.mockRejectedValue(new Error('Load failed'))
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    try {
      await act(async () => {
        result.current.startHold()
        await vi.advanceTimersByTimeAsync(0)
        await vi.advanceTimersByTimeAsync(500)
      })

      expect(startVoiceStream).toHaveBeenCalledTimes(2)
      expect(result.current.micError).toBe('unavailable')
      expect(result.current.isListening).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('useHybridVoiceInput stop() cancellation', () => {
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

describe('useHybridVoiceInput hold safety timeout', () => {
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

describe('useHybridVoiceInput chunk upload cadence', () => {
  it('uploads a growing snapshot on the chunk interval while recording', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(pushVoiceStreamChunk).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })
    expect(pushVoiceStreamChunk).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })
    expect(pushVoiceStreamChunk).toHaveBeenCalledTimes(2)
  })

  it('uploads only the DELTA on each tick, never the whole buffer again', async () => {
    // The old protocol re-sent everything captured so far on every tick,
    // which is O(N^2) upload over a hold: 8.3MB for a 40-second answer, 63MB
    // at the 120s safety cap. Each tick must now read the delta snapshot,
    // never the whole-buffer one.
    vi.useFakeTimers()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await vi.advanceTimersByTimeAsync(0)
    })
    snapshotWav.mockClear()
    snapshotPcmDelta.mockClear()

    await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
    await act(async () => { await vi.advanceTimersByTimeAsync(4000) })

    expect(snapshotPcmDelta).toHaveBeenCalledTimes(2)
    expect(snapshotWav).not.toHaveBeenCalled()
  })

  it('re-sends a delta that failed to upload, so a dropped chunk costs no words', async () => {
    // The whole-buffer protocol got this for free: any dropped chunk was
    // covered by the next one. Deltas do not, so a failed chunk is held and
    // prepended to the following upload.
    vi.useFakeTimers()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await vi.advanceTimersByTimeAsync(0)
    })
    pushVoiceStreamChunk.mockClear()
    pushVoiceStreamChunk.mockRejectedValueOnce(new Error('network went away'))

    await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
    expect(pushVoiceStreamChunk).toHaveBeenCalledTimes(1)

    // Second tick carries the failed delta plus the fresh one, so the bytes
    // sent are larger than a single delta on its own.
    await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
    expect(pushVoiceStreamChunk).toHaveBeenCalledTimes(2)
    const retried = pushVoiceStreamChunk.mock.calls[1][2] as Blob
    const single = pushVoiceStreamChunk.mock.calls[0][2] as Blob
    expect(retried.size).toBeGreaterThan(single.size)
  })

  it('does not carry a previous turn\'s failed chunk into the next turn', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await vi.advanceTimersByTimeAsync(0)
    })
    pushVoiceStreamChunk.mockRejectedValueOnce(new Error('nope'))
    await act(async () => { await vi.advanceTimersByTimeAsync(4000) })

    await act(async () => { result.current.stop() })
    pushVoiceStreamChunk.mockClear()

    await act(async () => {
      result.current.startHold()
      await vi.advanceTimersByTimeAsync(0)
    })
    await act(async () => { await vi.advanceTimersByTimeAsync(4000) })

    const first = pushVoiceStreamChunk.mock.calls[0][2] as Blob
    expect(first.size).toBe(new Blob(['pcm']).size)
  })

  it('logs how much audio was actually captured at release, for diagnosing an empty transcript', async () => {
    // A real production trace showed a 2.3s hold come back with NO text at
    // all. Whether that is a genuinely quiet child or a capture-side race
    // (e.g. the mic not yet live after a barge-in interrupt) is exactly
    // what this log line is for — see docs/VOICE_SETUP.md's "produced
    // nothing with the session already open" section.
    const { getDebugEntries, clearDebugEntries } = await import('./debugBus')
    clearDebugEntries()
    snapshotPcmDelta.mockReturnValue(new Blob([new Uint8Array(3200)])) // ~100ms at 16kHz 16-bit mono

    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))
    await act(async () => { result.current.startHold() })
    await act(async () => { result.current.release() })

    const messages = getDebugEntries().map((e) => e.message)
    expect(messages.some((m) => /release\(\) captured ~100ms of audio this delta \(3200 bytes\)/.test(m))).toBe(true)
  })

  it('stops uploading once the turn is released', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await vi.advanceTimersByTimeAsync(4000)
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

  it('uploads a final chunk on release even for a hold shorter than the chunk interval', async () => {
    vi.useFakeTimers()
    // Simulates the real useVoiceRecorder's behavior: stopRecording()
    // synchronously clears the state snapshotWav() depends on, before its
    // own internal await resolves. A real regression had release() call
    // snapshotWav() AFTER stopRecording(), which then always saw it already
    // cleared and silently uploaded nothing for any hold shorter than
    // CHUNK_UPLOAD_INTERVAL_MS (so the periodic tick never got a chance to
    // fire even once) — every such turn transcribed as literally nothing.
    let hasAudio = true
    stopRecording.mockImplementation(async () => {
      hasAudio = false
    })
    snapshotPcmDelta.mockImplementation(() => (hasAudio ? new Blob(['pcm']) : null))

    const { result } = renderHook(() => useHybridVoiceInput({ token: 'tok' }))

    await act(async () => {
      result.current.startHold()
      await vi.advanceTimersByTimeAsync(500) // well under CHUNK_UPLOAD_INTERVAL_MS
    })
    expect(pushVoiceStreamChunk).not.toHaveBeenCalled()

    await act(async () => {
      result.current.release()
      await vi.advanceTimersByTimeAsync(0)
    })

    expect(pushVoiceStreamChunk).toHaveBeenCalledTimes(1)
    expect(pushVoiceStreamChunk.mock.calls[0][2]).toBeInstanceOf(Blob)
  })
})

describe('useHybridVoiceInput mic errors', () => {
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

describe('useHybridVoiceInput no-speech-heard feedback', () => {
  it('does not deliver an onFinal call when a hold produces an empty final transcript', async () => {
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

    expect(onFinal).not.toHaveBeenCalled()
  })
})

describe('useHybridVoiceInput audio session', () => {
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

// ── Release before the session opens ────────────────────────────────────────
//
// Regression tests for the race a real debug capture caught on cellular: a
// short hold (~1s) reaches release() before startVoiceStream's promise has
// resolved, so sessionIdRef is still null. release() used to discard the
// whole turn silently — no upload, no finish, no error — and the
// late-resolving .then() then armed an SSE consumer and a chunk timer for a
// turn that had already ended, which sat until the stream died and reported
// "voice stream produced nothing".
describe('release() arriving before the streaming session opens', () => {
  /** startVoiceStream that the test resolves by hand, to model a slow network. */
  function deferredSession() {
    let resolveIt: (id: string) => void = () => {}
    const promise = new Promise<string>((r) => { resolveIt = r })
    startVoiceStream.mockReturnValue(promise)
    return { open: (id = 'sess-late') => resolveIt(id) }
  }

  it('uploads the captured audio once the session finally opens', async () => {
    const session = deferredSession()
    const events = makeEventStream()
    streamVoiceEvents.mockImplementation(() => events.stream())
    const blob = new Blob(['the-childs-answer'])
    snapshotPcmDelta.mockReturnValue(blob)

    const { result } = renderHook(() => useHybridVoiceInput({ token: 't' }))

    await act(async () => { result.current.startHold() })
    // Child lets go while the session request is still in flight.
    await act(async () => { result.current.release() })

    // Nothing lost, nothing sent yet.
    expect(finishVoiceStream).not.toHaveBeenCalled()

    await act(async () => { session.open('sess-late'); await flush() })

    // The turn completes against the session that just opened.
    expect(pushVoiceStreamChunk).toHaveBeenCalled()
    expect(finishVoiceStream).toHaveBeenCalledWith('t', 'sess-late')
  })

  it('delivers the transcript for a turn released before the session opened', async () => {
    const session = deferredSession()
    const events = makeEventStream()
    streamVoiceEvents.mockImplementation(() => events.stream())
    const onFinal = vi.fn()

    const { result } = renderHook(() => useHybridVoiceInput({ token: 't', onFinal }))

    await act(async () => { result.current.startHold() })
    await act(async () => { result.current.release() })
    await act(async () => { session.open(); await flush() })

    await act(async () => {
      events.push({ type: 'final', text: 'Joseph forgave his brothers' })
      events.push({ type: 'done' })
      await flush()
    })

    expect(onFinal).toHaveBeenCalledWith('Joseph forgave his brothers')
  })

  it('does NOT start the periodic chunk timer for an already-released turn', async () => {
    // The compounding half of the bug: a 4s interval uploading from a
    // recorder that has already stopped.
    vi.useFakeTimers()
    try {
      const session = deferredSession()
      streamVoiceEvents.mockImplementation(() => pendingForever())

      const { result } = renderHook(() => useHybridVoiceInput({ token: 't' }))
      await act(async () => { result.current.startHold() })
      await act(async () => { result.current.release() })
      await act(async () => { session.open(); await vi.advanceTimersByTimeAsync(0) })

      const callsAfterRelease = pushVoiceStreamChunk.mock.calls.length
      await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })

      expect(pushVoiceStreamChunk.mock.calls.length).toBe(callsAfterRelease)
    } finally {
      vi.useRealTimers()
    }
  })

  it('stop() cancels a deferred release instead of sending it later', async () => {
    const session = deferredSession()
    streamVoiceEvents.mockImplementation(() => pendingForever())

    const { result } = renderHook(() => useHybridVoiceInput({ token: 't' }))
    await act(async () => { result.current.startHold() })
    await act(async () => { result.current.release() })
    await act(async () => { result.current.stop() })
    await act(async () => { session.open(); await flush() })

    expect(finishVoiceStream).not.toHaveBeenCalledWith('t', 'sess-late')
  })

  it('surfaces an error when the session never opens at all', async () => {
    vi.useFakeTimers()
    try {
      startVoiceStream.mockRejectedValue(new Error('offline'))
      streamVoiceEvents.mockImplementation(() => pendingForever())

      const { result } = renderHook(() => useHybridVoiceInput({ token: 't' }))
      await act(async () => { result.current.startHold() })
      await act(async () => { result.current.release() })
      // Long enough to exhaust startVoiceStream's own retry schedule.
      await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })

      // Must not sit in 'transcribing' forever waiting on a session that
      // will never exist.
      expect(result.current.isTranscribing).toBe(false)
      expect(result.current.micError).toBeTruthy()
    } finally {
      vi.useRealTimers()
    }
  })

  it('normal-speed holds are unaffected — the chunk timer still arms', async () => {
    // Guards against "fixing" the race by simply never arming the timer.
    vi.useFakeTimers()
    try {
      startVoiceStream.mockResolvedValue('sess-fast')
      streamVoiceEvents.mockImplementation(() => pendingForever())

      const { result } = renderHook(() => useHybridVoiceInput({ token: 't' }))
      await act(async () => { result.current.startHold(); await vi.advanceTimersByTimeAsync(0) })

      const before = pushVoiceStreamChunk.mock.calls.length
      await act(async () => { await vi.advanceTimersByTimeAsync(9_000) })

      expect(pushVoiceStreamChunk.mock.calls.length).toBeGreaterThan(before)
    } finally {
      vi.useRealTimers()
    }
  })
})
