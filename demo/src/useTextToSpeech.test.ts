/**
 * Regression coverage for Bede's voice-selection logic (useTextToSpeech.ts)
 * — this whole area had never had automated tests, which is exactly how a
 * real, reported bug (voice reverting to a woman's on Microsoft Edge a few
 * turns into a session) shipped and sat unnoticed. See useTextToSpeech.ts's
 * own comments for the confirmed mechanism: Edge fires 'voiceschanged' more
 * than once per session as it lazy-loads online/neural voices, reissuing
 * brand-new SpeechSynthesisVoice objects for what is logically the same
 * voice — code that cached the first-resolved object forever ended up
 * handing a stale reference to later utterances, which Edge silently
 * ignored in favor of its own (female) default.
 *
 * Each test dynamically re-imports the module after vi.resetModules() so
 * the module-scoped voicesReadyPromise cache starts fresh — without that,
 * tests would leak state into each other the same way a real page's first
 * speak() call does across a whole tab session.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

type FakeVoice = { name: string; lang: string }

function voice(name: string, lang = 'en-US'): FakeVoice {
  return { name, lang }
}

function makeFakeSpeechSynthesis(initialVoices: FakeVoice[] = []) {
  let voices = initialVoices
  const listeners: Record<string, Array<() => void>> = {}
  return {
    getVoices: () => voices,
    addEventListener: (event: string, handler: () => void) => {
      ;(listeners[event] ||= []).push(handler)
    },
    removeEventListener: (event: string, handler: () => void) => {
      listeners[event] = (listeners[event] || []).filter((h) => h !== handler)
    },
    // Test-only helper (not part of the real SpeechSynthesis API) — fires
    // 'voiceschanged' the same way a real engine would after loading more
    // voices, letting tests simulate Edge firing it more than once.
    __setVoices(next: FakeVoice[]) {
      voices = next
      ;(listeners['voiceschanged'] || []).forEach((h) => h())
    },
  }
}

beforeEach(() => {
  vi.resetModules()
})

describe('pickBestVoice', () => {
  it('prefers a known male voice name over an unlabeled voice that is actually female', async () => {
    const { pickBestVoice } = await import('./useTextToSpeech')
    ;(window as any).speechSynthesis = makeFakeSpeechSynthesis([
      voice('Google US English'), // confirmed-female despite the neutral-sounding name
      voice('Microsoft David - English (United States)'),
    ])
    expect(pickBestVoice()?.name).toBe('Microsoft David - English (United States)')
  })

  it('prefers an en-GB male-labeled voice over an ambiguous same-language one', async () => {
    const { pickBestVoice } = await import('./useTextToSpeech')
    ;(window as any).speechSynthesis = makeFakeSpeechSynthesis([
      voice('Some Ambiguous Voice', 'en-GB'),
      voice('James (Male)', 'en-GB'),
    ])
    expect(pickBestVoice()?.name).toBe('James (Male)')
  })

  it('avoids an explicitly-female-labeled voice even with no male match available', async () => {
    const { pickBestVoice } = await import('./useTextToSpeech')
    ;(window as any).speechSynthesis = makeFakeSpeechSynthesis([
      voice('Unknown (Female)', 'en-US'),
      voice('Neutral Sounding Voice', 'en-US'),
    ])
    expect(pickBestVoice()?.name).toBe('Neutral Sounding Voice')
  })

  it('falls back to the first available voice when nothing else matches', async () => {
    const { pickBestVoice } = await import('./useTextToSpeech')
    ;(window as any).speechSynthesis = makeFakeSpeechSynthesis([voice('Only Option', 'fr-FR')])
    expect(pickBestVoice()?.name).toBe('Only Option')
  })

  it('returns null when there are no voices at all', async () => {
    const { pickBestVoice } = await import('./useTextToSpeech')
    ;(window as any).speechSynthesis = makeFakeSpeechSynthesis([])
    expect(pickBestVoice()).toBeNull()
  })
})

describe('isFemaleVoiceName / isMaleVoiceName', () => {
  it('does not let "female" count as a positive male match via its "male" substring', async () => {
    const { isFemaleVoiceName, isMaleVoiceName } = await import('./useTextToSpeech')
    expect(isFemaleVoiceName('Alex (Female)')).toBe(true)
    expect(isMaleVoiceName('Alex (Female)')).toBe(false)
  })

  it('matches known female voice names that carry no gender word at all', async () => {
    const { isFemaleVoiceName } = await import('./useTextToSpeech')
    expect(isFemaleVoiceName('Google US English')).toBe(true)
    expect(isFemaleVoiceName('Samantha')).toBe(true)
  })
})

describe('resolveVoice — Edge stale-voice-object regression', () => {
  it('re-resolves a live voice object after the engine reissues its voice list mid-session', async () => {
    const { resolveVoice } = await import('./useTextToSpeech')

    const fakeSynth = makeFakeSpeechSynthesis([])
    ;(window as any).speechSynthesis = fakeSynth

    const firstResolvePromise = resolveVoice()
    const firstGenDavid = voice('Microsoft David - English (United States)')
    fakeSynth.__setVoices([voice('Some Other Voice'), firstGenDavid])
    const firstResolved = await firstResolvePromise
    expect(firstResolved).toBe(firstGenDavid)

    // Edge reissues the whole voice list with brand-new object instances
    // for what is logically the same voice — the exact behavior that broke
    // the old "cache the object forever" implementation.
    const secondGenDavid = voice('Microsoft David - English (United States)')
    fakeSynth.__setVoices([voice('Some Other Voice'), secondGenDavid])

    const secondResolved = await resolveVoice()
    expect(secondResolved).toBe(secondGenDavid)
    expect(secondResolved).not.toBe(firstGenDavid)
  })

  it('waits for an async voiceschanged event when getVoices() is initially empty', async () => {
    const { resolveVoice } = await import('./useTextToSpeech')
    const fakeSynth = makeFakeSpeechSynthesis([])
    ;(window as any).speechSynthesis = fakeSynth

    const resolvePromise = resolveVoice()
    const david = voice('Microsoft David - English (United States)')
    setTimeout(() => fakeSynth.__setVoices([david]), 0)

    expect(await resolvePromise).toBe(david)
  })
})
