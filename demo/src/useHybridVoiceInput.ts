// Mirror of homeschool-tutor/src/hooks/useHybridVoiceInput.ts for the demo app.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useVoiceRecorder } from './useVoiceRecorder'
import { finishVoiceStream, pushVoiceStreamChunk, startVoiceStream, streamVoiceEvents } from './api'
import { logDebug } from './debugBus'
import { enterRecordingAudioSession, restorePlaybackAudioSession } from './audioSession'

/**
 * Voice input for the chat mic button. Server-side streaming transcription
 * (chunked Whisper over SSE — see homeschool-api/services/streaming_transcription.py)
 * is now the ONLY path. Browser-native SpeechRecognition was removed
 * entirely: across this app's history it was the source of nearly every
 * voice-pipeline bug fought here — WebKit audio-session races, native
 * failing to even start within 10-30ms on some devices, an ever-more-
 * elaborate stall watchdog trying to paper over undocumented per-browser
 * behavior. The client always captures raw mic audio locally
 * (useVoiceRecorder.ts, the fallback path already proven reliable) and
 * periodically uploads the growing buffer to the backend; partial and final
 * transcripts arrive over an SSE stream. See docs/VOICE_SETUP.md's
 * "server-side streaming transcription" section for the full history of why.
 *
 * KNOWN GAP: native SpeechRecognition's own endpointing (detecting "the
 * child stopped talking" without an explicit release) had no equivalent
 * built here — that's real, unbuilt work (client-side silence/voice-
 * activity detection), not something this rewrite quietly solved. hold-to-
 * talk (startHold/release) is unaffected, since the child's own release()
 * already marks the end of a turn explicitly. start() (tap mode, used only
 * by homeschool-tutor's opt-in, off-by-default continuous "Voice on" mode)
 * now behaves like startHold() and needs an explicit release() the same
 * way — continuous mode's own call site never calls one, so a turn there
 * will run for the full HOLD_SAFETY_TIMEOUT_MS ceiling before auto-
 * finishing rather than ending snappily when the child stops talking. See
 * docs/VOICE_SETUP.md for the follow-up this needs.
 */

// How often, while a turn is open, to upload the growing audio buffer for a
// fresh transcription pass. Was 2500ms — raised after a real reported delay:
// every pass re-transcribes the WHOLE growing buffer (faster-whisper has no
// incremental mode), and the backend's per-session worker processes exactly
// one pass at a time, so a shorter interval means more total CPU-seconds
// spent on partial passes that get thrown away, competing with (and
// sometimes still running when) the one pass that actually matters — the
// final pass release() is waiting on. A longer interval cuts that wasted
// work without losing the "still listening" live-partial-text feedback
// entirely. See docs/VOICE_SETUP.md's transcription-delay section — a
// server-side per-pass timing log now exists there too, since this was a
// reasoned mitigation, not a confirmed full fix.
const CHUNK_UPLOAD_INTERVAL_MS = 4000
// Below this, an empty release() is almost certainly an accidental brief
// tap, not a real speech attempt gone unheard — no need to alarm the
// child/parent over a stray touch.
const MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK = 1200
// Bounds the worst case where a release event never reaches the button at
// all (a missed pointerup, a dropped touch event on some Android WebView) —
// applies to EVERY turn, not just an explicit hold (see the KNOWN GAP note
// above: without native's own endpointing, start()'s continuous-mode
// callers have no other way to end a turn at all). Matches
// useVoiceRecorder's own MAX_RECORDING_MS, the real ceiling for how long a
// single turn's audio graph stays open.
const HOLD_SAFETY_TIMEOUT_MS = 120000
const MAX_RECORDING_MS = 120000

interface Options {
  token: string | null
  onFinal?: (transcript: string) => void
  language?: string
}

type Mode = 'idle' | 'recording' | 'transcribing'
export type MicError = 'permission-denied' | 'unavailable' | 'no-speech-heard'

export function useHybridVoiceInput({ token, onFinal, language = 'en-US' }: Options) {
  const [mode, _setMode] = useState<Mode>('idle')
  const [interim, setInterim] = useState('')
  // Surfaces the one failure mode that used to be totally silent: a denied
  // or unavailable microphone left `mode` stuck with nothing telling the
  // visitor why the mic button just stopped doing anything. Callers show
  // this once, then call clearMicError.
  const [micError, setMicError] = useState<MicError | null>(null)
  const clearMicError = useCallback(() => setMicError(null), [])
  // Mirrored in a ref so callbacks fired from timers/async work see the
  // CURRENT mode, not a stale closure.
  const modeRef = useRef<Mode>('idle')
  const setMode = useCallback((m: Mode) => {
    modeRef.current = m
    _setMode(m)
  }, [])
  const holdStartedAtRef = useRef(0)
  const holdSafetyRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const chunkTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  // Bumped on every _start()/stop()/release() — lets in-flight async work
  // from a PREVIOUS turn (an SSE loop still reading, a chunk upload still in
  // flight) recognize it's stale and stop touching shared state, so a fast
  // press-release-press sequence can't let two attempts cross wires.
  const attemptRef = useRef(0)
  // Always points at the CURRENT release() so the hold-safety timer (armed
  // inside _start) can call it without a forward reference.
  const releaseRef = useRef<() => void>(() => {})

  // Pin WebKit's audio session category to match whether the mic is
  // actually capturing right now — see audioSession.ts for why. Reacts to
  // `mode` (not individual start/stop call sites) so every path that ends
  // listening is covered by one effect instead of needing a call threaded
  // into each of them individually.
  useEffect(() => {
    if (mode === 'recording') {
      enterRecordingAudioSession()
    } else {
      restorePlaybackAudioSession()
    }
  }, [mode])

  const clearHoldSafety = useCallback(() => {
    if (holdSafetyRef.current) clearTimeout(holdSafetyRef.current)
    holdSafetyRef.current = null
  }, [])

  const clearChunkTimer = useCallback(() => {
    if (chunkTimerRef.current) clearInterval(chunkTimerRef.current)
    chunkTimerRef.current = null
  }, [])

  const recorder = useVoiceRecorder({
    maxDurationMs: MAX_RECORDING_MS,
    onError: (reason) => {
      logDebug(`recorder onError reason=${reason}`)
      clearHoldSafety()
      clearChunkTimer()
      attemptRef.current += 1
      setMode('idle')
      setMicError(reason)
    },
  })

  // Uploads whatever's been captured so far, if anything and if this
  // attempt is still the current one — called on the chunk-upload interval
  // and once more, immediately, right at release() so the FINAL chunk
  // reflects audio up to the actual release moment rather than however
  // stale the last interval tick was.
  const uploadSnapshot = useCallback(async (attempt: number) => {
    const sessionId = sessionIdRef.current
    if (!token || !sessionId || attemptRef.current !== attempt) return
    const wavBlob = recorder.snapshotWav()
    if (!wavBlob) return
    try {
      await pushVoiceStreamChunk(token, sessionId, wavBlob)
    } catch (err) {
      // A single dropped chunk isn't fatal — the NEXT upload (interval tick
      // or the release-time final push) carries everything captured so far
      // anyway, since uploads are never deltas. Only a hard failure to ever
      // get a session started, or the final push failing too, surfaces to
      // the child (handled at those call sites).
      logDebug(`pushVoiceStreamChunk failed: ${err instanceof Error ? err.message : String(err)}`)
    }
  }, [token, recorder])

  // Consumes the SSE event stream for one turn's session — the ONE place
  // responsible for the whole post-processing once a turn ends: updates
  // `interim` on each partial, and once the stream itself closes (its own
  // 'final' then 'done', or an error), delivers onFinal and returns mode to
  // idle. release() below only has to trigger the upload+finish sequence
  // that makes the server produce those events; it doesn't duplicate any of
  // this handling itself.
  const consumeEvents = useCallback(async (sessionId: string, attempt: number) => {
    if (!token) return
    let finalText = ''
    try {
      for await (const event of streamVoiceEvents(token, sessionId)) {
        if (attemptRef.current !== attempt) return
        if (event.type === 'partial') {
          setInterim(event.text)
        } else if (event.type === 'final') {
          finalText = event.text
          setInterim(event.text)
        } else if (event.type === 'error') {
          logDebug(`voice stream event error: ${event.message}`)
        }
      }
    } catch (err) {
      logDebug(`voice event stream failed: ${err instanceof Error ? err.message : String(err)}`)
    }
    if (attemptRef.current !== attempt) return
    clearHoldSafety()
    const text = finalText.trim()
    const heldMs = Date.now() - holdStartedAtRef.current
    setMode('idle')
    if (text) {
      onFinal?.(text)
    } else if (heldMs >= MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK) {
      // A real, multi-second turn produced literally nothing. Confirmed via
      // a real debug-panel trace in the native-SpeechRecognition era: this
      // used to just silently send nothing, leaving the child's whole
      // answer lost with no sign anything went wrong.
      logDebug(`voice stream produced nothing after a ${heldMs}ms turn — surfacing to the user`)
      setMicError('no-speech-heard')
    }
  }, [token, onFinal, clearHoldSafety, setMode])

  // Shared entry point for both start() and startHold() — functionally
  // identical now (see the KNOWN GAP note above for why start()'s own
  // continuous-mode caller doesn't behave quite like it used to).
  const _start = useCallback(() => {
    if (modeRef.current !== 'idle') return
    const attempt = ++attemptRef.current
    logDebug(`_start() attempt=${attempt}`)
    holdStartedAtRef.current = Date.now()
    sessionIdRef.current = null
    setInterim('')
    // A fresh press means a fresh attempt — don't let a previous failure's
    // banner linger once the child tries again.
    setMicError(null)

    // Switch the AudioSession category to recording-capable SYNCHRONOUSLY,
    // right here, before anything touches the mic — not via the mode-driven
    // effect above, which only runs after this render commits, a beat too
    // late for iOS Safari's own getUserMedia timing. See audioSession.ts and
    // docs/VOICE_SETUP.md's audio-session-race troubleshooting sections.
    enterRecordingAudioSession()
    setMode('recording')
    recorder.startRecording()

    holdSafetyRef.current = setTimeout(() => {
      holdSafetyRef.current = null
      releaseRef.current()
    }, HOLD_SAFETY_TIMEOUT_MS)

    if (!token) {
      logDebug('_start: no token, cannot open a streaming session')
      clearHoldSafety()
      setMode('idle')
      setMicError('unavailable')
      return
    }

    startVoiceStream(token, language.slice(0, 2))
      .then((sessionId) => {
        if (attemptRef.current !== attempt) return // turn already ended
        sessionIdRef.current = sessionId
        consumeEvents(sessionId, attempt)
        chunkTimerRef.current = setInterval(() => uploadSnapshot(attempt), CHUNK_UPLOAD_INTERVAL_MS)
      })
      .catch((err) => {
        logDebug(`startVoiceStream failed: ${err instanceof Error ? err.message : String(err)}`)
        if (attemptRef.current !== attempt) return
        // No streaming session, and no native fallback anymore — this turn
        // genuinely can't be transcribed at all.
        clearHoldSafety()
        setMode('idle')
        setMicError('unavailable')
      })
  }, [token, language, recorder, consumeEvents, uploadSnapshot, clearHoldSafety, setMode])

  const start = useCallback(() => _start(), [_start])
  const startHold = useCallback(() => _start(), [_start])

  const stop = useCallback(() => {
    logDebug(`stop() (cancel) from mode=${modeRef.current}`)
    attemptRef.current += 1 // invalidates any in-flight chunk upload / SSE consumer
    clearHoldSafety()
    clearChunkTimer()
    if (modeRef.current === 'recording') recorder.stopRecording()
    const sessionId = sessionIdRef.current
    sessionIdRef.current = null
    if (token && sessionId) finishVoiceStream(token, sessionId).catch(() => {})
    setInterim('')
    setMode('idle')
  }, [token, recorder, clearHoldSafety, clearChunkTimer, setMode])

  // The child let go of the button (or, for continuous mode, some other
  // caller decided the turn is over). Pushes one final chunk reflecting
  // everything up to this exact moment, then signals finish — the SSE
  // consumer already running (started back in _start) sees the resulting
  // 'final'+'done' events and handles onFinal delivery + returning to idle
  // itself (see consumeEvents above). Unlike stop() (which cancels and
  // discards), release() delivers the transcript.
  const release = useCallback(() => {
    logDebug(`release() from mode=${modeRef.current}`)
    if (modeRef.current !== 'recording') return
    const attempt = attemptRef.current
    const sessionId = sessionIdRef.current
    clearChunkTimer()
    recorder.stopRecording()
    setMode('transcribing')

    if (!token || !sessionId) {
      // Never got a session at all — no SSE consumer running to bring this
      // back to idle on its own.
      clearHoldSafety()
      setMode('idle')
      return
    }
    ;(async () => {
      await uploadSnapshot(attempt)
      try {
        await finishVoiceStream(token, sessionId)
      } catch (err) {
        logDebug(`finishVoiceStream failed: ${err instanceof Error ? err.message : String(err)}`)
        // consumeEvents' own stream-read will also fail/end without a
        // 'final' in this case and already returns mode to idle itself —
        // no separate handling needed here.
      }
    })()
  }, [token, recorder, clearChunkTimer, clearHoldSafety, uploadSnapshot, setMode])
  releaseRef.current = release

  return {
    isListening: mode === 'recording',
    isTranscribing: mode === 'transcribing',
    interim,
    micError,
    clearMicError,
    isSupported: !!navigator.mediaDevices?.getUserMedia && !!(window.AudioContext || (window as unknown as { webkitAudioContext?: unknown }).webkitAudioContext),
    start,
    startHold,
    release,
    stop,
  }
}
