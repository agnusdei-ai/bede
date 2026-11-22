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
import { resetVoiceGateForTests, SPEAK_REQUEST_TIMEOUT_MS, VOICE_RECHECK_MS, useTextToSpeech } from './useTextToSpeech'

/** Installs `speakMock` for /tutor/speak and answers the voice-status ask
 *  with `speaks` (true unless a test says otherwise). */
function stubFetch(speakMock: (...args: any[]) => any, speaks = true) {
  const all = vi.fn((url: string, init?: RequestInit) => String(url).includes('/tutor/voice')
    ? Promise.resolve({ ok: true, json: async () => (speaks ? { configured: true, where: 'local', available: true } : { configured: false, where: null, available: false }) })
    : speakMock(url, init))
  vi.stubGlobal('fetch', all)
  return all
}

/** How many lines were sent to /tutor/speak. */
const speakRequests = () => (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls
  .filter(([u]) => String(u).includes('/tutor/speak')).length

describe('useTextToSpeech — backend (Fable) voice priority', () => {
  let browserSpeakSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    resetVoiceGateForTests()
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
    stubFetch(vi.fn().mockResolvedValue({
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
    stubFetch(fetchMock)
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
    stubFetch(vi.fn().mockResolvedValue({
      status: 200,
      headers: new Headers({ 'X-TTS-Configured': 'True' }),
      blob: async () => new Blob(['fake-audio'], { type: 'audio/wav' }),
    }))

    const { result } = renderHook(() => useTextToSpeech('fake-token'))
    act(() => result.current.speak('Good morning, dear one.'))

    await waitFor(() => expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1))
    expect(speakRequests()).toBe(1)
    expect(browserSpeakSpy).not.toHaveBeenCalled()
  })

  it('stays silent, never the browser voice, when no voice is configured on this deployment', async () => {
    stubFetch(vi.fn().mockResolvedValue({
      status: 204,
      headers: new Headers({ 'X-TTS-Configured': 'False' }),
      blob: async () => new Blob(),
    }))

    const { result } = renderHook(() => useTextToSpeech('fake-token'))
    act(() => result.current.speak('Good morning, dear one.'))

    await waitFor(() => expect(speakRequests()).toBe(1))
    await waitFor(() => expect(result.current.isSpeaking).toBe(false))
    expect(browserSpeakSpy).not.toHaveBeenCalled()
    expect(window.HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
  })

  it('stays silent — does NOT fall back to the browser voice — when TTS is configured but this one call fails', async () => {
    stubFetch(vi.fn().mockResolvedValue({
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
    stubFetch(vi.fn().mockResolvedValue({
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
    stubFetch(vi.fn().mockResolvedValue({
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
    stubFetch(vi.fn())

    const { result } = renderHook(() => useTextToSpeech(null))
    act(() => result.current.speak('Good morning, dear one.'))

    await waitFor(() => expect(result.current.isSpeaking).toBe(false))
    expect(fetch).not.toHaveBeenCalled()
    expect(browserSpeakSpy).not.toHaveBeenCalled()
  })

  // ── An install where Bede's voice cannot speak: text-first, nothing sent ──

  it('sends no line at all when no voice is configured or the voice is switched off', async () => {
    const speakMock = vi.fn()
    stubFetch(speakMock, false)
    const { result } = renderHook(() => useTextToSpeech('fake-token'))
    act(() => { result.current.speak('Good morning, dear one.') })
    act(() => { result.current.speak('Here are 4.') })
    await waitFor(() => expect(result.current.isSpeaking).toBe(false))
    expect(speakMock).not.toHaveBeenCalled()
    expect(speakRequests()).toBe(0)
    expect(browserSpeakSpy).not.toHaveBeenCalled()
    expect(window.HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
  })

  it('asks whether the voice can speak once per sign-in, not once per line', async () => {
    const all = stubFetch(vi.fn().mockResolvedValue({
      status: 200, headers: new Headers({ 'X-TTS-Configured': 'True' }), blob: async () => new Blob(['a']),
    }))
    const { result } = renderHook(() => useTextToSpeech('fake-token'))
    act(() => { result.current.speak('One.') })
    await waitFor(() => expect(speakRequests()).toBe(1))
    await waitFor(() => expect(result.current.isSpeaking).toBe(false))
    act(() => { result.current.speak('Two.') })
    await waitFor(() => expect(speakRequests()).toBe(2))
    expect(all.mock.calls.filter(([u]) => String(u).includes('/tutor/voice'))).toHaveLength(1)
  })

  it('a status check that fails is silent and is asked again, never treated as an answer', async () => {
    let fail = true
    const all = vi.fn((url: string) => {
      if (String(url).includes('/tutor/voice')) {
        return fail ? Promise.reject(new TypeError('Load failed'))
          : Promise.resolve({ ok: true, json: async () => ({ configured: true, where: 'local', available: true }) })
      }
      return Promise.resolve({ status: 200, headers: new Headers({ 'X-TTS-Configured': 'True' }), blob: async () => new Blob(['a']) })
    })
    vi.stubGlobal('fetch', all)
    const { result } = renderHook(() => useTextToSpeech('fake-token'))
    act(() => { result.current.speak('One.') })
    await waitFor(() => expect(result.current.isSpeaking).toBe(false))
    expect(speakRequests()).toBe(0)
    fail = false
    act(() => { result.current.speak('Two.') })
    await waitFor(() => expect(speakRequests()).toBe(1))
    expect(browserSpeakSpy).not.toHaveBeenCalled()
  })

  it('a line the speech service never answers is given up, silent, and Bede stops "speaking"', async () => {
    vi.useFakeTimers()
    try {
      stubFetch((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      }))
      const { result } = renderHook(() => useTextToSpeech('fake-token'))
      act(() => { result.current.speak('Here are 4.') })
      await act(async () => { await vi.advanceTimersByTimeAsync(10) })
      expect(result.current.isSpeaking).toBe(true)
      expect(speakRequests()).toBe(1)
      await act(async () => { await vi.advanceTimersByTimeAsync(SPEAK_REQUEST_TIMEOUT_MS + 1) })
      expect(result.current.isSpeaking).toBe(false)
      expect(browserSpeakSpy).not.toHaveBeenCalled()
      expect(window.HTMLMediaElement.prototype.play).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('when Piper is not answering, nothing is requested; once it is back, Bede speaks again', async () => {
    let up = false
    const speakMock = vi.fn().mockResolvedValue({
      status: 200, headers: new Headers({ 'X-TTS-Configured': 'True' }), blob: async () => new Blob(['a']),
    })
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => String(url).includes('/tutor/voice')
      ? Promise.resolve({ ok: true, json: async () => ({ configured: true, where: 'local', available: up }) })
      : speakMock(url, init)))
    const t0 = Date.now()
    const now = vi.spyOn(Date, 'now').mockReturnValue(t0)
    const { result } = renderHook(() => useTextToSpeech('fake-token'))
    act(() => { result.current.speak('One.') })
    await waitFor(() => expect(result.current.isSpeaking).toBe(false))
    up = true
    act(() => { result.current.speak('Two.') })
    await waitFor(() => expect(result.current.isSpeaking).toBe(false))
    expect(speakMock).not.toHaveBeenCalled()
    now.mockReturnValue(t0 + VOICE_RECHECK_MS + 1)
    act(() => { result.current.speak('Three.') })
    await waitFor(() => expect(speakMock).toHaveBeenCalledTimes(1))
    expect(browserSpeakSpy).not.toHaveBeenCalled()
  })
})
