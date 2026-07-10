import { useState, useRef, useCallback, useEffect } from 'react'

/**
 * Bede's spoken voice.
 *
 * Tries the backend's self-hosted TTS first (services/voice_synthesis.py on
 * the server — a warm, dedicated male monk voice via Kokoro, no cloud API).
 * Falls back to the browser's built-in speechSynthesis when the backend
 * isn't configured or the request fails, so voice output never breaks the
 * session.
 *
 * Bede's persona is historically male (the Venerable Bede) — voice selection
 * in both paths prefers a male voice, never a gender-ambiguous or female one.
 */

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

/**
 * Call synchronously inside a real click/submit handler — e.g. the login
 * form's submit — BEFORE any await. Bede's very first line (the subject
 * opener) is spoken automatically once the session screen mounts, with no
 * user gesture directly in that call stack: it only exists because an
 * earlier async login/fetch chain finished. Strict browsers (iOS Safari
 * especially — this app's tablets are the primary target device) silently
 * refuse both speechSynthesis and <audio>.play() unless they were unlocked
 * by a genuine, synchronous user gesture first. This "spends" that gesture
 * on a silent no-op so the later automatic speech isn't blocked.
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

export function useTextToSpeech(token: string | null = null) {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [enabled, setEnabled] = useState(true)
  const [isSupported] = useState(() => 'speechSynthesis' in window)
  const queueRef = useRef<string[]>([])
  const speakingRef = useRef(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const stoppedRef = useRef(false)

  /** Tries the backend's cloud TTS. Returns true if it played, false to signal fallback. */
  const speakViaBackend = useCallback(async (text: string): Promise<boolean> => {
    if (!token) return false
    try {
      const res = await fetch('/api/tutor/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ text }),
      })
      if (res.status !== 200) return false // 204 = not configured server-side
      const blob = await res.blob()
      if (stoppedRef.current) return true // stop() fired while we were fetching
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
    } catch {
      return false
    }
  }, [token])

  const speakViaBrowser = useCallback((text: string): Promise<void> => {
    return new Promise((resolve) => {
      if (!isSupported) { resolve(); return }
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.voice = pickBestVoice()
      utterance.rate = 0.88     // slightly slower for children
      utterance.pitch = 0.92    // slightly lower — a warm, older male voice
      utterance.volume = 1.0
      utterance.onend = () => resolve()
      utterance.onerror = () => resolve()
      window.speechSynthesis.speak(utterance)
    })
  }, [isSupported])

  const processQueue = useCallback(async () => {
    if (speakingRef.current || queueRef.current.length === 0) return
    speakingRef.current = true
    setIsSpeaking(true)

    const text = queueRef.current.shift()!
    // Strip tool-result prefixes (📖, 🔍, ✨, 🌿) for natural speech
    const cleanText = text.replace(/^[📖🔍✨🌿⚠️]\s*/, '').replace(/\*[^*]+\*/g, '')

    if (cleanText.trim() && !stoppedRef.current) {
      const spokeViaBackend = await speakViaBackend(cleanText)
      if (!spokeViaBackend && !stoppedRef.current) await speakViaBrowser(cleanText)
    }

    speakingRef.current = false
    setIsSpeaking(false)
    processQueue()
  }, [speakViaBackend, speakViaBrowser])

  const speak = useCallback((text: string) => {
    if (!enabled || !text.trim()) return
    stoppedRef.current = false
    queueRef.current.push(text.trim())
    processQueue()
  }, [enabled, processQueue])

  const stop = useCallback(() => {
    stoppedRef.current = true
    queueRef.current = []
    speakingRef.current = false
    setIsSpeaking(false)
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    if (isSupported) window.speechSynthesis.cancel()
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

  // Voice output works via the backend even in browsers without speechSynthesis
  return { speak, stop, toggle, isSpeaking, enabled, isSupported: true }
}
