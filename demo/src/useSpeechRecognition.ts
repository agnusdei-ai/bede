import { useState, useRef, useCallback, useEffect } from 'react'

// Native Web Speech API only — the real app's useHybridVoiceInput falls back to
// server-side Whisper transcription when this is unsupported/unreliable (notably
// on Safari/iOS), but this demo has no backend to fall back to. If voice input
// doesn't work well in your browser, typing always works as the alternative.

export function useSpeechRecognition(onFinal: (text: string) => void) {
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
    const Ctor = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rec: any = new Ctor()
    rec.continuous = false
    rec.interimResults = true
    rec.lang = 'en-US'
    rec.maxAlternatives = 1

    rec.onstart = () => setIsListening(true)
    rec.onresult = (e: any) => {
      let interimText = ''
      let finalText = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const result = e.results[i]
        if (result.isFinal) finalText += result[0].transcript
        else interimText += result[0].transcript
      }
      setInterim(interimText)
      if (finalText.trim()) {
        onFinal(finalText.trim())
        setInterim('')
        stop()
      }
    }
    rec.onerror = () => { setIsListening(false); setInterim('') }
    rec.onend = () => { setIsListening(false); setInterim('') }

    recognitionRef.current = rec
    rec.start()
  }, [isSupported, isListening, onFinal, stop])

  useEffect(() => () => { recognitionRef.current?.abort() }, [])

  return { isListening, interim, isSupported, start, stop }
}
