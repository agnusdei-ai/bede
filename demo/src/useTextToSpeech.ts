import { useState, useRef, useCallback, useEffect } from 'react'
import { speakViaBackend } from './api'
import { logDebug } from './debugBus'

// Bede's spoken voice in the demo, and the only voice the demo speaks with:
// the chat and Number Time (docs/DECISIONS.md, the beta voice decision).
// Every line goes to the server's /tutor/speak. When a line fails, times
// out, or the browser blocks playback, the line is SILENT and the visitor
// carries on reading: the browser's own speechSynthesis is never used, since
// it is not Bede's voice. Nothing here touches a screen reader.

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
  try {
    const audio = getSharedAudioElement()
    audio.src = SILENT_WAV_DATA_URI
    audio.volume = 0
    audio.play().then(() => { audio.pause(); audio.volume = 1.0 }).catch(() => { audio.volume = 1.0 })
  } catch {
    // best-effort
  }
}

/**
 * Drop the tool-card marker emoji and *stage directions* before a line is
 * spoken. The markers are alternatives, not a character class, and the regex
 * carries the `u` flag: without it a class like `[📖🔍]` is a set of UTF-16
 * halves, so it also matched half of any other emoji (😊) and sent a lone
 * surrogate to the voice. Mirrors the app's helper of the same name;
 * `useTextToSpeech.markers.test.ts` asserts the two agree.
 */
export function stripSpokenMarkers(text: string): string {
  return text.replace(/(?:📖|🔍|✨|🌿|⚠\uFE0F?)\s*/gu, '').replace(/\*[^*]+\*/g, '')
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
    logDebug(`TTS stop() gen=${generationRef.current}`)
    setIsSpeaking(false)
  }, [])

  const speak = useCallback(async (text: string) => {
    // No `^` anchor: callers now batch a whole turn's segments (main text +
    // any tool cards) into one string before calling speak(), so a marker
    // emoji can appear mid-string, not just at position 0.
    const clean = stripSpokenMarkers(text).trim()
    if (!clean) return
    generationRef.current += 1
    const myGeneration = generationRef.current
    // First thing to check for any "Bede said it twice" report: this line
    // appearing twice for one turn means the duplication is upstream in the
    // turn-stream consumer, not in playback below.
    logDebug(`TTS speak() gen=${myGeneration} text="${ttsPreview(clean)}"`)
    setIsSpeaking(true)
    const { spoke, configured, fetchedAudio } = await playBackendVoice(clean, myGeneration)
    // A line that did not play stays silent, whatever the reason: no voice
    // configured, a failed or timed-out line, or a browser that blocked
    // playback (armAutoReUnlock self-heals that on the next real tap). Bede
    // never switches to the browser's own voice.
    if (generationRef.current === myGeneration && !spoke) {
      logDebug(`TTS line not spoken, staying silent: configured=${configured} fetchedAudio=${fetchedAudio}`)
    }
    if (generationRef.current === myGeneration) setIsSpeaking(false)
  }, [playBackendVoice])

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
    }
  }, [])

  return { speak, stop, isSpeaking }
}
