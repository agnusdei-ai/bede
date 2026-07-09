import { useState, useRef, useCallback, useEffect } from 'react'

/**
 * Web Speech API hook for real-time STT during tutoring.
 * Shows interim results live, calls onFinal when recognition settles.
 *
 * Safari's implementation (incl. iOS) is unreliable in practice — it can stop
 * silently after the first phrase or fire spurious errors. Callers should treat
 * onError/onEndWithoutResult as a signal to fall back to server-side transcription
 * (see useHybridVoiceInput) rather than relying on this hook alone.
 */

interface Options {
  onFinal?: (transcript: string) => void
  /** Fired on a real recognition error (never for benign 'no-speech'). */
  onError?: (error: string) => void
  /** Fired when recognition ends without ever producing a final result. */
  onEndWithoutResult?: () => void
  language?: string
  continuous?: boolean
}

export function useSpeechRecognition({ onFinal, onError, onEndWithoutResult, language = 'en-US', continuous = false }: Options = {}) {
  const [isListening, setIsListening] = useState(false)
  const [interim, setInterim] = useState('')
  const [isSupported] = useState(() => 'SpeechRecognition' in window || 'webkitSpeechRecognition' in window)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null)

  const stop = useCallback(() => {
    recognitionRef.current?.stop()
    recognitionRef.current = null
    setIsListening(false)
    setInterim('')
  }, [])

  const start = useCallback(() => {
    if (!isSupported || isListening) return
    let gotFinalResult = false

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SpeechRecognitionCtor = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rec: any = new SpeechRecognitionCtor()
    rec.continuous = continuous
    rec.interimResults = true
    rec.lang = language
    rec.maxAlternatives = 1

    rec.onstart = () => setIsListening(true)

    rec.onresult = (e: any) => {
      let interimText = ''
      let finalText = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const result = e.results[i]
        if (result.isFinal) {
          finalText += result[0].transcript
        } else {
          interimText += result[0].transcript
        }
      }
      setInterim(interimText)
      if (finalText.trim()) {
        gotFinalResult = true
        onFinal?.(finalText.trim())
        setInterim('')
        if (!continuous) stop()
      }
    }

    rec.onerror = (e: any) => {
      if (e.error !== 'no-speech') {
        console.warn('Speech recognition error:', e.error)
        onError?.(e.error)
      }
      setIsListening(false)
      setInterim('')
    }

    rec.onend = () => {
      setIsListening(false)
      setInterim('')
      if (!gotFinalResult) onEndWithoutResult?.()
    }

    recognitionRef.current = rec
    rec.start()
  }, [isSupported, isListening, continuous, language, onFinal, onError, onEndWithoutResult, stop])

  useEffect(() => () => { recognitionRef.current?.abort() }, [])

  return { isListening, interim, isSupported, start, stop }
}
