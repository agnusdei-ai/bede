import { useState, useRef, useCallback } from 'react'

// Ported from homeschool-tutor/src/hooks/useTextToSpeech.ts, calling ElevenLabs
// directly from the browser (no backend proxy) when a key is configured.
// Bede's persona is historically male — voice selection prefers a male voice
// in both paths, never gender-ambiguous or female.

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

export function useTextToSpeech(elevenLabsKey: string | null, elevenLabsVoiceId: string | null) {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const speakViaElevenLabs = useCallback(async (text: string): Promise<boolean> => {
    if (!elevenLabsKey || !elevenLabsVoiceId) return false
    try {
      const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${elevenLabsVoiceId}`, {
        method: 'POST',
        headers: { 'xi-api-key': elevenLabsKey, 'Content-Type': 'application/json', Accept: 'audio/mpeg' },
        body: JSON.stringify({
          text,
          model_id: 'eleven_turbo_v2_5',
          voice_settings: { stability: 0.55, similarity_boost: 0.8 },
        }),
      })
      if (!res.ok) return false
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      await new Promise<void>((resolve) => {
        const audio = new Audio(url)
        audioRef.current = audio
        audio.onended = () => resolve()
        audio.onerror = () => resolve()
        audio.play().catch(() => resolve())
      })
      URL.revokeObjectURL(url)
      return true
    } catch {
      return false
    }
  }, [elevenLabsKey, elevenLabsVoiceId])

  const speak = useCallback(async (text: string) => {
    const clean = text.replace(/^[📖🔍✨🌿⚠️]\s*/, '').replace(/\*[^*]+\*/g, '').trim()
    if (!clean) return
    setIsSpeaking(true)
    const spoke = await speakViaElevenLabs(clean)
    if (!spoke && 'speechSynthesis' in window) {
      await new Promise<void>((resolve) => {
        const utterance = new SpeechSynthesisUtterance(clean)
        utterance.voice = pickBestVoice()
        utterance.rate = 0.88
        utterance.pitch = 0.92
        utterance.onend = () => resolve()
        utterance.onerror = () => resolve()
        window.speechSynthesis.speak(utterance)
      })
    }
    setIsSpeaking(false)
  }, [speakViaElevenLabs])

  const stop = useCallback(() => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
    setIsSpeaking(false)
  }, [])

  return { speak, stop, isSpeaking }
}
