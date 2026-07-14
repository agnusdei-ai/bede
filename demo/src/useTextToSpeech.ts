import { useState, useRef, useCallback, useEffect } from 'react'
import { speakViaBackend } from './api'

// Tries the backend's self-hosted Kokoro voice first (same one production
// uses) — both demo tiers always supply a real token, since both are
// backend-mediated. Falls back to browser speech if the backend request
// fails or isn't configured. Bede's persona is historically male — voice
// selection prefers a male voice, never gender-ambiguous or female.

// Confirmed-female voices that carry no gender word in their name at all
// — the exact case priority 4 below ("not explicitly labeled female") was
// meant to guard against, and exactly where that heuristic used to fail.
// "Google US English" is Chrome's own default English voice on desktop
// (and often the ONLY English voice available at all on Linux/ChromeOS
// Chrome installs with no extra OS voices) — a name that reads as
// gender-neutral but is an audibly female voice, so it used to sail
// through priority 4's "not explicitly female" check as a false "safe
// pick." This is the confirmed, reported cause of voice output reverting
// to a woman's voice specifically on Chrome even though every prior
// priority was already trying not to pick one.
const KNOWN_FEMALE_VOICE_NAMES = new Set([
  'Google US English',
  'Google UK English Female',
  'Samantha', 'Victoria', 'Karen', 'Moira', 'Tessa', 'Fiona', 'Kate',
  'Microsoft Zira - English (United States)',
  'Microsoft Jenny - English (United States)',
  'Microsoft Aria - English (United States)',
  'Microsoft Hazel - English (United Kingdom)',
  'Microsoft Susan - English (United Kingdom)',
])

// A name containing "female" also contains "male" as a literal substring
// ("fe-MALE") — naively checking name.includes('male') alone matches female
// voices too. Every male check below excludes isFemale() explicitly to
// avoid this exact bug (a real, confirmed cause of picking a female voice
// on at least one Android/Chrome device that labels voices "...Female").
function isFemaleVoiceName(name: string): boolean {
  return name.toLowerCase().includes('female') || KNOWN_FEMALE_VOICE_NAMES.has(name)
}
function isMaleVoiceName(name: string): boolean {
  return name.toLowerCase().includes('male') && !isFemaleVoiceName(name)
}

// Exact names confirmed male across common desktop/mobile TTS engines that
// don't label voices "male"/"female" in the first place (Safari/macOS/iOS
// give plain first names; Windows/Edge give "Microsoft <Name> - ...").
// Checked before any substring heuristics since exact names are unambiguous.
//
// Deliberately excludes "Fred" — a real, confirmed-bad pick reported on
// Safari/macOS/iOS: it's a decades-old novelty voice (the classic
// "Stephen Hawking"/"Speak & Spell" robotic sound), not a lower-quality-
// but-acceptable one like the others here. Lumping it into this same
// top-priority tier meant Array.find() below picked whichever name
// happened to come first in that platform's own getVoices() ordering —
// unspecified and not something this code controls — so the SAME device
// could resolve to Fred in one tab/session and Daniel or Alex (both
// genuinely good, natural-sounding voices on the exact same platform) in
// another. Every other name here is a reasonable voice; Fred never is.
const KNOWN_MALE_VOICE_NAMES = new Set([
  'Daniel', 'Oliver', 'Arthur', 'Alex', 'Aaron', 'Gordon',
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
  // Unlike homeschool-tutor's version of this hook, speak() here has no
  // queue at all — every call is a fresh, standalone utterance that fully
  // supersedes whatever came before it (callers already batch a whole
  // turn into one joined string before calling speak() once). So this is
  // bumped on EVERY speak() call, not just stop(): the moment a new
  // speak() starts, any earlier call's still-in-flight backend request
  // must never be allowed to start playing once it finally resolves —
  // without this, a slow response from an OLD turn could land after a
  // NEWER turn's own speak() had already started, and since nothing else
  // here tracked that, it would just play on top of it — two Bedes
  // talking at once.
  const generationRef = useRef(0)

  // Returns whether it actually played AND whether some backend TTS is
  // configured at all — see speak() below for why both matter.
  const speakViaKokoro = useCallback(async (text: string, myGeneration: number): Promise<{ spoke: boolean; configured: boolean }> => {
    if (!speakToken) return { spoke: false, configured: false }
    const { audio: blob, configured } = await speakViaBackend(speakToken, text)
    if (!blob) return { spoke: false, configured }
    // A newer speak() or stop() has superseded this call while we were
    // waiting on the network — see generationRef's own comment.
    if (generationRef.current !== myGeneration) return { spoke: true, configured }
    const url = URL.createObjectURL(blob)
    await new Promise<void>((resolve) => {
      const audio = new Audio(url)
      audioRef.current = audio
      audio.onended = () => resolve()
      audio.onerror = () => resolve()
      audio.play().catch(() => resolve())
    })
    URL.revokeObjectURL(url)
    if (generationRef.current === myGeneration) audioRef.current = null
    return { spoke: true, configured }
  }, [speakToken])

  const speakViaBrowser = useCallback((text: string, myGeneration: number): Promise<void> => {
    return new Promise((resolve) => {
      if (!('speechSynthesis' in window)) { resolve(); return }
      resolveVoice().then((voice) => {
        if (generationRef.current !== myGeneration) { resolve(); return }
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

  const stop = useCallback(() => {
    generationRef.current += 1
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
    setIsSpeaking(false)
  }, [])

  const speak = useCallback(async (text: string) => {
    // No `^` anchor: callers now batch a whole turn's segments (main text +
    // any tool cards) into one string before calling speak(), so a marker
    // emoji can appear mid-string, not just at position 0.
    const clean = text.replace(/[📖🔍✨🌿⚠️]\s*/g, '').replace(/\*[^*]+\*/g, '').trim()
    if (!clean) return
    generationRef.current += 1
    const myGeneration = generationRef.current
    setIsSpeaking(true)
    const { spoke, configured } = await speakViaKokoro(clean, myGeneration)
    // Only the browser's own voice is a reasonable fallback when NOTHING is
    // configured server-side — a configured backend that failed this one
    // call stays silent rather than jarringly switching to a different,
    // lower-quality voice mid-conversation.
    if (!spoke && !configured && generationRef.current === myGeneration) await speakViaBrowser(clean, myGeneration)
    if (generationRef.current === myGeneration) setIsSpeaking(false)
  }, [speakViaKokoro, speakViaBrowser])

  // Unmount cleanup — a screen switch (e.g. main chat -> Mastery preview)
  // unmounts this hook's owning component; without this, any audio that
  // was still playing at that moment keeps playing in the background with
  // nothing left able to stop it, since stop() is a function on an
  // instance that no longer exists once unmounted.
  useEffect(() => {
    return () => {
      generationRef.current += 1
      if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
      if ('speechSynthesis' in window) window.speechSynthesis.cancel()
    }
  }, [])

  return { speak, stop, isSpeaking }
}
