/**
 * WebKit's AudioSession API (iOS/iPadOS 17+ Safari) exposes
 * `navigator.audioSession.type`, letting a page explicitly pin which audio
 * session category it's in. Not yet in TypeScript's DOM lib, and
 * unsupported everywhere except WebKit — every function here is a
 * best-effort no-op elsewhere (Android Chrome, desktop, older iOS), guarded
 * by a feature check plus try/catch.
 *
 * Why this exists: opening ANY getUserMedia() audio stream — the mic
 * button's own recorder fallback/prewarm (useVoiceRecorder.ts), or native
 * SpeechRecognition's own internal capture (useSpeechRecognition.ts), which
 * uses getUserMedia under the hood regardless of whether this app calls it
 * directly — switches WebKit's audio session into a mode that can route
 * subsequent Bede TTS playback through the device's built-in earpiece
 * speaker instead of whatever output a family actually selected (a
 * Bluetooth speaker, wired headphones, AirPlay). Reported as Bede's voice
 * "switching to browser embedded [audio] instead of mobile audio" tied
 * specifically to using the press-to-talk mic mid-lesson, and not settling
 * back onto one output for the rest of the session — each subsequent mic
 * press re-triggers the same category flip. Explicitly pinning the session
 * back to 'playback' the moment mic capture ends (see
 * useHybridVoiceInput.ts's mode-driven effect) tells WebKit to keep routing
 * audio to whatever device is actually selected, rather than leaving the
 * session in whatever ambiguous state the mic capture left it in.
 */
interface WebKitAudioSession {
  type: 'auto' | 'playback' | 'transient' | 'transient-solo' | 'ambient' | 'play-and-record'
}

function getAudioSession(): WebKitAudioSession | null {
  return (navigator as Navigator & { audioSession?: WebKitAudioSession }).audioSession ?? null
}

/** Call while the mic is actively capturing (native recognition or the raw-PCM recorder fallback). */
export function enterRecordingAudioSession() {
  try {
    const session = getAudioSession()
    if (session) session.type = 'play-and-record'
  } catch {
    // best-effort — unsupported or blocked, nothing to do
  }
}

/** Call once mic capture ends, so playback (Bede's TTS) routes to the family's actual chosen output again. */
export function restorePlaybackAudioSession() {
  try {
    const session = getAudioSession()
    if (session) session.type = 'playback'
  } catch {
    // best-effort
  }
}
