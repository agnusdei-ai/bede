import { useState, useRef, useCallback, useEffect } from 'react'

/**
 * Web Speech API hook for real-time STT during tutoring.
 * Shows interim results live, calls onFinal when recognition settles.
 *
 * Browser support: Chrome, Edge, Safari 15+. Firefox uses the Whisper fallback.
 */

interface Options {
  onFinal?: (transcript: string) => void
  language?: string
  continuous?: boolean
}

export function useSpeechRecognition({ onFinal, language = 'en-US', continuous = false }: Options = {}) {
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
        onFinal?.(finalText.trim())
        setInterim('')
        if (!continuous) stop()
      }
    }

    rec.onerror = (e: any) => {
      if (e.error !== 'no-speech') console.warn('Speech recognition error:', e.error)
      setIsListening(false)
      setInterim('')
    }

    rec.onend = () => {
      setIsListening(false)
      setInterim('')
    }

    recognitionRef.current = rec
    rec.start()
  }, [isSupported, isListening, continuous, language, onFinal, stop])

  useEffect(() => () => { recognitionRef.current?.abort() }, [])

  return { isListening, interim, isSupported, start, stop }
}
