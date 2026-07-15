import { useState, useRef, useCallback, useEffect } from 'react'

/**
 * Bede's spoken voice.
 *
 * Tries the backend's OpenAI TTS first (services/voice_synthesis.py on the
 * server — a warm, dedicated male monk voice). Falls back to the browser's
 * built-in speechSynthesis when the backend isn't configured or the request
 * fails, so voice output never breaks the session.
 *
 * Bede's persona is historically male (the Venerable Bede) — voice selection
 * in both paths prefers a male voice, never a gender-ambiguous or female one.
 */

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
// remounts within the same tab, same as lastKnownTtsConfigured below.
// Confirmed on a Samsung Android tablet (Chrome): a brand-new media element
// created well after the page's initial unlock gesture can be silently
// refused by the browser's autoplay policy even though the page itself is
// otherwise "unlocked" — re-using the SAME element that was blessed by a
// real play() at login is the standard mitigation for that class of
// platform quirk (desktop Chrome and iOS Safari don't need it, but reusing
// one element costs nothing there either).
let sharedAudioEl: HTMLAudioElement | null = null
function getSharedAudioElement(): HTMLAudioElement {
  if (!sharedAudioEl) sharedAudioEl = new Audio()
  return sharedAudioEl
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
    const audio = getSharedAudioElement()
    audio.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA='
    audio.volume = 0
    audio.play().then(() => { audio.pause(); audio.volume = 1.0 }).catch(() => { audio.volume = 1.0 })
  } catch {
    // best-effort
  }
}

// Once a real response confirms the backend has TTS configured, remember it
// for the rest of the tab session. A network-level exception in
// speakViaBackend below (timeout, connection reset, a transient hiccup) says
// nothing about whether TTS is configured — it's a failure of that one call,
// not a fact about the deployment. Treating it as "unconfigured" was the
// actual cause of voice audibly flipping from the backend voice to the
// browser's robotic fallback partway through a session: one hiccupy request
// lied about the deployment being unconfigured even though every other call
// that session succeeded fine. Module-scoped (not a ref) since it should
// survive remounts of the hook within the same tab, same as resolvedVoice above.
let lastKnownTtsConfigured = false

export function useTextToSpeech(token: string | null = null, initialEnabled: boolean = true) {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [enabled, setEnabled] = useState(initialEnabled)
  const [isSupported] = useState(() => 'speechSynthesis' in window)
  const queueRef = useRef<string[]>([])
  const speakingRef = useRef(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const stoppedRef = useRef(false)
  // Bumped by stop() only (never by speak() — a second queued item within
  // the same still-active turn must NOT invalidate an earlier one still
  // mid-flight; see queueRef above). Each processQueue() pass captures the
  // current value once and threads it through as myGeneration. Without
  // this, a slow /api/tutor/speak response from an OLD turn could resolve
  // AFTER a NEWER turn's own stop()-then-speak() sequence had already
  // reset stoppedRef back to false, sail past that check, and start
  // playing on top of (and clobbering audioRef for) the new turn's own
  // audio — two Bedes talking at once. This is the actual bug a plain
  // boolean can't catch: stoppedRef only remembers "was stop() the LAST
  // thing that happened," not "is this SPECIFIC in-flight call still the
  // one that should be allowed to play."
  const generationRef = useRef(0)

  /** Tries the backend's cloud TTS. `spoke` is whether audio actually
   *  started playing — NOT just whether the fetch succeeded; a caught
   *  play() rejection or an 'error' event used to be reported as spoke:
   *  true unconditionally, which permanently masked real playback failures
   *  (see the module comment on getSharedAudioElement). `configured` (from
   *  the X-TTS-Configured header) is whether SOME backend TTS is set up at
   *  all. `fetchedAudio` distinguishes "the /tutor/speak request itself
   *  failed" from "we got real audio bytes back but this browser refused
   *  to play them" — see processQueue() below for why the caller needs all
   *  three, not just whether this one call succeeded. */
  const speakViaBackend = useCallback(async (text: string, myGeneration: number): Promise<{ spoke: boolean; configured: boolean; fetchedAudio: boolean }> => {
    if (!token) return { spoke: false, configured: false, fetchedAudio: false }
    try {
      const res = await fetch('/api/tutor/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ text }),
      })
      const configured = res.headers.get('X-TTS-Configured') === 'True'
      lastKnownTtsConfigured = configured
      if (res.status !== 200) return { spoke: false, configured, fetchedAudio: false } // 204 = synthesis unavailable
      const blob = await res.blob()
      // A newer stop() has superseded this call while we were fetching —
      // see generationRef's own comment for why stoppedRef alone can't
      // catch this. Nothing between here and audio.play() below awaits
      // anything, so one check here is sufficient — there's no gap left
      // for another stop()/speak() to interleave into.
      if (stoppedRef.current || generationRef.current !== myGeneration) return { spoke: true, configured, fetchedAudio: true }
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
      if (generationRef.current === myGeneration) audioRef.current = null
      return { spoke: played, configured, fetchedAudio: true }
    } catch {
      return { spoke: false, configured: lastKnownTtsConfigured, fetchedAudio: false }
    }
  }, [token])

  const speakViaBrowser = useCallback((text: string, myGeneration: number): Promise<void> => {
    return new Promise((resolve) => {
      if (!isSupported) { resolve(); return }
      resolveVoice().then((voice) => {
        if (generationRef.current !== myGeneration) { resolve(); return }
        const utterance = new SpeechSynthesisUtterance(text)
        if (voice) utterance.voice = voice
        utterance.rate = 0.88     // slightly slower for children
        utterance.pitch = 0.92    // slightly lower — a warm, older male voice
        utterance.volume = 1.0
        utterance.onend = () => resolve()
        utterance.onerror = () => resolve()
        window.speechSynthesis.speak(utterance)
      })
    })
  }, [isSupported])

  const processQueue = useCallback(async () => {
    if (speakingRef.current || queueRef.current.length === 0) return
    speakingRef.current = true
    setIsSpeaking(true)

    const text = queueRef.current.shift()!
    // Strip tool-result prefixes (📖, 🔍, ✨, 🌿) for natural speech. No `^`
    // anchor: callers now batch a whole turn's segments (main text + any
    // tool cards) into one string before calling speak(), so a marker
    // emoji can appear mid-string, not just at position 0.
    const cleanText = text.replace(/[📖🔍✨🌿⚠️]\s*/g, '').replace(/\*[^*]+\*/g, '')
    const myGeneration = generationRef.current

    if (cleanText.trim() && !stoppedRef.current) {
      const { spoke, configured, fetchedAudio } = await speakViaBackend(cleanText, myGeneration)
      // Two distinct failure classes get different treatment:
      //  - the /tutor/speak request itself failed (network hiccup, backend
      //    error, nothing configured) — stay silent for this one line
      //    rather than jarringly switching to a different, lower-quality
      //    voice mid-conversation (the original rule this fallback follows).
      //  - real audio bytes came back but this browser refused to play
      //    them (confirmed on a Samsung Android tablet: Chrome can
      //    silently block audio.play() outside a fresh gesture) — that has
      //    nothing to do with backend configuration, so browser speech is
      //    strictly better than the total silence this used to produce.
      if (!spoke && (fetchedAudio || !configured) && !stoppedRef.current) await speakViaBrowser(cleanText, myGeneration)
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
    generationRef.current += 1
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

  // Cleans up on unmount too, not just when a caller explicitly calls
  // stop() — navigating away from a screen that's mid-speech (e.g. this
  // component unmounting because the app switched views) must not leave
  // its audio playing in the background indefinitely, which the original
  // version only did for the speechSynthesis fallback, never for the
  // backend-audio path (audioRef).
  useEffect(() => {
    return () => {
      generationRef.current += 1
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current = null
      }
      if (isSupported) window.speechSynthesis.cancel()
    }
  }, [isSupported])

  // Voice output works via the backend even in browsers without speechSynthesis
  return { speak, stop, toggle, isSpeaking, enabled, isSupported: true }
}
