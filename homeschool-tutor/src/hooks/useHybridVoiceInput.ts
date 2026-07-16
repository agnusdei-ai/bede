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
const MAX_RECORDING_MS = 8000

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

  const clearWatchdog = useCallback(() => {
    if (watchdogRef.current) clearTimeout(watchdogRef.current)
    watchdogRef.current = null
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
    clearWatchdog()
    watchdogRef.current = setTimeout(() => {
      native.stop()
      startFallback()
    }, NATIVE_STALL_TIMEOUT_MS)
  }, [native.interim, native.stop, clearWatchdog, startFallback])

  const start = useCallback(() => {
    if (mode !== 'idle') return
    stoppedByUserRef.current = false

    if (native.isSupported) {
      setMode('native')
      native.start()
      // Safari can accept the mic tap and then never fire onresult/onerror/onend —
      // bail out to the recording fallback if nothing happens in time.
      watchdogRef.current = setTimeout(() => {
        native.stop()
        startFallback()
      }, NATIVE_STALL_TIMEOUT_MS)
    } else {
      startFallback()
    }
  }, [mode, native, startFallback])

  const stop = useCallback(() => {
    stoppedByUserRef.current = true
    clearWatchdog()
    if (mode === 'native') native.stop()
    if (mode === 'recording') recorder.stopRecording()
    setMode('idle')
  }, [mode, native, recorder, clearWatchdog])

  return {
    isListening: mode === 'native' || mode === 'recording',
    isTranscribing: mode === 'transcribing',
    interim: native.interim,
    // MediaRecorder + getUserMedia cover every evergreen browser, so the mic
    // button no longer needs to hide itself when native recognition is absent.
    isSupported: native.isSupported || (!!navigator.mediaDevices?.getUserMedia && !!window.MediaRecorder),
    start,
    stop,
  }
}
