import { useState, useRef, useCallback, useEffect } from 'react'
import { logDebug } from './debugBus'

/**
 * Bede's spoken voice, and the only voice anything in this app speaks with:
 * the chat, Sound Time, Number Time and Map Practice (docs/DECISIONS.md
 * entry 46).
 *
 * Every line goes to the server's /tutor/speak. In installed Bede that is
 * Bede's own Piper voice on the family's computer; cloud speech is never
 * used there. When no voice is set up, or Bede's voice is not answering
 * (asked once, then again after VOICE_RECHECK_MS), no line is requested at
 * all. When a line fails or times out, or the browser blocks playback, the
 * line is SILENT and everything on screen carries on. The browser's own
 * speechSynthesis is never used: it is not Bede's voice, and a child
 * hearing a different voice is worse than a line that is shown but not
 * spoken. (`bedesVoiceOnly.test.ts` fails if anything speaks through it.)
 * Nothing here touches a screen reader, which reads the page on its own
 * terms.
 */

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
 * refuse <audio>.play() unless it was unlocked
 * by a genuine, synchronous user gesture first. This "spends" that gesture
 * on a silent no-op so the later automatic speech isn't blocked.
 */
export function unlockSpeechForSession() {
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

/** How long one line may take to come back from /tutor/speak before it is
 *  given up and left silent. Longer than any real line takes. */
export const SPEAK_REQUEST_TIMEOUT_MS = 20_000

// Whether Bede's voice can speak right now (GET /tutor/voice: a voice is set
// up and answering in this session's language). A "yes" is remembered for
// the sign-in. A "no" is remembered for VOICE_RECHECK_MS only, so a voice that
// comes back is picked up within a lesson, while an install with no voice
// still sends no line to /tutor/speak. A failed ASK is not remembered at
// all: it says nothing about the voice, so the next line asks again (and is
// silent meanwhile).
let voiceGate: { token: string; at: number; speaks: Promise<boolean> } | null = null

/** How long a "Bede's voice can't speak right now" answer is trusted. */
export const VOICE_RECHECK_MS = 60_000

/** Test seam: forget the remembered answer. */
export function resetVoiceGateForTests() { voiceGate = null }

async function askWhetherVoiceSpeaks(token: string): Promise<boolean> {
  try {
    const res = await fetch('/api/tutor/voice', { headers: { Authorization: `Bearer ${token}` } })
    if (!res.ok) throw new Error(`status ${res.status}`)
    const body = await res.json()
    return body?.configured === true && body?.available === true
  } catch (err) {
    if (voiceGate?.token === token) voiceGate = null
    logDebug(`TTS voice status unknown, staying silent for now: ${err instanceof Error ? err.message : String(err)}`)
    return false
  }
}

/** Whether Bede's voice can speak for this sign-in. Shared by the hook and
 *  the lesson screen, so both read one answer from one request. */
export function voiceSpeaks(token: string): Promise<boolean> {
  const now = Date.now()
  if (!voiceGate || voiceGate.token !== token) {
    voiceGate = { token, at: now, speaks: askWhetherVoiceSpeaks(token) }
    return voiceGate.speaks
  }
  const gate = voiceGate
  return gate.speaks.then((speaks) => {
    if (speaks || Date.now() - gate.at < VOICE_RECHECK_MS || voiceGate !== gate) return voiceGate?.speaks ?? speaks
    voiceGate = { token, at: Date.now(), speaks: askWhetherVoiceSpeaks(token) }
    return voiceGate.speaks
  })
}

/**
 * Drops the tool-card marker emoji (📖 🔍 ✨ 🌿 ⚠️) and *stage directions*
 * from a line before it is spoken.
 *
 * The markers are matched as whole characters (`u` flag, alternation). A
 * character class without `u` matched each emoji's two UTF-16 halves
 * separately, so any other emoji sharing a first half, such as 😊, lost it
 * and reached the voice as a lone, unreadable surrogate.
 */
export function stripSpokenMarkers(text: string): string {
  return text.replace(/(?:📖|🔍|✨|🌿|⚠\uFE0F?)\s*/gu, '').replace(/\*[^*]+\*/g, '')
}

export function useTextToSpeech(token: string | null = null, initialEnabled: boolean = true) {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [enabled, setEnabled] = useState(initialEnabled)
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
    // A provider that never answers must not leave Bede "speaking" forever:
    // isSpeaking holds the mic back in continuous voice mode. The line is
    // given up and stays silent; the lesson goes on.
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), SPEAK_REQUEST_TIMEOUT_MS)
    try {
      const res = await fetch('/api/tutor/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ text }),
        signal: controller.signal,
      })
      const configured = res.headers.get('X-TTS-Configured') === 'True'
      lastKnownTtsConfigured = configured
      if (res.status !== 200) return { spoke: false, configured, fetchedAudio: false } // 204 = synthesis unavailable
      const blob = await res.blob()
      clearTimeout(timer)
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
    } finally {
      clearTimeout(timer)
    }
  }, [token])

  const processQueue = useCallback(async () => {
    if (speakingRef.current || queueRef.current.length === 0) return
    speakingRef.current = true
    setIsSpeaking(true)

    const text = queueRef.current.shift()!
    // Strip tool-result prefixes (📖, 🔍, ✨, 🌿) for natural speech. No `^`
    // anchor: callers now batch a whole turn's segments (main text + any
    // tool cards) into one string before calling speak(), so a marker
    // emoji can appear mid-string, not just at position 0.
    const cleanText = stripSpokenMarkers(text)
    const myGeneration = generationRef.current

    logDebug(`TTS processQueue start gen=${myGeneration} remaining=${queueRef.current.length} text="${ttsPreview(cleanText)}"`)

    // No voice configured, or the voice switched off here: the line is
    // shown, not spoken, and no speech request is made.
    const allowed = !!token && cleanText.trim() !== '' && !stoppedRef.current && await voiceSpeaks(token)
    if (!allowed && generationRef.current === myGeneration && cleanText.trim()) {
      logDebug('TTS voice not available on this deployment: line shown, not spoken')
    }

    if (allowed && !stoppedRef.current && generationRef.current === myGeneration) {
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
        // A line that did not play stays silent. Bede never switches to the
        // browser's own voice, whatever the reason: no voice configured on
        // this deployment, a failed line, or a browser that blocked
        // playback (armAutoReUnlock self-heals that on the next real tap).
        if (!spoke) {
          logDebug(`TTS line not spoken, staying silent: configured=${configured} fetchedAudio=${fetchedAudio}`)
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
  }, [speakViaBackend, token])

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
  }, [])

  const toggle = useCallback(() => {
    if (enabled) stop()
    setEnabled((v) => !v)
  }, [enabled, stop])

  // Cleans up on unmount too, not just when a caller explicitly calls
  // stop() — navigating away from a screen that's mid-speech (e.g. this
  // component unmounting because the app switched views) must not leave
  // its audio playing in the background indefinitely, which the original
  // version only did for the old browser-voice path, never for the
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
    }
  }, [])

  // Bede's voice is the server's, so every browser that can play audio supports it.
  return { speak, stop, toggle, isSpeaking, enabled, isSupported: true }
}
