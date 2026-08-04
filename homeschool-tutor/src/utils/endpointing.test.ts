/**
 * The assertion that matters most here is a NEGATIVE one, and it is the
 * opposite of what a dictation test would check: a child who pauses to think
 * mid-narration must NOT have their turn ended. Recall pauses are the work,
 * not hesitation — see endpointing.ts.
 */
import { describe, expect, it } from 'vitest'

import {
  MIN_SPEECH_MS,
  NO_SPEECH_TIMEOUT_MS,
  SAMPLE_INTERVAL_MS,
  SILENCE_LEVEL,
  TRAILING_SILENCE_MS,
  advanceEndpointState,
  endReason,
  initialEndpointState,
  shouldEndTurn,
} from './endpointing'

const LOUD = SILENCE_LEVEL + 0.2
const QUIET = 0

/** Feed a run of samples at the real sample interval. */
function feed(state: ReturnType<typeof initialEndpointState>, level: number, ms: number) {
  let next = state
  for (let elapsed = 0; elapsed < ms; elapsed += SAMPLE_INTERVAL_MS) {
    next = advanceEndpointState(next, { level, deltaMs: SAMPLE_INTERVAL_MS })
  }
  return next
}

describe('a child who is still thinking', () => {
  it('does not end the turn during a two-second thinking pause', () => {
    // The case this whole module has to get right. A general-purpose
    // dictation endpoint (~700-1500ms) would cut this child off mid-recall.
    let s = feed(initialEndpointState(), LOUD, 2000)
    s = feed(s, QUIET, 2000)
    expect(shouldEndTurn(s)).toBe(false)
  })

  it('survives several pauses in one long narration', () => {
    let s = initialEndpointState()
    for (let i = 0; i < 4; i++) {
      s = feed(s, LOUD, 1500)
      s = feed(s, QUIET, 2000)
      expect(shouldEndTurn(s)).toBe(false)
    }
  })

  it('resets the silence run the moment the child speaks again', () => {
    let s = feed(initialEndpointState(), LOUD, 1000)
    s = feed(s, QUIET, 2400)
    expect(s.silenceMs).toBeGreaterThan(0)
    s = advanceEndpointState(s, { level: LOUD, deltaMs: SAMPLE_INTERVAL_MS })
    expect(s.silenceMs).toBe(0)
    expect(shouldEndTurn(s)).toBe(false)
  })

  it('keeps the pause allowance well clear of a normal dictation endpoint', () => {
    // Guards the intent, not just the number: if someone "optimises" this to
    // feel snappier, it should be a deliberate argument, not a quiet edit.
    expect(TRAILING_SILENCE_MS).toBeGreaterThanOrEqual(2500)
  })
})

describe('a child who has finished', () => {
  it('ends the turn after the full trailing silence', () => {
    let s = feed(initialEndpointState(), LOUD, 1500)
    s = feed(s, QUIET, TRAILING_SILENCE_MS)
    expect(shouldEndTurn(s)).toBe(true)
    expect(endReason(s)).toBe('finished-speaking')
  })

  it('ends far sooner than the 120s safety ceiling it replaces', () => {
    let s = feed(initialEndpointState(), LOUD, 4000)
    s = feed(s, QUIET, TRAILING_SILENCE_MS)
    expect(shouldEndTurn(s)).toBe(true)
    // The whole point: a four-second answer used to hold the mic for 120s.
    expect(s.elapsedMs).toBeLessThan(30_000)
  })
})

describe('a child who never speaks', () => {
  it('does not end early just because the mic opened into silence', () => {
    const s = feed(initialEndpointState(), QUIET, 5000)
    expect(shouldEndTurn(s)).toBe(false)
  })

  it('eventually gives up rather than holding the mic to the safety ceiling', () => {
    const s = feed(initialEndpointState(), QUIET, NO_SPEECH_TIMEOUT_MS)
    expect(shouldEndTurn(s)).toBe(true)
    expect(endReason(s)).toBe('no-speech')
  })

  it('needs real speech, not a single stray sample, to arm the endpoint', () => {
    // One blip of noise must not make a silent room look like a finished
    // answer — that would end the turn TRAILING_SILENCE_MS later with
    // nothing recorded.
    let s = advanceEndpointState(initialEndpointState(), { level: LOUD, deltaMs: SAMPLE_INTERVAL_MS })
    expect(s.heardSpeech).toBe(false)
    s = feed(s, QUIET, TRAILING_SILENCE_MS)
    expect(endReason(s)).not.toBe('finished-speaking')
  })

  it('arms only once MIN_SPEECH_MS has genuinely accumulated', () => {
    const justUnder = feed(initialEndpointState(), LOUD, MIN_SPEECH_MS - SAMPLE_INTERVAL_MS)
    expect(justUnder.heardSpeech).toBe(false)
    const atThreshold = feed(initialEndpointState(), LOUD, MIN_SPEECH_MS)
    expect(atThreshold.heardSpeech).toBe(true)
  })
})

describe('the level threshold', () => {
  it('treats a level at the threshold as silence, not speech', () => {
    const s = feed(initialEndpointState(), SILENCE_LEVEL, 5000)
    expect(s.speechMs).toBe(0)
    expect(s.heardSpeech).toBe(false)
  })

  it('stays armed through a long quiet stretch, so a child who spoke is never stranded', () => {
    // HONEST NOTE, from mutation-testing this file: removing the explicit
    // `state.heardSpeech ||` latch does NOT make this fail, because speechMs
    // only ever accumulates — so `speechMs >= MIN_SPEECH_MS` is already
    // monotonic and the two implementations are equivalent today. This test
    // therefore pins the observable PROPERTY (once armed, always armed), not
    // the mechanism, and cannot prove the latch is doing anything.
    //
    // The latch stays anyway: it is what keeps this property true if speechMs
    // ever becomes a windowed or decaying measure, which is exactly the kind
    // of change that would otherwise silently un-arm the endpoint and leave a
    // child who did speak waiting on the no-speech clock instead.
    let s = feed(initialEndpointState(), LOUD, MIN_SPEECH_MS)
    expect(s.heardSpeech).toBe(true)
    s = feed(s, QUIET, 60_000)
    expect(s.heardSpeech).toBe(true)
    expect(endReason(s)).toBe('finished-speaking')
  })
})

describe('nothing fires before there is anything to fire on', () => {
  it('reports no end reason for a fresh state', () => {
    expect(shouldEndTurn(initialEndpointState())).toBe(false)
    expect(endReason(initialEndpointState())).toBe(null)
  })
})
