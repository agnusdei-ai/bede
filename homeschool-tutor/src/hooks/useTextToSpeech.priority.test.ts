/**
 * Regression coverage for speak(): Bede's voice comes only from the server's
 * /tutor/speak (the local voice, or the configured cloud voice), and a line
 * that cannot be spoken in it is SILENT. The browser's own speechSynthesis is
 * stubbed here only so every test can prove it is never called (owner
 * decision 2026-11-18, docs/DECISIONS.md entry 46).
 *
 * speak() here is synchronous — it pushes onto an internal queue and lets
 * processQueue() drain it — so tests poll for the expected side effect via
 * waitFor() rather than awaiting speak()'s own return value.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useTextToSpeech } from './useTextToSpeech'

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

  it('mic barge-in stops backend playback immediately and the next utterance completes', async () => {
    let audio!: HTMLAudioElement
    window.HTMLMediaElement.prototype.play = vi.fn(function (this: HTMLAudioElement) {
      audio = this
      return Promise.resolve()
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200,
      headers: new Headers({ 'X-TTS-Configured': 'True' }),
      blob: async () => new Blob(['sample-audio'], { type: 'audio/wav' }),
    }))
    const { result } = renderHook(() => useTextToSpeech('fake-token'))
    act(() => { void result.current.speak('Sample first utterance.') })
    await waitFor(() => expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1))
    expect(result.current.isSpeaking).toBe(true)
    act(() => result.current.stop())
    expect(window.HTMLMediaElement.prototype.pause).toHaveBeenCalledTimes(1)
    expect(result.current.isSpeaking).toBe(false)
    act(() => { void result.current.speak('Sample next utterance.') })
    await waitFor(() => expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(2))
    expect(result.current.isSpeaking).toBe(true)
    await act(async () => { audio.onended?.(new Event('ended')) })
    expect(result.current.isSpeaking).toBe(false)
    expect(browserSpeakSpy).not.toHaveBeenCalled()
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2)
  })

  it('late pre-interruption audio cannot restart playback over the next utterance', async () => {
    let finishOldFetch!: (response: unknown) => void
    let audio!: HTMLAudioElement
    const response = {
      status: 200,
      headers: new Headers({ 'X-TTS-Configured': 'True' }),
      blob: async () => new Blob(['sample-audio'], { type: 'audio/wav' }),
    }
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise((resolve) => { finishOldFetch = resolve }))
      .mockResolvedValue(response)
    vi.stubGlobal('fetch', fetchMock)
    window.HTMLMediaElement.prototype.play = vi.fn(function (this: HTMLAudioElement) {
      audio = this
      return Promise.resolve()
    })
    const { result } = renderHook(() => useTextToSpeech('fake-token'))
    act(() => { void result.current.speak('Sample slow utterance.') })
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    act(() => { result.current.stop(); void result.current.speak('Sample current utterance.') })
    await waitFor(() => expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1))
    await act(async () => { finishOldFetch(response); await new Promise((resolve) => setTimeout(resolve, 0)) })
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1)
    expect(result.current.isSpeaking).toBe(true)
    expect(browserSpeakSpy).not.toHaveBeenCalled()
    await act(async () => { audio.onended?.(new Event('ended')) })
    expect(result.current.isSpeaking).toBe(false)
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

  it('stays silent, never the browser voice, when no voice is configured on this deployment', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 204,
      headers: new Headers({ 'X-TTS-Configured': 'False' }),
      blob: async () => new Blob(),
    }))

    const { result } = renderHook(() => useTextToSpeech('fake-token'))
    act(() => result.current.speak('Good morning, dear one.'))

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(result.current.isSpeaking).toBe(false))
    expect(browserSpeakSpy).not.toHaveBeenCalled()
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

    await waitFor(() => expect(result.current.isSpeaking).toBe(false))
    expect(fetch).not.toHaveBeenCalled()
    expect(browserSpeakSpy).not.toHaveBeenCalled()
  })
})
