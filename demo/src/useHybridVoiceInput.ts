// Mirror of homeschool-tutor/src/hooks/useHybridVoiceInput.ts for the demo app —
// the demo HAS a backend now (see docs/DEMO_HOSTING.md), so browser speech
// failures fall back to server Whisper exactly like the real app.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSpeechRecognition } from './useSpeechRecognition'
import { useVoiceRecorder } from './useVoiceRecorder'
import { transcribeFallback } from './api'

/**
 * Voice input for the chat mic button. Tries the native Web Speech API first
 * (instant, free, works well on Chrome/Edge) but falls back to recording +
 * server-side Whisper transcription whenever native recognition is
 * unsupported, errors out, or stalls — which covers Safari/iOS's documented
 * failure modes (silent stop after the first phrase, no result on first
 * attempt) as well as Firefox, which never implemented the API at all.
 */

const NATIVE_STALL_TIMEOUT_MS = 4000
// Hold-to-talk has no per-utterance stall watchdog by design (the child, not
// a timer, decides when a turn ends — see the effect below). But since the
// single mic button is now ALWAYS hold-to-talk with no manual toggle to
// escape a stuck state, an unbounded hold is no longer just "long" — it's a
// real dead end if a release event is ever missed (a touch pointerup that
// doesn't reach the button, a dropped event on some Android WebView, etc.).
// This safety net auto-releases (sending whatever was captured, same as a
// real release) after the same ceiling already used for the recording
// fallback, so a missed release degrades to "the turn ended a bit early"
// rather than "the mic is stuck forever with no way to clear it."
const HOLD_SAFETY_TIMEOUT_MS = 60000
// Was 8000ms — kept in sync with homeschool-tutor/src/hooks/useHybridVoiceInput.ts;
// too short once a child is really answering out loud, and walkie-talkie
// hold-to-talk falls into this recorder whenever native recognition isn't
// supported or throws synchronously on press, silently truncating longer
// held answers.
const MAX_RECORDING_MS = 60000

interface Options {
  token: string | null
  onFinal?: (transcript: string) => void
  language?: string
}

type Mode = 'idle' | 'native' | 'recording' | 'transcribing'

export function useHybridVoiceInput({ token, onFinal, language = 'en-US' }: Options) {
  const [mode, _setMode] = useState<Mode>('idle')
  // Mirrored in a ref so callbacks fired from browser events (recognition
  // onend, the watchdog timer) see the CURRENT mode, not a stale closure —
  // startFallback below relies on this to dedupe.
  const modeRef = useRef<Mode>('idle')
  const setMode = useCallback((m: Mode) => {
    modeRef.current = m
    _setMode(m)
  }, [])
  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const stoppedByUserRef = useRef(false)
  // Hold-to-talk (walkie-talkie) state. In hold mode the native session runs
  // CONTINUOUS for the whole press so natural pauses don't end it; final
  // segments accumulate in accumRef and are sent exactly once on explicit
  // release(). No timer or effect ever restarts recognition — only a user
  // press starts it and only a user release ends it.
  const holdModeRef = useRef(false)
  const accumRef = useRef('')
  const lastInterimRef = useRef('')
  const holdSafetyRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Always points at the CURRENT release() so the hold-safety timer (armed
  // inside _start, defined below) can call it without a forward reference —
  // updated on every render, right after release is (re)created.
  const releaseRef = useRef<() => void>(() => {})
  // Gates native onFinal after release so the trailing async final that
  // Safari/Chrome emit a tick after stop() doesn't re-add already-salvaged text.
  const releasedRef = useRef(false)

  const clearWatchdog = useCallback(() => {
    if (watchdogRef.current) clearTimeout(watchdogRef.current)
    watchdogRef.current = null
  }, [])

  const clearHoldSafety = useCallback(() => {
    if (holdSafetyRef.current) clearTimeout(holdSafetyRef.current)
    holdSafetyRef.current = null
  }, [])

  const recorder = useVoiceRecorder({
    maxDurationMs: MAX_RECORDING_MS,
    onComplete: async (wavBlob) => {
      setMode('transcribing')
      const text = token ? await transcribeFallback(token, wavBlob, language.slice(0, 2)) : ''
      setMode('idle')
      if (text) onFinal?.(text)
    },
  })

  const startFallback = useCallback(() => {
    // The watchdog and native recognition's own onend/onerror can BOTH ask
    // for the fallback on the same attempt (stopping native recognition
    // fires its onend a tick later) — only the first should start the
    // recorder, or two overlapping MediaRecorder sessions get opened.
    if (modeRef.current === 'recording' || modeRef.current === 'transcribing') return
    clearWatchdog()
    setMode('recording')
    recorder.startRecording()
  }, [clearWatchdog, recorder, setMode])

  const native = useSpeechRecognition({
    language,
    onFinal: (transcript) => {
      if (holdModeRef.current) {
        // Walkie-talkie: keep the mic open across pauses. Stash each final
        // segment; release() sends the whole thing once the child lets go.
        if (releasedRef.current) return
        accumRef.current = accumRef.current ? `${accumRef.current} ${transcript}` : transcript
        // The interim that preceded this segment is now baked into it — drop
        // it so release()'s salvage can't re-append text already accumulated.
        lastInterimRef.current = ''
        return
      }
      clearWatchdog()
      setMode('idle')
      onFinal?.(transcript)
    },
    onError: () => {
      if (!stoppedByUserRef.current) startFallback()
    },
    onEndWithoutResult: () => {
      if (!stoppedByUserRef.current) startFallback()
    },
    onNoSpeech: () => {
      // Nobody spoke — nothing to transcribe, so don't burn a Whisper round
      // trip on 8s of silence. Go idle; SocraticChat's dictation keepalive
      // restarts the mic if voice mode is still on.
      clearWatchdog()
      setMode('idle')
    },
  })

  // Interim results prove native recognition is alive and hearing the
  // child — each new one RE-ARMS the stall watchdog instead of disarming it
  // outright. A one-shot disarm (the original approach) left the session
  // with NO stall protection at all for the rest of the utterance the
  // moment a single interim result had ever arrived — but Safari's
  // documented failure mode (see useSpeechRecognition.ts) is stalling out
  // completely PARTWAY through a longer utterance, not just at the very
  // start, and a one-shot disarm meant that later stall just sat there
  // "listening" forever with nothing ever reaching Bede. A rolling window
  // catches a stall at any point while staying just as tolerant of
  // Chrome's real pattern (interim results throughout a long utterance, one
  // FINAL transcript only once the child stops) — a fresh interim keeps
  // re-arming the window well inside the stall timeout as long as
  // recognition is still actually making progress.
  useEffect(() => {
    if (modeRef.current !== 'native' || !native.interim) return
    // Remember the latest interim so release() can salvage a transcript the
    // engine hasn't yet promoted to a final segment.
    lastInterimRef.current = native.interim
    // In hold-to-talk the child is deliberately in control of when the turn
    // ends (release), so a mid-utterance pause must NOT trip the stall
    // watchdog and dump into the recording fallback — skip re-arming it.
    if (holdModeRef.current) return
    clearWatchdog()
    watchdogRef.current = setTimeout(() => {
      native.stop()
      startFallback()
    }, NATIVE_STALL_TIMEOUT_MS)
  }, [native.interim, native.stop, clearWatchdog, startFallback])

  // Shared entry point for both tap-to-speak (hold=false) and walkie-talkie
  // hold-to-talk (hold=true). Uses modeRef (synchronous) rather than the mode
  // state so a fast press right after release isn't blocked by a stale render.
  const _start = useCallback((hold: boolean) => {
    if (modeRef.current !== 'idle') return
    stoppedByUserRef.current = false
    releasedRef.current = false
    holdModeRef.current = hold
    accumRef.current = ''
    lastInterimRef.current = ''

    if (native.isSupported) {
      setMode('native')
      try {
        native.start(hold)
      } catch {
        // iOS Safari can throw synchronously out of start() (e.g. its own
        // notion of "already started" or a permission-state edge case)
        // instead of delivering it as an onerror event. If that throw isn't
        // caught here, the watchdog below never gets registered at all —
        // mode stays stuck at 'native' forever with no event and no timer
        // ever going to rescue it. Fall back immediately; a synchronous
        // throw means native recognition definitely isn't going to work for
        // this attempt.
        startFallback()
        return
      }
      // In hold-to-talk the child, not a timer, decides when the turn ends,
      // so the stall watchdog would only fight the user — don't arm it. In
      // tap-to-speak, Safari can accept the mic tap and then never fire
      // onresult/onerror/onend, so bail to the recording fallback if nothing
      // happens in time.
      if (!hold) {
        watchdogRef.current = setTimeout(() => {
          native.stop()
          startFallback()
        }, NATIVE_STALL_TIMEOUT_MS)
      } else {
        // See HOLD_SAFETY_TIMEOUT_MS above — bounds the worst case where a
        // release event never reaches the button at all.
        holdSafetyRef.current = setTimeout(() => {
          holdSafetyRef.current = null
          if (holdModeRef.current) releaseRef.current()
        }, HOLD_SAFETY_TIMEOUT_MS)
      }
    } else {
      startFallback()
    }
  }, [native, startFallback, setMode])

  const start = useCallback(() => _start(false), [_start])
  const startHold = useCallback(() => _start(true), [_start])

  const stop = useCallback(() => {
    stoppedByUserRef.current = true
    releasedRef.current = true
    clearWatchdog()
    clearHoldSafety()
    if (modeRef.current === 'native') native.stop()
    if (modeRef.current === 'recording') recorder.stopRecording()
    holdModeRef.current = false
    accumRef.current = ''
    setMode('idle')
  }, [native, recorder, clearWatchdog, clearHoldSafety, setMode])

  // Walkie-talkie release: the child let go of the button. Send whatever the
  // engine has captured so far — accumulated final segments plus the latest
  // interim the engine hasn't promoted yet — exactly once. Unlike stop()
  // (which cancels and discards), release() delivers the transcript.
  const release = useCallback(() => {
    clearWatchdog()
    clearHoldSafety()
    if (modeRef.current === 'native') {
      stoppedByUserRef.current = true
      releasedRef.current = true
      const salvage = lastInterimRef.current.trim()
      native.stop()
      const text = [accumRef.current.trim(), salvage].filter(Boolean).join(' ').trim()
      accumRef.current = ''
      lastInterimRef.current = ''
      holdModeRef.current = false
      setMode('idle')
      if (text) onFinal?.(text)
    } else if (modeRef.current === 'recording') {
      // Native wasn't available for this press; the recorder is capturing.
      // Stopping it runs onComplete → transcribe → onFinal (sends once).
      holdModeRef.current = false
      recorder.stopRecording()
    }
    // idle / transcribing: nothing to release.
  }, [native, recorder, clearWatchdog, clearHoldSafety, setMode, onFinal])
  releaseRef.current = release

  return {
    isListening: mode === 'native' || mode === 'recording',
    isTranscribing: mode === 'transcribing',
    interim: native.interim,
    // MediaRecorder + getUserMedia cover every evergreen browser, so the mic
    // button no longer needs to hide itself when native recognition is absent.
    isSupported: native.isSupported || (!!navigator.mediaDevices?.getUserMedia && !!window.MediaRecorder),
    start,
    startHold,
    release,
    stop,
  }
}
