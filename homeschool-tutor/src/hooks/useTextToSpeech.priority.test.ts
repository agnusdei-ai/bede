/**
 * Regression coverage for speak()'s priority order: Bede's configured
 * backend voice (OpenAI TTS, "fable" — homeschool-api/core/config.py's
 * openai_tts_voice) must always win over the browser's speechSynthesis
 * fallback whenever the backend is configured and the call succeeds. The
 * browser voice is only ever a last resort — see useTextToSpeech.ts's own
 * comments on why a configured-but-failed call stays silent rather than
 * degrading to a different voice mid-conversation.
 *
 * speak() here is synchronous — it pushes onto an internal queue and lets
 * processQueue() drain it — so tests poll for the expected side effect via
 * waitFor() rather than awaiting speak()'s own return value.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { pickBestVoice, useTextToSpeech } from './useTextToSpeech'

describe('useTextToSpeech — backend (Fable) voice priority', () => {
  let browserSpeakSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
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
    ;(window as any).SpeechSynthesisUtterance = class {
      onend: (() => void) | null = null
      onerror: (() => void) | null = null
      voice: unknown = null
      rate = 1
      pitch = 1
      volume = 1
      constructor(public text: string) {}
    }
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
    act(() => result.current.speak('Good morning, dear one.'))

    await waitFor(() => expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1))
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(browserSpeakSpy).not.toHaveBeenCalled()
  })

  it('falls back to the browser voice only when the backend reports TTS is not configured at all', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 204,
      headers: new Headers({ 'X-TTS-Configured': 'False' }),
      blob: async () => new Blob(),
    }))

    const { result } = renderHook(() => useTextToSpeech('fake-token'))
    act(() => result.current.speak('Good morning, dear one.'))

    await waitFor(() => expect(browserSpeakSpy).toHaveBeenCalledTimes(1))
    expect(window.HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
  })

  it('stays silent — does NOT fall back to the browser voice — when TTS is configured but this one call fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 500,
      headers: new Headers({ 'X-TTS-Configured': 'True' }),
      blob: async () => new Blob(),
    }))

    const { result } = renderHook(() => useTextToSpeech('fake-token'))
    act(() => result.current.speak('Good morning, dear one.'))

    await waitFor(() => expect(result.current.isSpeaking).toBe(false))
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
    act(() => result.current.speak('Good morning, dear one.'))

    await waitFor(() => expect(result.current.isSpeaking).toBe(false))
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
    act(() => result.current.speak('Good morning, dear one.'))
    await waitFor(() => expect(playSpy).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(result.current.isSpeaking).toBe(false))

    document.dispatchEvent(new Event('pointerdown'))
    await waitFor(() => expect(playSpy).toHaveBeenCalledTimes(2))
  })

  it('never calls the backend at all without a token (not logged in yet)', async () => {
    vi.stubGlobal('fetch', vi.fn())

    const { result } = renderHook(() => useTextToSpeech(null))
    act(() => result.current.speak('Good morning, dear one.'))

    await waitFor(() => expect(browserSpeakSpy).toHaveBeenCalledTimes(1))
    expect(fetch).not.toHaveBeenCalled()
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
