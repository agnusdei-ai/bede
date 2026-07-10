import { useState, useRef, useCallback } from 'react'
import { speakViaBackend } from './api'

// Tries the backend's self-hosted Kokoro voice first (same one production
// uses) — both demo tiers always supply a real token, since both are
// backend-mediated. Falls back to browser speech if the backend request
// fails or isn't configured. Bede's persona is historically male — voice
// selection prefers a male voice, never gender-ambiguous or female.

// A name containing "female" also contains "male" as a literal substring
// ("fe-MALE") — naively checking name.includes('male') alone matches female
// voices too. Every male check below excludes isFemale() explicitly to
// avoid this exact bug (a real, confirmed cause of picking a female voice
// on at least one Android/Chrome device that labels voices "...Female").
function isFemaleVoiceName(name: string): boolean {
  return name.toLowerCase().includes('female')
}
function isMaleVoiceName(name: string): boolean {
  return name.toLowerCase().includes('male') && !isFemaleVoiceName(name)
}

// Exact names confirmed male across common desktop/mobile TTS engines that
// don't label voices "male"/"female" in the first place (Safari/macOS/iOS
// give plain first names; Windows/Edge give "Microsoft <Name> - ...").
// Checked before any substring heuristics since exact names are unambiguous.
const KNOWN_MALE_VOICE_NAMES = new Set([
  'Daniel', 'Oliver', 'Arthur', 'Alex', 'Fred', 'Aaron', 'Gordon',
  'Microsoft David - English (United States)',
  'Microsoft Mark - English (United States)',
  'Microsoft Guy - English (United States)',
  'Microsoft Ryan - English (United Kingdom)',
  'Microsoft George - English (United Kingdom)',
  'Google UK English Male',
  'Google US English Male',
])

function pickBestVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices()
  if (!voices.length) return null
  const priorities = [
    (v: SpeechSynthesisVoice) => KNOWN_MALE_VOICE_NAMES.has(v.name),
    (v: SpeechSynthesisVoice) => v.lang.startsWith('en-GB') && isMaleVoiceName(v.name),
    (v: SpeechSynthesisVoice) => v.lang.startsWith('en') && isMaleVoiceName(v.name),
    // Many Android/OEM TTS engines (Samsung's included) expose English
    // voices with no gender word in the name at all — nothing above can
    // match those. Rather than falling straight through to "just take the
    // first English voice" (which might be the one explicitly labeled
    // female), prefer any voice that ISN'T explicitly female first — an
    // unlabeled voice is a better bet than a confirmed-wrong one.
    (v: SpeechSynthesisVoice) => v.lang.startsWith('en') && !isFemaleVoiceName(v.name),
    (v: SpeechSynthesisVoice) => v.lang.startsWith('en'),
  ]
  for (const check of priorities) {
    const match = voices.find(check)
    if (match) return match
  }
  return voices[0] ?? null
}

// Chrome — especially on Android — returns an EMPTY array from getVoices()
// on the very first call after page load; the real list only populates
// asynchronously via 'voiceschanged', sometimes after Bede's very first
// line already wants to speak. Picking synchronously before that fires
// silently falls back to whatever voice the OS/engine defaults to, which is
// why the chosen voice could vary between sessions on the exact same
// device. Resolving once (module-scoped, so it's stable for the whole tab)
// and waiting briefly for the real list makes the pick deterministic.
let resolvedVoice: SpeechSynthesisVoice | null = null
let voiceResolutionPromise: Promise<SpeechSynthesisVoice | null> | null = null

function resolveVoice(): Promise<SpeechSynthesisVoice | null> {
  if (resolvedVoice) return Promise.resolve(resolvedVoice)
  if (voiceResolutionPromise) return voiceResolutionPromise

  voiceResolutionPromise = new Promise((resolve) => {
    const tryPick = (): boolean => {
      if (!window.speechSynthesis.getVoices().length) return false
      resolvedVoice = pickBestVoice()
      resolve(resolvedVoice)
      return true
    }

    if (tryPick()) return

    const handler = () => {
      if (tryPick()) {
        window.speechSynthesis.removeEventListener('voiceschanged', handler)
        clearTimeout(timeoutId)
      }
    }
    window.speechSynthesis.addEventListener('voiceschanged', handler)

    // Some engines never fire voiceschanged at all — don't wait forever.
    const timeoutId = setTimeout(() => {
      window.speechSynthesis.removeEventListener('voiceschanged', handler)
      tryPick()
      resolve(resolvedVoice)
    }, 1000)
  })

  return voiceResolutionPromise
}

/**
 * Call synchronously inside a real click/submit handler — e.g. the setup
 * form's submit, or the trial PIN's login button — BEFORE any await. Bede's
 * very first line (the subject opener) is spoken automatically once the
 * chat screen mounts, with no user gesture directly in that call stack: it
 * only exists because an earlier async fetch/stream finished. Strict
 * browsers (iOS Safari especially, and this app's primary target is
 * tablets) silently refuse both speechSynthesis and <audio>.play() unless
 * they were unlocked by a genuine, synchronous user gesture first. This
 * "spends" that gesture on a silent no-op so the later automatic speech
 * isn't blocked.
 */
export function unlockSpeechForSession() {
  if ('speechSynthesis' in window) {
    try {
      const u = new SpeechSynthesisUtterance(' ')
      u.volume = 0
      window.speechSynthesis.speak(u)
    } catch {
      // best-effort — never block the actual form submission on this
    }
  }
  try {
    const silent = new Audio(
      'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=',
    )
    silent.volume = 0
    silent.play().then(() => silent.pause()).catch(() => {})
  } catch {
    // best-effort
  }
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
      resolveVoice().then((voice) => {
        const utterance = new SpeechSynthesisUtterance(text)
        if (voice) utterance.voice = voice
        utterance.rate = 0.88
        utterance.pitch = 0.92
        utterance.onend = () => resolve()
        utterance.onerror = () => resolve()
        window.speechSynthesis.speak(utterance)
      })
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
