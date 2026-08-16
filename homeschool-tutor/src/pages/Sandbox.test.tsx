/**
 * Regression coverage for Sandbox.tsx's text-to-speech wiring — Bede's
 * voice previously existed only in a real child session (SocraticChat.tsx),
 * not in the parent-only "Ask Bede" sandbox, even though the whole point of
 * this page is previewing what a response will sound like before a child
 * hears it. This mirrors useTextToSpeech.priority.test.ts's own fetch-mock
 * approach (the real speak() call, against a mocked global fetch) rather
 * than mocking the hook itself, so it proves the actual request/response
 * contract from this page, not just that some function got called.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { streamSandboxChat } = vi.hoisted(() => ({ streamSandboxChat: vi.fn() }))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return { ...actual, streamSandboxChat }
})

import { useSessionStore } from '../store/sessionStore'
import Sandbox from './Sandbox'

function renderSandbox() {
  return render(
    <MemoryRouter>
      <Sandbox />
    </MemoryRouter>,
  )
}

/** streamSandboxChat is an async generator; tests drive it via this helper
 *  so each one controls exactly which chunks arrive and when. */
async function* chunksOf(...texts: string[]) {
  for (const content of texts) yield { type: 'text', content }
}

beforeEach(() => {
  useSessionStore.setState({ token: 'parent-tok' })
  streamSandboxChat.mockReset()
  window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined)
  window.HTMLMediaElement.prototype.pause = vi.fn()
  URL.createObjectURL = vi.fn(() => 'blob:fake-url')
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => {
  useSessionStore.setState({ token: null })
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  // This project's vitest config doesn't set `globals: true`, so RTL's own
  // automatic afterEach(cleanup) never registers.
  cleanup()
})

describe('Sandbox — Bede speaks its answers', () => {
  it('speaks the full assembled reply once streaming completes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200,
      headers: new Headers({ 'X-TTS-Configured': 'True' }),
      blob: async () => new Blob(['fake-audio'], { type: 'audio/aac' }),
    }))
    streamSandboxChat.mockReturnValue(chunksOf('Equivalent fractions ', 'represent the same amount.'))

    renderSandbox()
    fireEvent.change(screen.getByPlaceholderText('Enter the SANDBOX_PIN configured for this deployment'), {
      target: { value: '1234' },
    })
    const input = screen.getByPlaceholderText('Ask Bede anything…')
    fireEvent.change(input, { target: { value: 'What are equivalent fractions?' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/api/tutor/speak',
      expect.objectContaining({
        body: JSON.stringify({ text: 'Equivalent fractions represent the same amount.' }),
      }),
    ))
  })

  it('does not call speak for an empty or whitespace-only reply', async () => {
    vi.stubGlobal('fetch', vi.fn())
    streamSandboxChat.mockReturnValue(chunksOf('   '))

    renderSandbox()
    fireEvent.change(screen.getByPlaceholderText('Enter the SANDBOX_PIN configured for this deployment'), {
      target: { value: '1234' },
    })
    const input = screen.getByPlaceholderText('Ask Bede anything…')
    fireEvent.change(input, { target: { value: 'Anything' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(streamSandboxChat).toHaveBeenCalledTimes(1))
    expect(fetch).not.toHaveBeenCalledWith('/api/tutor/speak', expect.anything())
  })

  it('stops a still-speaking previous answer before sending the next question', async () => {
    // A rapid-fire testing tool is exactly the case where a parent fires off
    // a second question before the first has finished speaking. jsdom never
    // fires a real <audio> 'ended' event on its own, so speakViaBackend's
    // internal promise (which only resolves via onended/onerror) genuinely
    // hangs after the first send here — the hook stays "speaking" exactly
    // as if real playback were still in progress, with no extra plumbing
    // needed to simulate it.
    streamSandboxChat
      .mockReturnValueOnce(chunksOf('First answer.'))
      .mockReturnValueOnce(chunksOf('Second question.'))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200,
      headers: new Headers({ 'X-TTS-Configured': 'True' }),
      blob: async () => new Blob(['fake-audio']),
    }))

    renderSandbox()
    fireEvent.change(screen.getByPlaceholderText('Enter the SANDBOX_PIN configured for this deployment'), {
      target: { value: '1234' },
    })
    const input = screen.getByPlaceholderText('Ask Bede anything…')
    fireEvent.change(input, { target: { value: 'First question' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    // First reply spoken; its playback promise is left hanging (see above).
    await waitFor(() => expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1))
    expect(window.HTMLMediaElement.prototype.pause).not.toHaveBeenCalled()

    fireEvent.change(input, { target: { value: 'Second question' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    // stopSpeech() at the top of handleSend() must reach into the still-
    // hanging first call and actually pause the shared <audio> element —
    // the concrete, assertable behaviour behind "stops a still-speaking
    // previous answer," not just that the page didn't crash.
    await waitFor(() => expect(window.HTMLMediaElement.prototype.pause).toHaveBeenCalledTimes(1))
  })

  it('renders a mute/unmute toggle that silences the next reply', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200,
      headers: new Headers({ 'X-TTS-Configured': 'True' }),
      blob: async () => new Blob(['fake-audio']),
    }))
    streamSandboxChat.mockReturnValue(chunksOf('An answer.'))

    renderSandbox()
    const muteButton = screen.getByTitle('Mute Bede')
    fireEvent.click(muteButton)
    await screen.findByTitle('Unmute Bede')

    fireEvent.change(screen.getByPlaceholderText('Enter the SANDBOX_PIN configured for this deployment'), {
      target: { value: '1234' },
    })
    const input = screen.getByPlaceholderText('Ask Bede anything…')
    fireEvent.change(input, { target: { value: 'A question' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(streamSandboxChat).toHaveBeenCalledTimes(1))
    expect(fetch).not.toHaveBeenCalledWith('/api/tutor/speak', expect.anything())
  })
})
