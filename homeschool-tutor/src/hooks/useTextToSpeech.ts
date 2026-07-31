import { useState, useRef, useCallback, useEffect } from 'react'
import { logDebug } from './debugBus'
import i18n from '../i18n'

/**
 * Bede's spoken voice.
 *
 * Tries the backend's OpenAI TTS first (services/voice_synthesis.py on the
 * server — a warm, dedicated male monk voice). Falls back to the browser's
 * built-in speechSynthesis ONLY when TTS is genuinely unconfigured on this
 * deployment (no OPENAI_API_KEY) — a reasonable zero-config default in that
 * case. Real Bede audio that was fetched but blocked from playing by the
 * browser's own autoplay policy is deliberately NOT covered by that
 * fallback: a real report showed a browser that kept blocking audio.play()
 * swapping to the jarring, robotic browser default voice on every single
 * turn for the whole session — worse than staying silent for that one line
 * while armAutoReUnlock (below) self-heals the block on the next real tap.
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

// Spanish TTS engines almost never put "male"/"female" in a voice name, so
// the substring heuristics above find nothing to work with. These are exact
// names shipped by common engines for Spanish male voices — the same
// approach KNOWN_MALE_VOICE_NAMES takes for English, kept deliberately
// short and conservative rather than guessing at every OEM's catalogue.
const KNOWN_SPANISH_MALE_VOICE_NAMES = new Set([
  'Jorge', 'Diego', 'Juan', 'Carlos', 'Javier',
  'Microsoft Pablo - Spanish (Spain)',
  'Microsoft Raul - Spanish (Mexico)',
  'Microsoft Jorge - Spanish (Spain)',
  'Google español',
  'Google español de Estados Unidos',
])

/**
 * Pick Bede's browser-fallback voice for a given language.
 *
 * `langPrefix` was previously hardcoded to English throughout, which meant a
 * Spanish session fell back to an English voice reading Spanish text —
 * audibly wrong, and the reason this takes a parameter now. Pass the
 * session's own locale (i18n.language), not the device's.
 */
export function pickBestVoice(langPrefix = 'en'): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices()
  if (!voices.length) return null

  const inLang = (v: SpeechSynthesisVoice) => v.lang.toLowerCase().startsWith(langPrefix)

  const priorities = [
    (v: SpeechSynthesisVoice) => langPrefix === 'en' && KNOWN_MALE_VOICE_NAMES.has(v.name),
    (v: SpeechSynthesisVoice) => langPrefix === 'es' && KNOWN_SPANISH_MALE_VOICE_NAMES.has(v.name),
    (v: SpeechSynthesisVoice) => langPrefix === 'en' && v.lang.startsWith('en-GB') && isMaleVoiceName(v.name),
    (v: SpeechSynthesisVoice) => inLang(v) && isMaleVoiceName(v.name),
    // Many Android/OEM TTS engines (Samsung's included) expose English
    // voices with no gender word in the name at all — nothing above can
    // match those. Rather than falling straight through to "just take the
    // first English voice" (which might be the one explicitly labeled
    // female), prefer any voice that ISN'T explicitly female first — an
    // unlabeled voice is a better bet than a confirmed-wrong one.
    (v: SpeechSynthesisVoice) => inLang(v) && !isFemaleVoiceName(v.name),
    (v: SpeechSynthesisVoice) => inLang(v),
  ]

  for (const check of priorities) {
    const match = voices.find(check)
    if (match) return match
  }
  // English keeps its old last-resort "any voice at all" — that behaviour is
  // long-standing and safe for English text. For any other language a
  // wrong-language voice is worse than none: returning null leaves
  // utterance.voice unset, so the engine picks from utterance.lang itself
  // rather than reading Spanish aloud in an English voice.
  return langPrefix === 'en' ? (voices[0] ?? null) : null
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

export function resolveVoice(langPrefix = 'en'): Promise<SpeechSynthesisVoice | null> {
  return waitForVoicesReady().then(() => pickBestVoice(langPrefix))
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
// Short preview of a line for the debug overlay's ring buffer (100 entries,
// see debugBus.ts) — enough to tell two utterances apart, or to spot the
// SAME utterance queued twice, without flooding the buffer with full
// paragraphs. This is Bede's own generated speech, never the child's input.
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
    audio.src = SILENT_WAV_DATA_URI
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
          // Two STARTs without an ENDED between them means two clips are
          // overlapping on the shared element — that is what a doubled or
          // "reverby" Bede sounds like.
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
    } catch {
      return { spoke: false, configured: lastKnownTtsConfigured, fetchedAudio: false }
    }
  }, [token])

  const speakViaBrowser = useCallback((text: string, myGeneration: number): Promise<void> => {
    return new Promise((resolve) => {
      if (!isSupported) { resolve(); return }
      // The session's locale, not the device's — same rule the speech
      // recognition language already follows (see SocraticChat/App).
      const langPrefix = i18n.language === 'es' ? 'es' : 'en'
      resolveVoice(langPrefix).then((voice) => {
        if (generationRef.current !== myGeneration) { resolve(); return }
        const utterance = new SpeechSynthesisUtterance(text)
        // Always set, even when no voice matched: it is what lets the
        // engine choose a Spanish voice of its own rather than reading
        // Spanish text with whatever default it would otherwise use.
        utterance.lang = langPrefix === 'es' ? 'es-MX' : 'en-GB'
        if (voice) utterance.voice = voice
        utterance.rate = 0.88     // slightly slower for children
        utterance.pitch = 0.92    // slightly lower — a warm, older male voice
        utterance.volume = 1.0
        utterance.onend = () => {
          logDebug(`TTS browser fallback ENDED gen=${myGeneration}`)
          resolve()
        }
        utterance.onerror = () => {
          logDebug(`TTS browser fallback ERROR gen=${myGeneration}`)
          resolve()
        }
        // A STARTED here while a backend clip is still playing is the
        // two-different-voices-at-once case, directly.
        logDebug(`TTS browser fallback STARTED gen=${myGeneration} voice=${voice?.name ?? 'default'}`)
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

    logDebug(`TTS processQueue start gen=${myGeneration} remaining=${queueRef.current.length} text="${ttsPreview(cleanText)}"`)

    if (cleanText.trim() && !stoppedRef.current) {
      const { spoke, configured, fetchedAudio } = await speakViaBackend(cleanText, myGeneration)
      // A stop() while this call was in flight (fetching, or actually
      // mid-playback — see stop()'s own onended-firing comment) bumps
      // generationRef and resets stoppedRef.current to false again for
      // whatever NEW call comes next, so stoppedRef.current alone can no
      // longer tell a resumed-but-superseded call apart from a live one —
      // same reasoning generationRef.current already exists to fix
      // elsewhere in this file. Without this check, a call unblocked by
      // stop()'s onended fix could resume after a newer call has already
      // started, and its own unconditional speakingRef/isSpeaking reset
      // below would stomp that newer call's in-progress state — the exact
      // "two Bedes talking at once" class of bug generationRef exists to
      // prevent.
      if (generationRef.current === myGeneration) {
        // Bede's voice has no fallback to the browser's own default voice
        // when real audio bytes actually came back — real report: on a
        // browser that keeps blocking audio.play() (autoplay policy), that
        // fallback meant every single turn audibly swapped to a jarring,
        // robotic-sounding default voice, over and over, for the whole
        // session — worse than the rare total silence it was meant to
        // avoid. fetchedAudio true means Bede's real voice line exists and
        // was simply blocked from playing this once; armAutoReUnlock
        // (called from speakViaBackend's own play() rejection handler
        // above) is the actual fix for THAT — self-healing on the next
        // real tap, not swapping voices. The one case that still falls
        // back is the genuinely different one: TTS was never configured
        // at all (no OPENAI_API_KEY on this deployment), where the
        // browser's own voice is a reasonable zero-config default rather
        // than a mid-session bait-and-switch.
        if (!spoke && !configured && !stoppedRef.current) {
          logDebug(`TTS falling back to browser voice: spoke=${spoke} configured=${configured} fetchedAudio=${fetchedAudio}`)
          await speakViaBrowser(cleanText, myGeneration)
        } else if (!spoke && fetchedAudio) {
          logDebug(`TTS blocked but configured — staying silent for this line rather than falling back: fetchedAudio=${fetchedAudio}`)
        }
      }
    }

    // Same generation guard as above: stop() already reset speakingRef/
    // isSpeaking itself when it interrupted this call, and any newer call
    // manages its own state independently — a superseded call resuming
    // here has nothing left to clean up and must not re-trigger the queue
    // (stop() already cleared it) or touch state a newer call now owns.
    if (generationRef.current === myGeneration) {
      speakingRef.current = false
      setIsSpeaking(false)
      processQueue()
    }
  }, [speakViaBackend, speakViaBrowser])

  const speak = useCallback((text: string) => {
    if (!enabled || !text.trim()) return
    stoppedRef.current = false
    queueRef.current.push(text.trim())
    // The first thing to check for any "Bede said it twice" report: if this
    // line appears twice for one turn, the duplication is upstream in
    // consumeTurnStream, not in playback below.
    logDebug(`TTS speak() queued depth=${queueRef.current.length} gen=${generationRef.current} speaking=${speakingRef.current} text="${ttsPreview(text)}"`)
    processQueue()
  }, [enabled, processQueue])

  const stop = useCallback(() => {
    logDebug(`TTS stop() gen=${generationRef.current}->${generationRef.current + 1} wasSpeaking=${speakingRef.current} queued=${queueRef.current.length}`)
    stoppedRef.current = true
    generationRef.current += 1
    queueRef.current = []
    speakingRef.current = false
    setIsSpeaking(false)
    if (audioRef.current) {
      const el = audioRef.current
      el.pause()
      // pause() alone never fires 'ended'/'error' — a speakViaBackend() call
      // still awaiting one of those to resolve its playback promise (see
      // that function) would otherwise hang forever the moment stop()
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
        const el = audioRef.current
        el.pause()
        el.onended?.(new Event('ended'))
        el.onended = null
        el.onerror = null
        audioRef.current = null
      }
      if (isSupported) window.speechSynthesis.cancel()
    }
  }, [isSupported])

  // Voice output works via the backend even in browsers without speechSynthesis
  return { speak, stop, toggle, isSpeaking, enabled, isSupported: true }
}
