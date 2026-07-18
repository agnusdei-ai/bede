import { useCallback, useEffect, useRef, useState } from 'react'
import { useSpeechRecognition } from './useSpeechRecognition'
import { useVoiceRecorder } from './useVoiceRecorder'
import { transcribeFallback } from '../services/voiceApi'

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
// Was 8000ms — far too short for a real spoken answer once a child is
// actually explaining their thinking out loud, and the walkie-talkie
// hold-to-talk mode (which is meant to support longer, paused-and-resumed
// answers) falls into this exact recorder whenever native recognition
// isn't supported or throws synchronously on press (see the catch in
// _start below) — so this cap silently truncated long walkie-talkie
// answers on any browser without native SpeechRecognition (Firefox,
// some Android WebViews), not just short tap-to-speak utterances.
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
        // A final result is proof of life just like an interim (some engines
        // can emit a final without ever emitting an interim first) — disarm
        // the hold-start watchdog below so it can't fire after the fact.
        clearWatchdog()
        accumRef.current = accumRef.current ? `${accumRef.current} ${transcript}` : transcript
        // The interim that preceded this segment is now baked into it — drop
        // it so release()'s salvage can't re-append text already accumulated.
        lastInterimRef.current = ''
        return
      }
      clearWatchdog()
      setMode('idle')
      recorder.cancelPrewarm()
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
      recorder.cancelPrewarm()
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
    // watchdog and dump into the recording fallback. But the FIRST interim
    // is still proof native is alive — disarm the hold-start watchdog
    // (armed in _start below) for good, then stop; don't rearm it, since
    // later pauses are the child's call, not a timer's.
    if (holdModeRef.current) {
      clearWatchdog()
      // First proof native is alive for this hold — the prewarmed mic
      // stream (opened below in _start, in case a fallback turns out to be
      // needed) is no longer going to be used, so release it now rather
      // than holding the mic open pointlessly for the rest of the press.
      recorder.cancelPrewarm()
      return
    }
    clearWatchdog()
    watchdogRef.current = setTimeout(() => {
      native.stop()
      startFallback()
    }, NATIVE_STALL_TIMEOUT_MS)
  }, [native.interim, native.stop, clearWatchdog, startFallback, recorder])

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
      // Open the fallback recorder's mic stream NOW, synchronously, inside
      // this same press-gesture call stack — before we even know whether
      // native recognition will work. iOS Safari only honors getUserMedia()
      // requests initiated directly inside a user gesture; if native stalls
      // and the watchdog below has to fall back several seconds from now,
      // that fallback runs from a setTimeout callback, well outside any
      // gesture — a getUserMedia() call made cold at that point is exactly
      // the case Safari silently blocks. Priming here sidesteps that: by
      // the time the fallback might be needed, the stream request was
      // already made at the right moment and is just waiting to be reused.
      recorder.prewarm()
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
      // so once native has proven it's alive, the stall watchdog must not
      // fight the user over a natural pause — see the interim effect above,
      // which disarms (and never rearms) this same timer on first signal.
      // But Safari (esp. iOS) can accept the mic press and then never fire
      // ONE SINGLE onresult for the entire hold — no interim, no final,
      // nothing (see useSpeechRecognition.ts) — and unlike tap-to-speak,
      // hold mode can't lean on onEndWithoutResult firing after release()
      // to catch this: release() sets stoppedByUserRef BEFORE stopping
      // native specifically to suppress that signal, so a fallback
      // recording doesn't start moments after the child already let go.
      // So arm the SAME watchdog here too (for both modes) — for hold mode
      // it only fires if literally nothing has happened yet, and switches
      // this hold over to the recorder fallback while the child is still
      // holding, so release() still has real audio to send.
      watchdogRef.current = setTimeout(() => {
        native.stop()
        startFallback()
      }, NATIVE_STALL_TIMEOUT_MS)
      if (hold) {
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
    if (modeRef.current === 'native') {
      native.stop()
      recorder.cancelPrewarm()
    }
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
      recorder.cancelPrewarm()
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
