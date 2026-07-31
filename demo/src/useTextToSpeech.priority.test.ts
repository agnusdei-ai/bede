/**
 * Regression coverage for speak()'s priority order: Bede's configured
 * backend voice (OpenAI TTS, "fable" — core/config.py's openai_tts_voice)
 * must always win over the browser's speechSynthesis fallback whenever the
 * backend is configured and the call succeeds. The browser voice is only
 * ever a last resort — see useTextToSpeech.ts's own comments on why a
 * configured-but-failed call stays silent rather than degrading to a
 * different voice mid-conversation.
 *
 * This exercises the REAL speakViaBackend() (from ./api) against a mocked
 * global fetch, not a mocked ./api module — so it proves the actual
 * request/response contract with the backend, not just that some function
 * got called.
 */
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { pickBestVoice, useTextToSpeech } from './useTextToSpeech'

describe('useTextToSpeech — backend (Fable) voice priority', () => {
  let browserSpeakSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    // Fires the utterance's onend the same way play()'s mock below fires
    // onended — speakViaBrowser()'s Promise only resolves via that
    // callback, which nothing simulates on its own in jsdom.
    browserSpeakSpy = vi.fn((utterance: SpeechSynthesisUtterance) => {
      queueMicrotask(() => utterance.onend?.(new Event('end') as any))
    })
    ;(window as any).speechSynthesis = {
      getVoices: () => [{ name: 'Microsoft David - English (United States)', lang: 'en-US' }],
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      speak: browserSpeakSpy,
      cancel: vi.fn(),
    }
    // jsdom doesn't implement the Web Speech API at all — not even the
    // SpeechSynthesisUtterance constructor speakViaBrowser() needs.
    ;(window as any).SpeechSynthesisUtterance = class {
      onend: (() => void) | null = null
      onerror: (() => void) | null = null
      voice: unknown = null
      rate = 1
      pitch = 1
      constructor(public text: string) {}
    }
    // jsdom doesn't implement real audio playback — the hook's own Promise
    // only resolves via audio.onended firing (real playback completing),
    // which nothing simulates on its own, so play() has to trigger it.
    window.HTMLMediaElement.prototype.play = vi.fn(function (this: HTMLAudioElement) {
      queueMicrotask(() => this.onended?.(new Event('ended')))
      return Promise.resolve()
    })
    window.HTMLMediaElement.prototype.pause = vi.fn()
    URL.createObjectURL = vi.fn(() => 'blob:fake-url')
    URL.revokeObjectURL = vi.fn()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('plays the backend voice and never touches the browser fallback when TTS is configured and the call succeeds', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200,
      headers: new Headers({ 'X-TTS-Configured': 'True' }),
      blob: async () => new Blob(['fake-audio'], { type: 'audio/wav' }),
    }))

    const { result } = renderHook(() => useTextToSpeech('fake-token'))

    await act(async () => {
      await result.current.speak('Good morning, dear one.')
    })

    expect(fetch).toHaveBeenCalledTimes(1)
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
    expect(browserSpeakSpy).not.toHaveBeenCalled()
  })

  it('falls back to the browser voice only when the backend reports TTS is not configured at all', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 204,
      headers: new Headers({ 'X-TTS-Configured': 'False' }),
      blob: async () => new Blob(),
    }))

    const { result } = renderHook(() => useTextToSpeech('fake-token'))

    await act(async () => {
      await result.current.speak('Good morning, dear one.')
    })

    expect(browserSpeakSpy).toHaveBeenCalledTimes(1)
    expect(window.HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
  })

  it('stays silent — does NOT fall back to the browser voice — when TTS is configured but this one call fails', async () => {
    // This is the case that matters most for "I don't hear Fable anymore":
    // a transient failure (bad key, quota, network) must never silently
    // degrade to a different voice; see the module comment above.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 500,
      headers: new Headers({ 'X-TTS-Configured': 'True' }),
      blob: async () => new Blob(),
    }))

    const { result } = renderHook(() => useTextToSpeech('fake-token'))

    await act(async () => {
      await result.current.speak('Good morning, dear one.')
    })

    expect(browserSpeakSpy).not.toHaveBeenCalled()
    expect(window.HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
  })

  it('stays silent — does NOT fall back to the browser voice — when real audio was fetched but the browser blocks play() (autoplay policy)', async () => {
    // Real report: a browser that keeps blocking audio.play() used to swap
    // to the jarring, robotic browser default voice on every single turn
    // for the whole session. Real Bede audio existing but being blocked
    // from playing must stay silent for that one line, never fall back.
    window.HTMLMediaElement.prototype.play = vi.fn(() => Promise.reject(new Error('NotAllowedError')))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200,
      headers: new Headers({ 'X-TTS-Configured': 'True' }),
      blob: async () => new Blob(['fake-audio'], { type: 'audio/wav' }),
    }))

    const { result } = renderHook(() => useTextToSpeech('fake-token'))

    await act(async () => {
      await result.current.speak('Good morning, dear one.')
    })

    expect(browserSpeakSpy).not.toHaveBeenCalled()
  })

  it('re-primes the shared audio element on the next real tap after a blocked play(), instead of staying blocked all session', async () => {
    const playSpy = vi.fn()
      .mockImplementationOnce(() => Promise.reject(new Error('NotAllowedError'))) // the real blocked turn
      .mockImplementation(() => Promise.resolve()) // the self-healing re-prime attempt, and anything after
    window.HTMLMediaElement.prototype.play = playSpy
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200,
      headers: new Headers({ 'X-TTS-Configured': 'True' }),
      blob: async () => new Blob(['fake-audio'], { type: 'audio/wav' }),
    }))

    const { result } = renderHook(() => useTextToSpeech('fake-token'))

    await act(async () => {
      await result.current.speak('Good morning, dear one.')
    })
    expect(playSpy).toHaveBeenCalledTimes(1)

    document.dispatchEvent(new Event('pointerdown'))
    expect(playSpy).toHaveBeenCalledTimes(2)
  })

  it('never calls the backend at all without a speak token (demo/session not authenticated yet)', async () => {
    vi.stubGlobal('fetch', vi.fn())

    const { result } = renderHook(() => useTextToSpeech(null))

    await act(async () => {
      await result.current.speak('Good morning, dear one.')
    })

    expect(fetch).not.toHaveBeenCalled()
    expect(browserSpeakSpy).toHaveBeenCalledTimes(1)
  })
})


describe('pickBestVoice — language', () => {
  const withVoices = (voices: Array<{ name: string; lang: string }>) => {
    ;(window as any).speechSynthesis = { getVoices: () => voices }
  }

  it('picks a Spanish voice for a Spanish session, never an English one', () => {
    withVoices([
      { name: 'Microsoft David - English (United States)', lang: 'en-US' },
      { name: 'Jorge', lang: 'es-MX' },
    ])
    expect(pickBestVoice('es')?.name).toBe('Jorge')
  })

  it('prefers a known Spanish male voice over other Spanish voices', () => {
    withVoices([
      { name: 'Paulina', lang: 'es-MX' },
      { name: 'Diego', lang: 'es-AR' },
    ])
    expect(pickBestVoice('es')?.name).toBe('Diego')
  })

  it('returns null rather than an English voice when no Spanish voice exists', () => {
    // Reading Spanish text aloud in an English voice is worse than leaving
    // utterance.voice unset and letting the engine choose from utterance.lang.
    withVoices([{ name: 'Microsoft David - English (United States)', lang: 'en-US' }])
    expect(pickBestVoice('es')).toBeNull()
  })

  it('still falls back to any available voice for English', () => {
    // Long-standing behaviour for English, deliberately preserved.
    withVoices([{ name: 'Something Unlabelled', lang: 'fr-FR' }])
    expect(pickBestVoice('en')?.name).toBe('Something Unlabelled')
  })

  it('defaults to English when no language is given', () => {
    withVoices([
      { name: 'Jorge', lang: 'es-MX' },
      { name: 'Daniel', lang: 'en-GB' },
    ])
    expect(pickBestVoice()?.name).toBe('Daniel')
  })
})
