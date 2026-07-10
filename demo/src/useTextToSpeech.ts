import { useState, useRef, useCallback } from 'react'
import { speakViaBackend } from './api'

// Tries the backend's self-hosted Kokoro voice first (same one production
// uses) when a trial token is supplied — the bring-your-own-key path has no
// backend at all, so it passes null and goes straight to browser speech.
// Bede's persona is historically male — voice selection prefers a male
// voice in both paths, never gender-ambiguous or female.

function pickBestVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices()
  if (!voices.length) return null
  const priorities = [
    (v: SpeechSynthesisVoice) => v.name === 'Google UK English Male',
    (v: SpeechSynthesisVoice) => v.name === 'Google US English Male',
    (v: SpeechSynthesisVoice) => v.lang.startsWith('en-GB') && v.name.toLowerCase().includes('male'),
    (v: SpeechSynthesisVoice) => v.lang.startsWith('en') && v.name.toLowerCase().includes('male'),
    (v: SpeechSynthesisVoice) => ['Daniel', 'Oliver', 'Arthur', 'Alex', 'Fred'].includes(v.name),
    (v: SpeechSynthesisVoice) => v.lang.startsWith('en'),
  ]
  for (const check of priorities) {
    const match = voices.find(check)
    if (match) return match
  }
  return voices[0] ?? null
}

export function useTextToSpeech(speakToken: string | null = null) {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const speakViaKokoro = useCallback(async (text: string): Promise<boolean> => {
    if (!speakToken) return false
    const blob = await speakViaBackend(speakToken, text)
    if (!blob) return false
    const url = URL.createObjectURL(blob)
    await new Promise<void>((resolve) => {
      const audio = new Audio(url)
      audioRef.current = audio
      audio.onended = () => resolve()
      audio.onerror = () => resolve()
      audio.play().catch(() => resolve())
    })
    URL.revokeObjectURL(url)
    audioRef.current = null
    return true
  }, [speakToken])

  const speakViaBrowser = useCallback((text: string): Promise<void> => {
    return new Promise((resolve) => {
      if (!('speechSynthesis' in window)) { resolve(); return }
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.voice = pickBestVoice()
      utterance.rate = 0.88
      utterance.pitch = 0.92
      utterance.onend = () => resolve()
      utterance.onerror = () => resolve()
      window.speechSynthesis.speak(utterance)
    })
  }, [])

  const speak = useCallback(async (text: string) => {
    const clean = text.replace(/^[📖🔍✨🌿⚠️]\s*/, '').replace(/\*[^*]+\*/g, '').trim()
    if (!clean) return
    setIsSpeaking(true)
    const spoke = await speakViaKokoro(clean)
    if (!spoke) await speakViaBrowser(clean)
    setIsSpeaking(false)
  }, [speakViaKokoro, speakViaBrowser])

  const stop = useCallback(() => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
    setIsSpeaking(false)
  }, [])

  return { speak, stop, isSpeaking }
}
