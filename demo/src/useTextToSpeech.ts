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

// One <audio> element, reused for every turn's backend TTS playback rather
// than a fresh `new Audio()` per call — module-scoped so it survives hook
// remounts within the same tab. Confirmed on a Samsung Android tablet
// (Chrome): a brand-new media element created well after the page's initial
// unlock gesture can be silently refused by the browser's autoplay policy
// even though the page itself is otherwise "unlocked" — re-using the SAME
// element that was blessed by a real play() at login is the standard
// mitigation for that class of platform quirk (desktop Chrome and iOS
// Safari don't need it, but reusing one element costs nothing there either).
let sharedAudioEl: HTMLAudioElement | null = null
function getSharedAudioElement(): HTMLAudioElement {
  if (!sharedAudioEl) sharedAudioEl = new Audio()
  return sharedAudioEl
}

/**
 * Call synchronously inside a real click handler — e.g. the "Generate my
 * code" button — BEFORE any await. Bede's
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
    const audio = getSharedAudioElement()
    audio.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA='
    audio.volume = 0
    audio.play().then(() => { audio.pause(); audio.volume = 1.0 }).catch(() => { audio.volume = 1.0 })
  } catch {
    // best-effort
  }
}

export function useTextToSpeech(speakToken: string | null = null) {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  // `spoke` reflects whether audio actually started playing — not just
  // whether the fetch succeeded (see getSharedAudioElement's comment above
  // for why a caught play() rejection must not be reported as a success).
  // `configured` is whether some backend TTS is set up at all. `fetchedAudio`
  // distinguishes "the backend request itself failed" from "we got real
  // audio bytes back but this browser refused to play them" — see speak()
  // below for why both matter.
  const speakViaKokoro = useCallback(async (text: string): Promise<{ spoke: boolean; configured: boolean; fetchedAudio: boolean }> => {
    if (!speakToken) return { spoke: false, configured: false, fetchedAudio: false }
    const { audio: blob, configured } = await speakViaBackend(speakToken, text)
    if (!blob) return { spoke: false, configured, fetchedAudio: false }
    const url = URL.createObjectURL(blob)
    const audio = getSharedAudioElement()
    audioRef.current = audio
    let played = false
    await new Promise<void>((resolve) => {
      audio.onended = () => resolve()
      audio.onerror = () => resolve()
      audio.src = url
      audio.play()
        .then(() => { played = true })
        .catch(() => resolve()) // autoplay-blocked or decode error — playback never started
    })
    URL.revokeObjectURL(url)
    audioRef.current = null
    return { spoke: played, configured, fetchedAudio: true }
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
    // No `^` anchor: callers now batch a whole turn's segments (main text +
    // any tool cards) into one string before calling speak(), so a marker
    // emoji can appear mid-string, not just at position 0.
    const clean = text.replace(/[📖🔍✨🌿⚠️]\s*/g, '').replace(/\*[^*]+\*/g, '').trim()
    if (!clean) return
    setIsSpeaking(true)
    const { spoke, configured, fetchedAudio } = await speakViaKokoro(clean)
    // Two distinct failure classes get different treatment:
    //  - the backend request itself failed (network hiccup, nothing
    //    configured) — stay silent for this one line rather than jarringly
    //    switching to a different, lower-quality voice mid-conversation.
    //  - real audio bytes came back but this browser refused to play them
    //    (confirmed on a Samsung Android tablet: Chrome can silently block
    //    audio.play() outside a fresh gesture) — that has nothing to do
    //    with backend configuration, so browser speech is strictly better
    //    than the total silence this used to produce.
    if (!spoke && (fetchedAudio || !configured)) await speakViaBrowser(clean)
    setIsSpeaking(false)
  }, [speakViaKokoro, speakViaBrowser])

  const stop = useCallback(() => {
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
    setIsSpeaking(false)
  }, [])

  return { speak, stop, isSpeaking }
}
