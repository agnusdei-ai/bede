import { useCallback, useRef, useState } from 'react'
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
  const [mode, setMode] = useState<Mode>('idle')
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
    clearWatchdog()
    setMode('recording')
    recorder.startRecording()
  }, [clearWatchdog, recorder])

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
  })

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
