/**
 * Deciding when a child has finished speaking, without them saying so.
 *
 * MIRRORED from homeschool-tutor/src/utils/endpointing.ts, byte for byte
 * apart from this note — same reasoning as demo/src/holdGesture.ts and
 * demo/src/canvasPersistence.ts. The demo is the thing a family judges the
 * product by, so it must not have worse voice behaviour than the product it
 * is selling; that is exactly what it had while this file existed only in
 * the app.
 *
 * Hold-to-talk doesn't need this — releasing the button IS the endpoint. But
 * continuous "Voice on" mode has no such signal, and `useHybridVoiceInput`'s
 * own KNOWN GAP note records the consequence: `start()` behaves exactly like
 * `startHold()`, nothing ever calls `release()`, and the turn therefore runs
 * for the full `HOLD_SAFETY_TIMEOUT_MS` — two minutes — before finishing.
 * A child answers in four seconds and then watches the mic sit open for
 * another hundred and sixteen.
 *
 * WHY THE NUMBERS ARE NOT THE USUAL DICTATION NUMBERS
 *
 * General-purpose dictation endpoints after roughly 700-1500ms of silence.
 * That is wrong here, and confidently so. This app's central activity is
 * narration — a child recalling a passage aloud, in their own words, from
 * memory. Thinking pauses mid-narration are not hesitation to be trimmed;
 * they are the work. Cutting a child off mid-recall to "helpfully" submit a
 * half-sentence is worse than any latency it saves, and it punishes exactly
 * the careful, unhurried recall the whole method is trying to build (see
 * docs/SOCRATIC_METHOD.md's pacing note, and _WORK_SCORING_NOTE's standing
 * rule never to hurry a child).
 *
 * So TRAILING_SILENCE_MS is deliberately long. The cost of waiting an extra
 * second is a second; the cost of cutting in early is the child's answer.
 *
 * HONEST LIMITS
 *
 * SILENCE_LEVEL is a fixed threshold against `useVoiceRecorder`'s level meter
 * (mean FFT magnitude / 128, clamped to 0-1). It has NOT been tuned against
 * real hardware in a real room — it cannot be from a sandbox with no
 * microphone. It is the first thing to adjust if a report says turns end too
 * early (raise TRAILING_SILENCE_MS first, then lower SILENCE_LEVEL) or never
 * end at all (raise SILENCE_LEVEL). Everything here is bounded by the
 * existing 120s safety timeout regardless, so a badly tuned threshold
 * degrades to today's behaviour rather than to something worse.
 */

/** Below this level, we call it silence. See the honest-limits note above. */
export const SILENCE_LEVEL = 0.06

/**
 * How much speech must be heard before endpointing is allowed to fire at all.
 * Without this, the silence between "mic opened" and "child drew breath"
 * would end the turn before it began.
 */
export const MIN_SPEECH_MS = 600

/**
 * Trailing silence that ends a turn. Long on purpose — see the note above on
 * why narration pauses are the work, not hesitation.
 */
export const TRAILING_SILENCE_MS = 3000

/**
 * If no speech is ever heard, end the turn after this instead of holding the
 * microphone open to the 120s safety ceiling. Covers an auto-start that fired
 * when the child had already walked away, or a mic that is live but picking
 * up nothing.
 */
export const NO_SPEECH_TIMEOUT_MS = 12_000

/** How often the caller should sample the level and advance this state. */
export const SAMPLE_INTERVAL_MS = 200

export interface EndpointState {
  /** Whether MIN_SPEECH_MS of speech has accumulated this turn. */
  heardSpeech: boolean
  /** Speech time accumulated so far, capped once heardSpeech is true. */
  speechMs: number
  /** Unbroken silence since the last speech sample. */
  silenceMs: number
  /** Total elapsed, used only for the never-spoke-at-all case. */
  elapsedMs: number
}

export function initialEndpointState(): EndpointState {
  return { heardSpeech: false, speechMs: 0, silenceMs: 0, elapsedMs: 0 }
}

/**
 * Fold one level sample into the state. Pure — no timers, no audio, no React
 * — so every boundary below can be tested directly instead of inferred from a
 * rendered component with a fake microphone.
 */
export function advanceEndpointState(
  state: EndpointState,
  { level, deltaMs }: { level: number; deltaMs: number },
): EndpointState {
  const speaking = level > SILENCE_LEVEL
  const speechMs = speaking ? state.speechMs + deltaMs : state.speechMs
  return {
    // Latches once reached: a child who has spoken has spoken, and a later
    // quiet stretch must not un-arm the endpoint and strand the turn.
    heardSpeech: state.heardSpeech || speechMs >= MIN_SPEECH_MS,
    speechMs,
    silenceMs: speaking ? 0 : state.silenceMs + deltaMs,
    elapsedMs: state.elapsedMs + deltaMs,
  }
}

/**
 * Has this turn ended? Two independent reasons, deliberately kept apart:
 * the child finished speaking, or the child never started.
 */
export function shouldEndTurn(state: EndpointState): boolean {
  if (state.heardSpeech) return state.silenceMs >= TRAILING_SILENCE_MS
  return state.elapsedMs >= NO_SPEECH_TIMEOUT_MS
}

/** Which of the two reasons fired — for the debug overlay, so a report can
 *  say whether a turn ended because the child stopped or never spoke. */
export function endReason(state: EndpointState): 'finished-speaking' | 'no-speech' | null {
  if (!shouldEndTurn(state)) return null
  return state.heardSpeech ? 'finished-speaking' : 'no-speech'
}
