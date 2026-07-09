import { useState, useRef, useCallback, useEffect } from 'react'

/**
 * Web Speech API hook for Bede's voice output.
 *
 * Voice selection priority:
 *  1. "Google UK English Female" — warm, clear, good for children
 *  2. "Google US English Female"
 *  3. Any "en-GB" female voice
 *  4. Any "en" female voice
 *  5. System default
 */

function pickBestVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices()
  if (!voices.length) return null

  const priorities = [
    (v: SpeechSynthesisVoice) => v.name === 'Google UK English Female',
    (v: SpeechSynthesisVoice) => v.name === 'Google US English Female',
    (v: SpeechSynthesisVoice) => v.lang.startsWith('en-GB') && v.name.toLowerCase().includes('female'),
    (v: SpeechSynthesisVoice) => v.lang.startsWith('en') && v.name.toLowerCase().includes('female'),
    (v: SpeechSynthesisVoice) => v.lang.startsWith('en'),
  ]

  for (const check of priorities) {
    const match = voices.find(check)
    if (match) return match
  }
  return voices[0] ?? null
}

export function useTextToSpeech() {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [enabled, setEnabled] = useState(true)
  const [isSupported] = useState(() => 'speechSynthesis' in window)
  const queueRef = useRef<string[]>([])
  const speakingRef = useRef(false)

  const processQueue = useCallback(() => {
    if (!isSupported || speakingRef.current || queueRef.current.length === 0) return
    const text = queueRef.current.shift()!
    if (!text.trim()) { processQueue(); return }

    // Strip tool-result prefixes (📖, 🔍, ✨, 🌿) for natural speech
    const cleanText = text.replace(/^[📖🔍✨🌿⚠️]\s*/, '').replace(/\*[^*]+\*/g, '')

    const utterance = new SpeechSynthesisUtterance(cleanText)
    utterance.voice = pickBestVoice()
    utterance.rate = 0.88    // slightly slower for children
    utterance.pitch = 1.05
    utterance.volume = 1.0

    utterance.onstart = () => { speakingRef.current = true; setIsSpeaking(true) }
    utterance.onend = () => {
      speakingRef.current = false
      setIsSpeaking(false)
      processQueue()
    }
    utterance.onerror = () => {
      speakingRef.current = false
      setIsSpeaking(false)
      processQueue()
    }

    window.speechSynthesis.speak(utterance)
  }, [isSupported])

  const speak = useCallback((text: string) => {
    if (!isSupported || !enabled || !text.trim()) return
    // Split long messages at sentence boundaries so pauses feel natural
    const sentences = text.match(/[^.!?]+[.!?]+/g) ?? [text]
    queueRef.current.push(...sentences.map((s) => s.trim()).filter(Boolean))
    processQueue()
  }, [isSupported, enabled, processQueue])

  const stop = useCallback(() => {
    if (!isSupported) return
    window.speechSynthesis.cancel()
    queueRef.current = []
    speakingRef.current = false
    setIsSpeaking(false)
  }, [isSupported])

  const toggle = useCallback(() => {
    if (enabled) stop()
    setEnabled((v) => !v)
  }, [enabled, stop])

  // Voices load asynchronously on some browsers
  useEffect(() => {
    if (!isSupported) return
    window.speechSynthesis.onvoiceschanged = () => {} // trigger re-render
    return () => { window.speechSynthesis.cancel() }
  }, [isSupported])

  return { speak, stop, toggle, isSpeaking, enabled, isSupported }
}
