import { useState, useRef, useCallback, useEffect } from 'react'
import { speakViaBackend } from './api'
import { logDebug } from './debugBus'

// Tries the backend's OpenAI TTS voice first (same one production uses) —
// both demo tiers always supply a real token, since both are
// backend-mediated. Falls back to browser speech ONLY when TTS is
// genuinely unconfigured on this deployment — a reasonable zero-config
// default in that case. Real Bede audio that was fetched but blocked from
// playing by the browser's own autoplay policy deliberately does NOT fall
// back: a real report showed a browser that kept blocking audio.play()
// swapping to the jarring, robotic browser default voice on every single
// turn for the whole session — worse than staying silent for that one
// line while armAutoReUnlock (below) self-heals the block on the next
// real tap. Bede's persona is historically male — voice selection prefers
// a male voice, never gender-ambiguous or female.

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
export function isFemaleVoiceName(name: string): boolean {
  return name.toLowerCase().includes('female') || KNOWN_FEMALE_VOICE_NAMES.has(name)
}
export function isMaleVoiceName(name: string): boolean {
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

export function pickBestVoice(): SpeechSynthesisVoice | null {
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
// device.
//
// Only READINESS is cached module-scoped (so the whole tab pays the async
// wait at most once) — never the SpeechSynthesisVoice object itself.
// Microsoft Edge fires 'voiceschanged' MORE THAN ONCE per session as it
// lazy-loads its online/neural voices well after the initial local list,
// and each firing can reissue brand-new SpeechSynthesisVoice object
// instances for what is logically the same voice. A voice object resolved
// once and reused on every later utterance goes stale the moment that
// happens: Edge doesn't error, it silently ignores the now-unrecognized
// object and falls back to its OWN current default voice instead — a
// female neural voice on Windows/Edge. This is the confirmed mechanism
// behind Bede's voice reverting to a woman's specifically on Edge, several
// turns into a session, even though every priority in pickBestVoice()
// above was already trying not to pick one. Calling pickBestVoice() fresh
// on every speak() (instead of returning a long-cached object) means
// there's never a stale reference left around to go bad.
let voicesReadyPromise: Promise<void> | null = null

function waitForVoicesReady(): Promise<void> {
  if (voicesReadyPromise) return voicesReadyPromise

  voicesReadyPromise = new Promise((resolve) => {
    if (window.speechSynthesis.getVoices().length) { resolve(); return }

    const handler = () => {
      if (window.speechSynthesis.getVoices().length) {
        window.speechSynthesis.removeEventListener('voiceschanged', handler)
        clearTimeout(timeoutId)
        resolve()
      }
    }
    window.speechSynthesis.addEventListener('voiceschanged', handler)

    // Some engines never fire voiceschanged at all — don't wait forever.
    const timeoutId = setTimeout(() => {
      window.speechSynthesis.removeEventListener('voiceschanged', handler)
      resolve()
    }, 1000)
  })

  return voicesReadyPromise
}

export function resolveVoice(): Promise<SpeechSynthesisVoice | null> {
  return waitForVoicesReady().then(() => pickBestVoice())
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
// Short preview of a line for the debug overlay's ring buffer — enough to
// tell two utterances apart, or to spot the SAME one spoken twice, without
// flooding the buffer. Bede's own generated speech, never the child's input.
function ttsPreview(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > 42 ? `${flat.slice(0, 42)}…` : flat
}

let sharedAudioEl: HTMLAudioElement | null = null
function getSharedAudioElement(): HTMLAudioElement {
  if (!sharedAudioEl) sharedAudioEl = new Audio()
  return sharedAudioEl
}

const SILENT_WAV_DATA_URI = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA='

// Real report: the login-time unlockSpeechForSession() call below is
// supposed to permanently bless sharedAudioEl for the rest of the tab
// (once ANY play() succeeds on an element, later programmatic play()
// calls on that SAME element are allowed indefinitely, gesture or not —
// the whole reason a shared singleton element exists at all). In
// practice a family reported audio.play() being rejected as
// autoplay-blocked on EVERY subsequent turn, not just an occasional one —
// meaning the initial unlock itself wasn't taking, or wasn't durable,
// on their device/browser. Rather than staying permanently blocked for
// the rest of the session once that happens, arm a one-shot retry that
// re-primes the same element on the very next genuine user gesture
// anywhere on the page (a subject switch, a mic tap, anything) — cheap
// and self-healing, instead of requiring a full reload to recover.
let reUnlockArmed = false
function armAutoReUnlock() {
  if (reUnlockArmed) return
  reUnlockArmed = true
  const retry = () => {
    document.removeEventListener('pointerdown', retry, true)
    reUnlockArmed = false
    try {
      const audio = getSharedAudioElement()
      const wasPlaying = !audio.paused
      if (wasPlaying) return // don't stomp audio that's actually mid-playback right now
      audio.src = SILENT_WAV_DATA_URI
      audio.volume = 0
      audio.play().then(() => { audio.pause(); audio.volume = 1.0 }).catch(() => { audio.volume = 1.0 })
    } catch {
      // best-effort — this is a background recovery attempt, never worth surfacing
    }
  }
  document.addEventListener('pointerdown', retry, true)
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
    audio.src = SILENT_WAV_DATA_URI
    audio.volume = 0
    audio.play().then(() => { audio.pause(); audio.volume = 1.0 }).catch(() => { audio.volume = 1.0 })
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

  // `spoke` reflects whether audio actually started playing — not just
  // whether the fetch succeeded (see getSharedAudioElement's comment above
  // for why a caught play() rejection must not be reported as a success).
  // `configured` is whether some backend TTS is set up at all. `fetchedAudio`
  // distinguishes "the backend request itself failed" from "we got real
  // audio bytes back but this browser refused to play them" — see speak()
  // below for why all three matter. Named distinctly from api.ts's imported
  // speakViaBackend (fetch-only): this wraps that call with actual playback
  // + generation tracking on top.
  const playBackendVoice = useCallback(async (text: string, myGeneration: number): Promise<{ spoke: boolean; configured: boolean; fetchedAudio: boolean }> => {
    if (!speakToken) return { spoke: false, configured: false, fetchedAudio: false }
    const { audio: blob, configured } = await speakViaBackend(speakToken, text)
    if (!blob) return { spoke: false, configured, fetchedAudio: false }
    // A newer speak() or stop() has superseded this call while we were
    // waiting on the network — see generationRef's own comment.
    if (generationRef.current !== myGeneration) return { spoke: true, configured, fetchedAudio: true }
    const url = URL.createObjectURL(blob)
    const audio = getSharedAudioElement()
    audioRef.current = audio
    let played = false
    await new Promise<void>((resolve) => {
      audio.onended = () => {
        logDebug(`TTS backend playback ENDED gen=${myGeneration}`)
        resolve()
      }
      audio.onerror = () => {
        logDebug(`TTS backend playback ERROR gen=${myGeneration}`)
        resolve()
      }
      audio.src = url
      audio.play()
        // Two STARTs with no ENDED between them means two clips overlapping
        // on the shared element — a doubled/"reverby" Bede.
        .then(() => { played = true; logDebug(`TTS backend playback STARTED gen=${myGeneration}`) })
        .catch((err) => {
          // autoplay-blocked or decode error — playback never started.
          // Arm a self-healing retry for the next real tap rather than
          // staying silently blocked for the rest of the session — see
          // armAutoReUnlock's own comment.
          logDebug(`backend TTS audio.play() rejected: ${err instanceof Error ? err.message : String(err)}`)
          armAutoReUnlock()
          resolve()
        })
    })
    URL.revokeObjectURL(url)
    if (generationRef.current === myGeneration) audioRef.current = null
    return { spoke: played, configured, fetchedAudio: true }
  }, [speakToken])

  const speakViaBrowser = useCallback((text: string, myGeneration: number): Promise<void> => {
    return new Promise((resolve) => {
      if (!('speechSynthesis' in window)) { resolve(); return }
      resolveVoice().then((voice) => {
        if (generationRef.current !== myGeneration) { resolve(); return }
        // A STARTED here while a backend clip is still playing is the
        // two-different-voices-at-once case, directly.
        logDebug(`TTS browser fallback STARTED gen=${myGeneration} voice=${voice?.name ?? 'default'}`)
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
    if (audioRef.current) {
      const el = audioRef.current
      el.pause()
      // pause() alone never fires 'ended'/'error' — a playBackendVoice()
      // call still awaiting one of those to resolve its playback promise
      // (see that function) would otherwise hang forever the moment stop()
      // interrupts mid-playback, which is exactly what a mic barge-in does
      // every time it cuts off Bede's backend-voice audio. Firing onended
      // manually resolves it the same way a natural end-of-playback would,
      // then detaches both handlers so the next reuse of this shared
      // element starts clean rather than possibly firing into a stale
      // closure from the call being abandoned here.
      el.onended?.(new Event('ended'))
      el.onended = null
      el.onerror = null
      audioRef.current = null
    }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel()
    logDebug(`TTS stop() gen=${generationRef.current}`)
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
    // First thing to check for any "Bede said it twice" report: this line
    // appearing twice for one turn means the duplication is upstream in the
    // turn-stream consumer, not in playback below.
    logDebug(`TTS speak() gen=${myGeneration} text="${ttsPreview(clean)}"`)
    setIsSpeaking(true)
    const { spoke, configured, fetchedAudio } = await playBackendVoice(clean, myGeneration)
    // Bede's voice has no fallback to the browser's own default voice when
    // real audio bytes actually came back — real report: on a browser that
    // keeps blocking audio.play() (autoplay policy), that fallback meant
    // every single turn audibly swapped to a jarring, robotic-sounding
    // default voice, over and over, for the whole session — worse than the
    // rare total silence it was meant to avoid. fetchedAudio true means
    // Bede's real voice line exists and was simply blocked from playing
    // this once; armAutoReUnlock (called from playBackendVoice's own
    // play() rejection handler above) is the actual fix for THAT —
    // self-healing on the next real tap, not swapping voices. The one case
    // that still falls back is the genuinely different one: TTS was never
    // configured at all, where the browser's own voice is a reasonable
    // zero-config default rather than a mid-session bait-and-switch.
    if (generationRef.current === myGeneration) {
      if (!spoke && !configured) {
        logDebug(`TTS falling back to browser voice: spoke=${spoke} configured=${configured} fetchedAudio=${fetchedAudio}`)
        await speakViaBrowser(clean, myGeneration)
      } else if (!spoke && fetchedAudio) {
        logDebug(`TTS blocked but configured — staying silent for this line rather than falling back: fetchedAudio=${fetchedAudio}`)
      }
    }
    if (generationRef.current === myGeneration) setIsSpeaking(false)
  }, [playBackendVoice, speakViaBrowser])

  // Unmount cleanup — a screen switch (e.g. main chat -> Mastery preview)
  // unmounts this hook's owning component; without this, any audio that
  // was still playing at that moment keeps playing in the background with
  // nothing left able to stop it, since stop() is a function on an
  // instance that no longer exists once unmounted.
  useEffect(() => {
    return () => {
      generationRef.current += 1
      if (audioRef.current) {
        const el = audioRef.current
        el.pause()
        el.onended?.(new Event('ended'))
        el.onended = null
        el.onerror = null
        audioRef.current = null
      }
      if ('speechSynthesis' in window) window.speechSynthesis.cancel()
    }
  }, [])

  return { speak, stop, isSpeaking }
}
