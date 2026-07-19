// Mirror of homeschool-tutor/src/hooks/useHybridVoiceInput.ts for the demo app —
// the demo HAS a backend now (see docs/DEMO_HOSTING.md), so browser speech
// failures fall back to server Whisper exactly like the real app.
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSpeechRecognition } from './useSpeechRecognition'
import { useVoiceRecorder } from './useVoiceRecorder'
import { transcribeFallback } from './api'
import { logDebug } from './debugBus'

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
const HOLD_SAFETY_TIMEOUT_MS = 120000
// Belt-and-suspenders for a real reported failure: a child interrupted Bede
// mid-speech, native recognition produced nothing at all (see the stall
// watchdog above), the recorder fallback kicked in, and the mic never
// recovered — later presses silently no-op'd forever. Root cause: the
// recorder's onComplete had no try/catch around the transcription network
// call, so any thrown error (a transient fetch failure, malformed JSON,
// whatever) skipped straight past the `setMode('idle')` that was supposed
// to run after it, stranding `mode` at 'transcribing' permanently (fixed
// below). This timer is the second layer: even a silent no-op that never
// reaches onComplete at all (e.g. stopRecording() called before
// startRecording()'s own async setup — see useVoiceRecorder.ts — has
// populated its refs) still can't leave `mode` stuck at 'recording' forever.
const RECORDING_SAFETY_TIMEOUT_MS = 10000
// Was 8000ms, then 60000ms — kept in sync with
// homeschool-tutor/src/hooks/useHybridVoiceInput.ts; both were too short
// once a child is really answering out loud, especially one who pauses to
// think mid-explanation, and walkie-talkie hold-to-talk falls into this
// recorder whenever native recognition isn't supported or throws
// synchronously on press, silently truncating longer held answers.
const MAX_RECORDING_MS = 120000

interface Options {
  token: string | null
  onFinal?: (transcript: string) => void
  language?: string
}

type Mode = 'idle' | 'native' | 'recording' | 'transcribing'
export type MicError = 'permission-denied' | 'unavailable'

export function useHybridVoiceInput({ token, onFinal, language = 'en-US' }: Options) {
  const [mode, _setMode] = useState<Mode>('idle')
  // Surfaces the one failure mode that used to be totally silent: a denied
  // or unavailable microphone left `mode` stuck (see startRecording's
  // `if (!stream) return` in useVoiceRecorder, which has no other way to
  // report back) with nothing telling the visitor why the mic button just
  // stopped doing anything. Callers show this once, then call clearMicError.
  const [micError, setMicError] = useState<MicError | null>(null)
  const clearMicError = useCallback(() => setMicError(null), [])
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
  const recordingSafetyRef = useRef<ReturnType<typeof setTimeout> | null>(null)
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

  const clearRecordingSafety = useCallback(() => {
    if (recordingSafetyRef.current) clearTimeout(recordingSafetyRef.current)
    recordingSafetyRef.current = null
  }, [])

  const recorder = useVoiceRecorder({
    maxDurationMs: MAX_RECORDING_MS,
    onComplete: async (wavBlob) => {
      // Recording actually completed and handed off — the safety timeout
      // below (armed in startFallback) exists for the case where THIS
      // callback never runs at all; now that it has, disarm it.
      clearRecordingSafety()
      setMode('transcribing')
      try {
        const text = token ? await transcribeFallback(token, wavBlob, language.slice(0, 2)) : ''
        if (text) onFinal?.(text)
      } catch (err) {
        // Real reported bug: a thrown/rejected transcription call (a
        // transient fetch failure, malformed JSON, whatever) used to skip
        // straight past the setMode('idle') below, stranding `mode` at
        // 'transcribing' permanently — the mic looked and behaved as
        // though stuck, with isTranscribing disabling the button and no
        // event ever left to clear it. try/catch/finally here guarantees
        // idle is always reached regardless of how transcription fails.
        logDebug(`transcribeFallback threw: ${err instanceof Error ? err.message : String(err)}`)
        setMicError('unavailable')
      } finally {
        setMode('idle')
      }
    },
    onError: (reason) => {
      // getUserMedia() is also called speculatively by recorder.prewarm()
      // (see _start below) before native recognition has even had a chance
      // to work — a prewarm failing while mode is still 'native' doesn't
      // mean THIS press is doomed, so only react once the recorder fallback
      // is actually the active path (mode has already been switched to
      // 'recording' by startFallback below).
      if (modeRef.current !== 'recording') return
      logDebug(`recorder onError reason=${reason}`)
      clearWatchdog()
      clearHoldSafety()
      clearRecordingSafety()
      holdModeRef.current = false
      accumRef.current = ''
      setMode('idle')
      setMicError(reason)
    },
  })

  const startFallback = useCallback(() => {
    // The watchdog and native recognition's own onend/onerror can BOTH ask
    // for the fallback on the same attempt (stopping native recognition
    // fires its onend a tick later) — only the first should start the
    // recorder, or two overlapping recording sessions get opened.
    if (modeRef.current === 'recording' || modeRef.current === 'transcribing') return
    logDebug(`startFallback() from mode=${modeRef.current}`)
    clearWatchdog()
    setMode('recording')
    recorder.startRecording()
    // Second layer of recovery alongside onComplete's own try/catch above:
    // covers a silent no-op rather than a thrown error — e.g. release()
    // calling recorder.stopRecording() before startRecording()'s own async
    // setup (see useVoiceRecorder.ts) has populated its refs yet, which
    // returns early without ever invoking onComplete at all. Cleared the
    // moment onComplete actually runs; if it never does, this forces mode
    // back to idle instead of leaving the mic permanently unresponsive.
    clearRecordingSafety()
    recordingSafetyRef.current = setTimeout(() => {
      recordingSafetyRef.current = null
      if (modeRef.current === 'recording') {
        logDebug('recording safety timeout — forcing back to idle')
        setMode('idle')
        setMicError('unavailable')
      }
    }, RECORDING_SAFETY_TIMEOUT_MS)
  }, [clearWatchdog, clearRecordingSafety, recorder, setMode])

  const native = useSpeechRecognition({
    language,
    onFinal: (transcript) => {
      // THE DUPLICATE-SEND BUG: release() sets releasedRef.current = true
      // AND holdModeRef.current = false SYNCHRONOUSLY, then calls
      // native.stop() — but stop() does not cut off an in-flight
      // SpeechRecognition instantly. Safari/Chrome can still deliver one
      // more (now-complete, and often longer/more accurate) final onresult
      // a tick later, i.e. AFTER holdModeRef.current is already false. That
      // used to fall all the way through to the unconditional send at the
      // bottom of this callback, which only exists for the tap-to-speak
      // (non-hold) path and has no idea release() already delivered this
      // utterance — sending the SAME turn a second time (occasionally
      // byte-identical, if the trailing final matches the interim release()
      // already salvaged; otherwise a longer variant of the same turn).
      // releasedRef.current is the one flag that stays true across that
      // entire async gap regardless of what holdModeRef.current is doing —
      // checking it FIRST, unconditionally, closes the gap for both modes.
      if (releasedRef.current) {
        logDebug(`native.onFinal IGNORED (already released) text="${transcript}"`)
        return
      }
      if (holdModeRef.current) {
        // Walkie-talkie: keep the mic open across pauses. Stash each final
        // segment; release() sends the whole thing once the child lets go.
        // A final result is proof of life just like an interim (some engines
        // can emit a final without ever emitting an interim first) — disarm
        // the hold-start watchdog below so it can't fire after the fact.
        clearWatchdog()
        accumRef.current = accumRef.current ? `${accumRef.current} ${transcript}` : transcript
        logDebug(`native.onFinal accumulated (hold) segment="${transcript}" accum="${accumRef.current}"`)
        // The interim that preceded this segment is now baked into it — drop
        // it so release()'s salvage can't re-append text already accumulated.
        lastInterimRef.current = ''
        return
      }
      logDebug(`native.onFinal (tap) text="${transcript}"`)
      clearWatchdog()
      setMode('idle')
      recorder.cancelPrewarm()
      onFinal?.(transcript)
    },
    onError: (error) => {
      if (stoppedByUserRef.current) return
      // 'not-allowed'/'service-not-allowed' (the Web Speech API's own
      // permission-denied codes) mean the SAME getUserMedia-backed
      // permission the recorder fallback would also need is already
      // blocked — falling back would just fail again the same way (or
      // throw a second, redundant permission prompt). Surface it directly
      // instead of wasting a round trip through the fallback.
      if (error === 'not-allowed' || error === 'service-not-allowed') {
        logDebug(`native onError permission denied (${error})`)
        clearWatchdog()
        clearHoldSafety()
        recorder.cancelPrewarm()
        holdModeRef.current = false
        accumRef.current = ''
        setMode('idle')
        setMicError('permission-denied')
        return
      }
      startFallback()
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
    logDebug(`_start(hold=${hold}) nativeSupported=${native.isSupported}`)
    stoppedByUserRef.current = false
    releasedRef.current = false
    holdModeRef.current = hold
    accumRef.current = ''
    lastInterimRef.current = ''
    // A fresh press means a fresh attempt — don't let a previous failure's
    // banner linger once the child tries again.
    setMicError(null)

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
    logDebug(`stop() (cancel) from mode=${modeRef.current}`)
    stoppedByUserRef.current = true
    releasedRef.current = true
    clearWatchdog()
    clearHoldSafety()
    clearRecordingSafety()
    if (modeRef.current === 'native') {
      native.stop()
      recorder.cancelPrewarm()
    }
    if (modeRef.current === 'recording') recorder.stopRecording()
    holdModeRef.current = false
    accumRef.current = ''
    setMode('idle')
  }, [native, recorder, clearWatchdog, clearHoldSafety, clearRecordingSafety, setMode])

  // Walkie-talkie release: the child let go of the button. Send whatever the
  // engine has captured so far — accumulated final segments plus the latest
  // interim the engine hasn't promoted yet — exactly once. Unlike stop()
  // (which cancels and discards), release() delivers the transcript.
  const release = useCallback(() => {
    logDebug(`release() from mode=${modeRef.current} accum="${accumRef.current}" interim="${lastInterimRef.current}"`)
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
    micError,
    clearMicError,
    // getUserMedia + AudioContext (the fallback's raw-PCM capture path —
    // see useVoiceRecorder) cover every evergreen browser, so the mic
    // button no longer needs to hide itself when native recognition is absent.
    isSupported:
      native.isSupported ||
      (!!navigator.mediaDevices?.getUserMedia && !!(window.AudioContext || (window as unknown as { webkitAudioContext?: unknown }).webkitAudioContext)),
    start,
    startHold,
    release,
    stop,
  }
}
