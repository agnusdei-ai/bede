// Mirror of homeschool-tutor/src/hooks/useHybridVoiceInput.ts for the demo app.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useVoiceRecorder } from './useVoiceRecorder'
import { finishVoiceStream, pushVoiceStreamChunk, startVoiceStream, streamVoiceEvents, transcribeAudio } from './api'
import { logDebug } from './debugBus'
import { enterRecordingAudioSession, restorePlaybackAudioSession } from './audioSession'
import { isNetworkFailure } from './networkFailure'
import {
  SAMPLE_INTERVAL_MS, advanceEndpointState, endReason, initialEndpointState,
} from './endpointing'

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
 * by this demo's own opt-in, off-by-default continuous "Voice on" mode —
 * see App.tsx's auto-start effect and useVoiceModePreference.ts) now
 * behaves like startHold() and needs an explicit release() the same way —
 * continuous mode's own call site never calls one, so a turn there used to
 * run for the full HOLD_SAFETY_TIMEOUT_MS ceiling (120s) before auto-
 * finishing rather than ending when the child stopped talking.
 *
 * That follow-up is now BUILT here too, and it had to be: the demo is what
 * a family judges the product by, so shipping it with voice behaviour
 * worse than the product's own is the wrong way round. Pass
 * `endpointOnSilence` — continuous mode does — and the turn ends on
 * trailing silence instead. endpointing.ts holds the decision logic and
 * the reasoning behind a silence window deliberately longer than a
 * dictation app's: narration pauses are the work, not hesitation to be
 * trimmed. hold-to-talk still does NOT pass it, because there the child's
 * own release IS the endpoint and second-guessing a held button would cut
 * them off mid-hold. The 120s ceiling remains underneath as the backstop
 * it always was. See docs/VOICE_SETUP.md.
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
// end before useVoiceRecorder's own MAX_RECORDING_MS so its auto-stop cannot
// clear the last PCM delta before release() snapshots it. This still bounds a
// single turn's audio graph stays open.
const HOLD_SAFETY_TIMEOUT_MS = 119500
const MAX_RECORDING_MS = 120000
// A "Load failed"/"Failed to fetch" error from startVoiceStream is a raw
// network-layer failure (the request never got a response at all — a
// dropped connection, a momentary Wi-Fi blip), not a server-side rejection.
// Real-world reports showed this happening repeatedly, mid-session, with no
// retry at all: every single hold immediately gave up and surfaced
// "unavailable," making voice input feel unusable on anything less than a
// rock-solid connection. One quick retry before giving up is the same
// reasoning services/voice_synthesis.py's OpenAI TTS call already applies
// on the backend side for the identical class of failure.
const START_STREAM_MAX_ATTEMPTS = 2
const START_STREAM_RETRY_DELAY_MS = 500
// Never throw away a spoken answer. The streaming path is four requests per
// turn (start, chunks, finish, events), and on a phone over cellular any one
// of them can drop. Every one of those failures used to end the turn and
// discard the recording, although the recorder still held all of it. Now a
// failed streaming step after the child has spoken sends the WHOLE answer,
// as one WAV, to the stateless POST /voice/transcribe, and delivers the
// result through the same onFinal as a normal turn. Only if that also fails
// is the connection message shown.
//
// If the stream dies while the child is still talking, the microphone stays
// open: they finish their answer, and their release (or the endpoint, or
// the hold ceiling) sends all of it. A transport failure on the upload gets
// exactly one more try; anything else (a refusal, the request deadline) is
// final, because repeating it asks to be refused twice.
const FALLBACK_MAX_ATTEMPTS = 2
const FALLBACK_RETRY_DELAY_MS = 1000

interface Options {
  token: string | null
  onFinal?: (transcript: string) => void
  language?: string
  /**
   * End the turn on trailing silence instead of waiting for an explicit
   * release(). Opt-in, and only continuous "Voice on" mode passes it —
   * hold-to-talk must never endpoint itself, because there the child's own
   * finger already says when they are done and second-guessing that would
   * cut them off mid-hold.
   *
   * This is the KNOWN GAP in this file's header comment, now closed for the
   * one caller that had no other way to end a turn. See utils/endpointing.ts
   * for why the silence window is deliberately longer than a dictation app's.
   */
  endpointOnSilence?: boolean
  /**
   * Fired when an endpointed turn ended because NOBODY SPOKE — distinct from
   * every other way a turn can fail, and deliberately not routed through
   * `micError`.
   *
   * In continuous mode silence is ordinary: the child is thinking, or has
   * stepped away. Reporting it as "I didn't quite catch that" tells a child
   * the microphone failed when nothing failed, and (via SocraticChat's
   * circuit breaker) three of those in a row drop them out of Voice on mode.
   * At the old 120s ceiling that took six minutes to happen; at the 12s
   * no-speech timeout it would take thirty-six seconds, so shortening the
   * timeout without this would have made an existing annoyance ten times
   * more frequent.
   */
  onSilentTimeout?: () => void
}

type Mode = 'idle' | 'recording' | 'transcribing'
// 'network' is deliberately separate from 'unavailable': the microphone
// itself is fine, the request to open a transcription session never reached
// the server. See isNetworkFailure above.
export type MicError = 'permission-denied' | 'unavailable' | 'no-speech-heard' | 'network'

export function useHybridVoiceInput({ token, onFinal, language = 'en-US', endpointOnSilence = false, onSilentTimeout }: Options) {
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
  // Set at release() (or the hold-safety timeout that calls the same
  // function) — lets the success/failure log below report processing
  // time separately from the full hold. heldMs already existed and mixes
  // "how long the child spoke" with "how long the server took after they
  // let go"; a slow turn needs those told apart to diagnose.
  const releasedAtRef = useRef(0)
  const holdSafetyRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const chunkTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const sessionIdRef = useRef<string | null>(null)
  // Bumped on start, cancel, and completion — lets in-flight async work
  // from a PREVIOUS turn (an SSE loop still reading, a chunk upload still in
  // flight) recognize it's stale and stop touching shared state, so a fast
  // press-release-press sequence can't let two attempts cross wires.
  const attemptRef = useRef(0)
  // Always points at the CURRENT release() so the hold-safety timer (armed
  // inside _start) can call it without a forward reference.
  const releaseRef = useRef<() => void>(() => {})
  // Same forward-reference pattern, for the endpointing effect's silent path.
  const stopRef = useRef<() => void>(() => {})
  const controllerRef = useRef<AbortController | null>(null)
  const uploadTailRef = useRef<Promise<void>>(Promise.resolve())
  // A recorder auto-stop can clear its PCM buffer after earlier deltas reached
  // the server. Preserve that evidence so release still sends /finish.
  const uploadedAudioRef = useRef(false)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const finishTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const recorderStopRef = useRef<Promise<unknown> | null>(null)
  const recorderStartRef = useRef<Promise<unknown> | null>(null)
  const recorderStartOwnerRef = useRef(0)
  // The attempt whose streaming session was lost while the child was still
  // recording. release() sees it and sends the whole answer in one piece.
  const streamLostAttemptRef = useRef(0)
  // The whole recording of a released turn, kept until the turn finishes so
  // a streaming failure AFTER release can still transcribe it.
  const releasedAudioRef = useRef<{ attempt: number; audio: Promise<Blob | null> } | null>(null)

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

  // A release() that arrived BEFORE the server session finished opening.
  //
  // _start() begins recording synchronously but opens the streaming session
  // over the network, so sessionIdRef is only set in that promise's .then().
  // A short hold on a slow connection therefore reaches release() with no
  // session yet — and release() used to just drop the turn on the floor:
  // audio discarded, nothing uploaded, no error shown. Confirmed from a real
  // debug capture: a 1041ms hold on cellular, ending in "voice stream
  // produced nothing" and an "I didn't quite catch that" bubble.
  //
  // It compounded, too. release() doesn't bump attemptRef (only stop()
  // does), so the late-resolving .then() still passed its staleness check
  // and installed an SSE consumer plus a 4s chunk-upload interval for a turn
  // that had already ended with a stopped recorder — and since nothing ever
  // called finishVoiceStream, that consumer sat waiting until the stream
  // died on its own.
  //
  // Holding the release here instead lets _start()'s .then() complete it the
  // moment the session exists: the audio was already captured, so nothing is
  // lost by finishing a beat late.
  const pendingReleaseRef = useRef<{ attempt: number; blob: Blob | null } | null>(null)

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
      if (recorderStartOwnerRef.current !== attemptRef.current) return
      logDebug(`recorder onError reason=${reason}`)
      stopRef.current()
      setMicError(reason)
    },
  })
  // Resolves to the whole recording (or null), for the fallback below.
  const stopRecorder = useCallback((): Promise<Blob | null> => {
    recorderStartRef.current = null
    const previousStop = recorderStopRef.current
    const currentStop = Promise.resolve(recorder.stopRecording())
      .then((blob) => (blob instanceof Blob ? blob : null))
      .catch(() => null)
    const stopped = Promise.all([previousStop, currentStop])
    recorderStopRef.current = stopped
    void stopped.finally(() => {
      if (recorderStopRef.current === stopped) recorderStopRef.current = null
    })
    return currentStop
  }, [recorder.stopRecording])

  // Uploads whatever's been captured so far, if anything and if this
  // attempt is still the current one — called on the chunk-upload interval
  // and once more, immediately, right at release() so the FINAL chunk
  // reflects audio up to the actual release moment rather than however
  // stale the last interval tick was.
  // Sends the whole recording of `attempt` to the one-shot endpoint and ends
  // the turn with what comes back. See FALLBACK_MAX_ATTEMPTS above.
  const transcribeWholeAnswer = useCallback(async (attempt: number, audio: Promise<Blob | null>) => {
    setMode('transcribing')
    const blob = await audio
    if (attemptRef.current !== attempt) return
    const signal = controllerRef.current?.signal
    let text: string | null = null
    if (blob && token) {
      logDebug(`voice stream lost — sending the whole answer in one piece (${blob.size} bytes, ~${Math.round(blob.size / 32)}ms)`)
      for (let tries = 1; tries <= FALLBACK_MAX_ATTEMPTS; tries++) {
        try {
          text = await transcribeAudio(token, blob, language.slice(0, 2), signal)
          break
        } catch (err) {
          if (attemptRef.current !== attempt) return
          logDebug(`one-shot transcription failed: ${err instanceof Error ? err.message : String(err)} (try ${tries}/${FALLBACK_MAX_ATTEMPTS})`)
          if (tries >= FALLBACK_MAX_ATTEMPTS || !isNetworkFailure(err)) break
          await new Promise((resolve) => setTimeout(resolve, FALLBACK_RETRY_DELAY_MS))
          if (attemptRef.current !== attempt) return
        }
      }
    } else {
      logDebug('voice stream lost and there is no recording to fall back on')
    }
    if (attemptRef.current !== attempt) return
    attemptRef.current += 1
    controllerRef.current?.abort()
    controllerRef.current = null
    streamLostAttemptRef.current = 0
    releasedAudioRef.current = null
    clearHoldSafety()
    setMode('idle')
    if (text === null) {
      setMicError('network')
      return
    }
    const trimmed = text.trim()
    const heldMs = Date.now() - holdStartedAtRef.current
    if (trimmed) {
      logDebug(`one-shot transcription delivered "${trimmed.slice(0, 40)}${trimmed.length > 40 ? '…' : ''}"`)
      onFinal?.(trimmed)
    } else if (heldMs >= MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK) {
      setMicError('no-speech-heard')
    }
  }, [token, language, onFinal, setMode, clearHoldSafety])

  const canFallBack = useCallback((): boolean => {
    if (!token) return false
    return true
  }, [token])

  // A streaming step failed for `attempt`. With `fallback` (every transport
  // failure), the answer is kept and sent in one piece instead; without it
  // (the post-release processing deadline, where the server is evidently
  // alive and busy, so the same audio again would only queue behind it),
  // the turn ends with the connection message as before.
  const failTurn = useCallback((attempt: number, fallback = true) => {
    if (attemptRef.current !== attempt) return
    if (!fallback || !canFallBack()) {
      stopRef.current()
      setMicError('network')
      return
    }
    const wasRecording = modeRef.current === 'recording'
    // Retire the streaming half of this turn: every upload, finish and
    // events reader still in flight for it is now stale and stops itself.
    const next = ++attemptRef.current
    if (recorderStartOwnerRef.current === attempt) recorderStartOwnerRef.current = next
    controllerRef.current?.abort()
    controllerRef.current = new AbortController()
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    if (finishTimerRef.current) clearTimeout(finishTimerRef.current)
    retryTimerRef.current = null
    finishTimerRef.current = null
    clearChunkTimer()
    pendingReleaseRef.current = null
    sessionIdRef.current = null
    uploadTailRef.current = Promise.resolve()
    setInterim('')
    if (wasRecording) {
      // Keep listening. release() sends the whole answer once they finish.
      logDebug('voice stream lost while still recording — keeping the microphone open for the whole answer')
      streamLostAttemptRef.current = next
      return
    }
    const released = releasedAudioRef.current
    const audio = released && released.attempt === attempt ? released.audio : Promise.resolve(null)
    void transcribeWholeAnswer(next, audio)
  }, [canFallBack, clearChunkTimer, transcribeWholeAnswer])

  const uploadSnapshot = useCallback(async (attempt: number, preCapturedBlob?: Blob | null) => {
    const sessionId = sessionIdRef.current
    if (!token || !sessionId || attemptRef.current !== attempt) return
    // release() below passes its own pre-captured blob, taken BEFORE
    // recorder.stopRecording() clears the refs snapshotWav() reads — see
    // that call site for why calling snapshotWav() fresh here would be too
    // late for a release-time upload.
    const fresh = preCapturedBlob !== undefined ? preCapturedBlob : recorder.snapshotPcmDelta()
    if (!fresh) return uploadTailRef.current
    const signal = controllerRef.current?.signal
    // Capture now, send in order. A failed delta may already have been appended;
    // resending without an acknowledgment protocol would duplicate audio.
    const upload = uploadTailRef.current.then(async () => {
      if (attemptRef.current !== attempt || signal?.aborted) return
      await pushVoiceStreamChunk(token, sessionId, fresh, signal)
      if (attemptRef.current === attempt) uploadedAudioRef.current = true
    })
    uploadTailRef.current = upload.catch((err) => {
      logDebug(`pushVoiceStreamChunk failed: ${err instanceof Error ? err.message : String(err)}`)
      failTurn(attempt)
    })
    return uploadTailRef.current
  }, [token, recorder, failTurn])

  // Consumes the SSE event stream for one turn's session — the ONE place
  // responsible for the whole post-processing once a turn ends: updates
  // `interim` on each partial, and once the stream itself closes (its own
  // 'final' then 'done', or an error), delivers onFinal and returns mode to
  // idle. release() below only has to trigger the upload+finish sequence
  // that makes the server produce those events; it doesn't duplicate any of
  // this handling itself.
  const consumeEvents = useCallback(async (sessionId: string, attempt: number, signal: AbortSignal) => {
    if (!token) return
    let finalText = ''
    let sawFinal = false
    let sawDone = false
    let streamErrored = false
    try {
      for await (const event of streamVoiceEvents(token, sessionId, signal)) {
        if (attemptRef.current !== attempt) return
        if (event.type === 'partial') {
          setInterim(event.text)
        } else if (event.type === 'final') {
          sawFinal = true
          finalText = event.text
          setInterim(event.text)
        } else if (event.type === 'error') {
          streamErrored = true
          logDebug(`voice stream event error: ${event.message}`)
          failTurn(attempt)
          return
        } else if (event.type === 'done') {
          sawDone = true
        }
      }
    } catch (err) {
      streamErrored = true
      logDebug(`voice event stream failed: ${err instanceof Error ? err.message : String(err)}`)
    }
    if (attemptRef.current !== attempt) return
    if (streamErrored || !sawFinal || !sawDone) {
      failTurn(attempt)
      return
    }
    clearHoldSafety()
    if (finishTimerRef.current) clearTimeout(finishTimerRef.current)
    finishTimerRef.current = null
    const text = finalText.trim()
    const heldMs = Date.now() - holdStartedAtRef.current

    // The stream ending while the child is STILL HOLDING is not a finished
    // turn — it is the turn dying underneath them, and it must not be
    // reported as completion.
    //
    // From a real trace: the server answered this session's very first
    // events request with "unknown or expired session" 238ms after creating
    // it (the demo's in-memory sessions do not survive a request landing on
    // a second instance — see CLAUDE.md's own note on streaming_transcription
    // and docs/VOICE_SETUP.md). This block then fell straight through to
    // setMode('idle') while the child went on speaking for another SEVEN
    // SECONDS. All of it was discarded, and heldMs at that instant was 643ms
    // — under MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK — so not even an error was
    // shown.
    //
    // Worse, nothing tore the turn down: the recorder kept capturing and the
    // chunk timer kept uploading. useVoiceRecorder refuses to start a second
    // recording while one is live, so the child's NEXT press reached _start()
    // and never reached startRecording() at all. That is the same latch-off
    // failure #372 fixed on the give-up path, arriving through a different
    // door. failTurn now retires the stream but keeps the microphone open,
    // so the child finishes and their release sends the whole answer in one
    // piece (see FALLBACK_MAX_ATTEMPTS).
    if (modeRef.current === 'recording') {
      logDebug(`voice stream ended while still recording after ${heldMs}ms (errored=${streamErrored}) — retiring the stream`)
      failTurn(attempt)
      return
    }

    attemptRef.current += 1
    sessionIdRef.current = null
    const controller = controllerRef.current
    controllerRef.current = null
    pendingReleaseRef.current = null
    uploadTailRef.current = Promise.resolve()
    clearChunkTimer()
    controller?.abort()
    setMode('idle')
    const processingMs = releasedAtRef.current ? Date.now() - releasedAtRef.current : null
    if (text) {
      // Mirrors the "produced nothing" log below for the success path, which
      // previously had no timing signal at all — a slow-but-successful
      // transcription was invisible in the debug panel. processingMs is
      // release() to final text specifically, isolating server/network time
      // from how long the child was actually still talking.
      logDebug(`voice stream delivered "${text.slice(0, 40)}${text.length > 40 ? '…' : ''}" — ${processingMs}ms after release (${heldMs}ms total hold)`)
      onFinal?.(text)
    } else if (heldMs >= MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK) {
      // A real, multi-second turn produced literally nothing. Confirmed via
      // a real debug-panel trace in the native-SpeechRecognition era: this
      // used to just silently send nothing, leaving the child's whole
      // answer lost with no sign anything went wrong.
      logDebug(`voice stream produced nothing after a ${heldMs}ms turn — surfacing to the user`)
      setMicError('no-speech-heard')
    }
  }, [token, onFinal, clearHoldSafety, clearChunkTimer, recorder, stopRecorder, setMode, failTurn])

  // Shared entry point for both start() and startHold() — functionally
  // identical now (see the KNOWN GAP note above for why start()'s own
  // continuous-mode caller doesn't behave quite like it used to).
  const _start = useCallback(() => {
    if (modeRef.current !== 'idle') return
    const attempt = ++attemptRef.current
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    uploadTailRef.current = Promise.resolve()
    uploadedAudioRef.current = false
    pendingReleaseRef.current = null
    releasedAtRef.current = 0
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
    const beginRecording = () => {
      if (attemptRef.current !== attempt || modeRef.current !== 'recording') return
      recorderStartOwnerRef.current = attempt
      const started = Promise.resolve(recorder.startRecording()).catch(() => {
        if (attemptRef.current !== attempt) return
        stopRef.current()
        setMicError('unavailable')
      })
      recorderStartRef.current = started
      void started.then(() => {
        if (recorderStartRef.current === started) recorderStartRef.current = null
      })
    }
    // stopRecording clears its shared PCM buffers after AudioContext.close.
    // Do not let that old teardown erase the next recording's samples.
    if (recorderStopRef.current) {
      void recorderStopRef.current.then(beginRecording)
    }
    else beginRecording()
    if (attemptRef.current !== attempt) return

    holdSafetyRef.current = setTimeout(() => {
      holdSafetyRef.current = null
      releaseRef.current()
    }, HOLD_SAFETY_TIMEOUT_MS)

    if (!token) {
      logDebug('_start: no token, cannot open a streaming session')
      clearHoldSafety()
      // Nothing will ever consume this recording — hand the microphone back
      // rather than leaving it capturing into a buffer no one will read. See
      // the identical call on the give-up path in beginStream's catch below.
      stopRecorder()
      setMode('idle')
      setMicError('unavailable')
      return
    }

    const beginStream = (attemptsLeft: number) => {
      startVoiceStream(token, language.slice(0, 2), controller.signal)
        .then((sessionId) => {
          if (attemptRef.current !== attempt) return // turn already ended
          logDebug(`startVoiceStream opened session after ${Date.now() - holdStartedAtRef.current}ms`)
          sessionIdRef.current = sessionId
          consumeEvents(sessionId, attempt, controller.signal)

          const pending = pendingReleaseRef.current
          if (pending && pending.attempt === attempt) {
            // The child already let go while this was in flight. Finish the
            // turn now rather than starting a chunk timer for a recorder
            // that has already stopped.
            pendingReleaseRef.current = null
            ;(async () => {
              await uploadSnapshot(attempt, pending.blob)
              if (attemptRef.current !== attempt) return
              try {
                await finishVoiceStream(token, sessionId, controller.signal)
              } catch (err) {
                logDebug(`finishVoiceStream (deferred) failed: ${err instanceof Error ? err.message : String(err)}`)
                failTurn(attempt)
              }
            })()
            return
          }

          chunkTimerRef.current = setInterval(() => uploadSnapshot(attempt), CHUNK_UPLOAD_INTERVAL_MS)
        })
        .catch((err) => {
          logDebug(`startVoiceStream failed: ${err instanceof Error ? err.message : String(err)} (attemptsLeft=${attemptsLeft - 1})`)
          if (attemptRef.current !== attempt) return
          if (attemptsLeft > 1 && isNetworkFailure(err)) {
            retryTimerRef.current = setTimeout(() => {
              if (attemptRef.current !== attempt) return
              beginStream(attemptsLeft - 1)
            }, START_STREAM_RETRY_DELAY_MS)
            return
          }
          // No streaming session, and no native fallback anymore — this turn
          // genuinely can't be transcribed at all.
          // Stop the microphone this turn opened. Without this the recorder
          // kept capturing for a turn that had already been abandoned: the OS
          // recording indicator stayed lit while the UI showed an idle mic
          // button, and — because a still-running recorder refuses to start
          // another one — every subsequent press did nothing at all, so a
          // momentary connection blip turned into voice input being dead for
          // the rest of the session. Confirmed from a real debug-panel trace
          // (four presses after the failure, none of which reached the
          // recorder). See docs/VOICE_SETUP.md.
          //
          // A start that failed on the CONNECTION keeps the microphone open
          // and sends the whole answer at release (see FALLBACK_MAX_ATTEMPTS).
          // A start the server refused, or one that hit the request deadline,
          // is a decision or an ambiguity rather than a dropped connection,
          // and ends the turn as before.
          failTurn(attempt, isNetworkFailure(err))
        })
    }
    beginStream(START_STREAM_MAX_ATTEMPTS)
  }, [token, language, recorder, stopRecorder, consumeEvents, uploadSnapshot, clearHoldSafety, setMode, failTurn])

  const start = useCallback(() => _start(), [_start])
  const startHold = useCallback(() => _start(), [_start])

  // ── Endpointing: end the turn when the child stops talking ───────────────
  // Only runs when the caller asked for it (continuous "Voice on" mode).
  // Hold-to-talk is untouched — there, release() is the endpoint, and a
  // silence detector second-guessing a held button would cut a child off
  // mid-hold.
  //
  // Reads the recorder's existing level meter rather than adding a second
  // analyser: the audio graph is already computing it for the level
  // visualisation, so this costs one sample read every SAMPLE_INTERVAL_MS
  // and no extra DSP. All the actual decisions live in endpointing.ts,
  // which is pure and directly tested — this effect only samples and acts.
  const levelRef = useRef(0)
  levelRef.current = recorder.level
  useEffect(() => {
    if (!endpointOnSilence || mode !== 'recording') return
    let state = initialEndpointState()
    const id = setInterval(() => {
      state = advanceEndpointState(state, {
        level: levelRef.current,
        deltaMs: SAMPLE_INTERVAL_MS,
      })
      const reason = endReason(state)
      if (!reason) return
      clearInterval(id)
      logDebug(
        `endpointing: ending turn (${reason}) after ${Math.round(state.elapsedMs)}ms ` +
        `— ${Math.round(state.speechMs)}ms speech, ${Math.round(state.silenceMs)}ms trailing silence`,
      )
      // The two reasons take different exits, and this is the whole practical
      // difference between a helpful endpoint and an irritating one.
      //
      // finished-speaking → release(): the child DID say something, so the
      // turn must be delivered.
      //
      // no-speech → stop(): nothing was captured, so there is nothing to
      // deliver and nothing went wrong. release() here would produce an empty
      // transcript, which MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK turns into a
      // "I didn't quite catch that" error and a tick on App.tsx's
      // voice-mode circuit breaker — telling a child the microphone failed
      // when they simply hadn't spoken yet. stop() discards silently, and
      // onSilentTimeout lets the caller decide what repeated silence means.
      if (reason === 'finished-speaking') {
        releaseRef.current()
      } else {
        stopRef.current()
        onSilentTimeout?.()
      }
    }, SAMPLE_INTERVAL_MS)
    return () => clearInterval(id)
  }, [endpointOnSilence, mode, onSilentTimeout])

  const stop = useCallback(() => {
    logDebug(`stop() (cancel) from mode=${modeRef.current}`)
    attemptRef.current += 1 // invalidates any in-flight chunk upload / SSE consumer
    controllerRef.current?.abort()
    if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
    if (finishTimerRef.current) clearTimeout(finishTimerRef.current)
    retryTimerRef.current = null
    finishTimerRef.current = null
    pendingReleaseRef.current = null // a cancel discards a deferred release too
    // A cancel is the child's (or the caller's) decision: never send the
    // recording anywhere afterwards.
    streamLostAttemptRef.current = 0
    releasedAudioRef.current = null
    clearHoldSafety()
    clearChunkTimer()
    if (modeRef.current === 'recording') stopRecorder()
    recorder.cancelPrewarm()
    sessionIdRef.current = null
    setInterim('')
    setMode('idle')
  }, [token, recorder, stopRecorder, clearHoldSafety, clearChunkTimer, setMode])

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
    releasedAtRef.current = Date.now()
    const attempt = attemptRef.current
    if (streamLostAttemptRef.current === attempt) {
      // The streaming session died while they were talking; send the whole
      // answer in one piece now that they have finished.
      clearChunkTimer()
      clearHoldSafety()
      void transcribeWholeAnswer(attempt, stopRecorder())
      return
    }
    const sessionId = sessionIdRef.current
    const signal = controllerRef.current?.signal
    clearChunkTimer()
    // Snapshot whatever's been captured so far BEFORE stopRecording() —
    // stopRecording() synchronously nulls out the refs snapshotWav() reads
    // (its own guard against a double-release re-processing the same audio
    // twice), so calling snapshotWav() any later than this line always sees
    // them already cleared and returns null. That silently skipped the
    // final chunk on EVERY release, regardless of hold length — confirmed
    // via a real debug-panel trace: any hold shorter than
    // CHUNK_UPLOAD_INTERVAL_MS (so the periodic tick never fired even once)
    // produced a transcript of literally nothing, every single time.
    const finalWavBlob = recorder.snapshotPcmDelta()
    if (!finalWavBlob && !recorder.isRecording && !uploadedAudioRef.current) {
      stopRef.current()
      setMicError('unavailable')
      return
    }
    // Diagnostic for exactly the ambiguity a "produced nothing" result
    // otherwise leaves open: did the mic actually capture audio during this
    // hold, or did real audio reach the server and come back empty? PCM is
    // 16kHz 16-bit mono, so bytes/32 = milliseconds of audio — directly
    // comparable to the hold duration logged elsewhere. A capturedMs far
    // below the hold length (especially near 0) points at a capture-side
    // race — e.g. the mic not yet live when a barge-in interrupts Bede's own
    // speech — rather than a transcription or network problem.
    const capturedMs = finalWavBlob ? Math.round(finalWavBlob.size / 32) : 0
    logDebug(`release() captured ~${capturedMs}ms of audio this delta (${finalWavBlob?.size ?? 0} bytes)`)
    releasedAudioRef.current = { attempt, audio: stopRecorder() }
    setMode('transcribing')
    clearHoldSafety()
    finishTimerRef.current = setTimeout(() => failTurn(attempt, false), 60_000)

    if (!token) {
      clearHoldSafety()
      setMode('idle')
      return
    }
    if (!sessionId) {
      // Park the captured audio until start resolves. The processing deadline,
      // separate from the recording ceiling, still bounds this wait.
      logDebug('release() before the session opened — deferring the final upload')
      pendingReleaseRef.current = { attempt, blob: finalWavBlob }
      return
    }
    ;(async () => {
      await uploadSnapshot(attempt, finalWavBlob)
      if (attemptRef.current !== attempt) return
      try {
        await finishVoiceStream(token, sessionId, signal)
      } catch (err) {
        logDebug(`finishVoiceStream failed: ${err instanceof Error ? err.message : String(err)}`)
        failTurn(attempt)
      }
    })()
  }, [token, recorder, stopRecorder, clearChunkTimer, clearHoldSafety, uploadSnapshot, setMode, failTurn, transcribeWholeAnswer])
  releaseRef.current = release
  stopRef.current = stop
  useEffect(() => () => stopRef.current(), [token])

  // Prewarming needs the recording-capable audio session too — this is what
  // made it dead on the one platform it matters most for.
  //
  // On iOS/iPadOS 17+ the mode-driven effect above pins the session to
  // 'playback' whenever the mic is not capturing, which is exactly the state
  // prewarm() fires in: it runs from an effect the moment it becomes the
  // child's turn, long before any press. WebKit then refuses the
  // getUserMedia() call outright — `InvalidStateError: AudioSession category
  // is not compatible with audio capture` — on every single turn, silently,
  // because a prewarm failure is deliberately never reported to the child
  // (`report: false`). Seen on every turn of a real iPhone trace.
  //
  // Nothing broke visibly, which is why it survived: getStream() resolves to
  // null rather than rejecting, and startRecording() falls back to its own
  // fresh call at press time. The cost is the entire benefit of prewarming —
  // the child is back to paying cold getUserMedia latency on every press,
  // which is the "transcript missing its first few words" report prewarm was
  // added to fix, and which a slow connection only makes more likely to
  // matter.
  const prewarm = useCallback(() => {
    enterRecordingAudioSession()
    return recorder.prewarm()
  }, [recorder.prewarm])

  // The other half, and the reason this is safe. A prewarmed stream that is
  // never pressed gets released here — and the category has to come back
  // with it, or a session that opened the mic for a press that never came
  // would leave 'play-and-record' pinned for the rest of the lesson, which
  // is precisely the state audioSession.ts exists to keep Bede's own speech
  // out of (it routes TTS to the earpiece instead of the family's chosen
  // output). Guarded on modeRef because this also fires when the child DID
  // press: _start() has already set 'play-and-record' synchronously by then,
  // and restoring playback under a live recording would break the capture.
  const cancelPrewarm = useCallback(() => {
    recorder.cancelPrewarm()
    if (modeRef.current !== 'recording') restorePlaybackAudioSession()
  }, [recorder.cancelPrewarm])

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
    // Opens the mic proactively, before any press — see the recorder's own
    // prewarm() for why a call issued synchronously AT press-time (as
    // _start()/recorder.startRecording() already do) cannot close this gap
    // by itself: it's already essentially as early as a cold call can be.
    // A caller only benefits by invoking this BEFORE the child presses,
    // e.g. as soon as it's genuinely their turn to speak.
    prewarm,
    cancelPrewarm,
  }
}
