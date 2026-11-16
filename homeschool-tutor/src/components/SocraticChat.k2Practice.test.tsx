/**
 * Bede's invite_practice card actually opens the phonics round: the chat
 * reads the server's `area` off the tool chunk and mounts K2PhonicsPractice,
 * which loads its lesson from the practice route. The card can reopen it.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import type { SessionConfig } from '../types'
import SocraticChat from './SocraticChat'

const CONFIG = {
  student_name: 'Ada', grade: '1', grade_stage: 'K-2', subjects: ['language_arts'],
} as unknown as SessionConfig

const CARD = '🔤 *Sound Time* — Let’s play with sounds and words.'
const LESSON = {
  lesson_id: 'L1', area: 'phonics', level: '1', domain: 'cvc_blending', your_turn_tries: 2,
  watch: {
    prompt: { key: 'read_word_choice', args: {} },
    display: { kind: 'word', word: 'cat', graphemes: [{ text: 'c', sound: 'kuh' }, { text: 'a', sound: 'ah' }, { text: 't', sound: 'tuh' }] },
    choice_kind: 'picture', choices: ['dog', 'cat', 'sun'], answer: { choice: 'cat' },
  },
  together: [], your_turn: [],
}

function sse(chunks: object[]): Response {
  const body = chunks.map((c) => `data: ${JSON.stringify(c)}\n\n`).join('')
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

let area: string | undefined
const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
  if (String(url).includes('/tutor/chat')) {
    return sse([{ type: 'tool', tool: 'invite_practice', area, content: CARD }, { type: 'done' }])
  }
  if (String(url).includes('/k2-practice/')) {
    return new Response(JSON.stringify(LESSON), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  return new Response('{}', { status: 404 })
})

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
  Element.prototype.scrollIntoView = vi.fn()
  act(() => {
    useSessionStore.getState().logout()
    useSessionStore.getState().setAuth('child-token', 'child')
    useSessionStore.getState().setSessionConfig(CONFIG)
    useSessionStore.getState().startSession()
  })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear() })

describe('the invite_practice card', () => {
  it('opens the phonics round, which loads its lesson from the practice route', async () => {
    area = 'phonics'
    render(<SocraticChat />)
    expect(await screen.findByRole('dialog', { name: 'Sound Time' })).toBeTruthy()
    const urls = fetchMock.mock.calls.map(([u]) => String(u))
    expect(urls.some((u) => u.includes('/k2-practice/Ada/phonics/lesson'))).toBe(true)
    // Closing returns to the chat; the card reopens it.
    fireEvent.click(screen.getByRole('button', { name: 'Back to Bede' }))
    expect(screen.queryByRole('dialog', { name: 'Sound Time' })).toBeNull()
    fireEvent.click(await screen.findByRole('button', { name: 'Start Sound Time' }))
    expect(await screen.findByRole('dialog', { name: 'Sound Time' })).toBeTruthy()
  })

  it('speaks the round on the device and never through /tutor/speak', async () => {
    // Nothing from a round may reach an AI provider: /tutor/speak forwards
    // text to a cloud speech service, so a round must use the browser's own.
    const spoken: { text: string; lang: string }[] = []
    class Utterance { text: string; lang = ''; voice: unknown = null; rate = 1; pitch = 1
      constructor(text: string) { this.text = text } }
    vi.stubGlobal('SpeechSynthesisUtterance', Utterance)
    vi.stubGlobal('speechSynthesis', {
      speak: (u: Utterance) => spoken.push({ text: u.text, lang: u.lang }),
      cancel: vi.fn(), pause: vi.fn(), resume: vi.fn(),
      getVoices: () => [{ name: 'Daniel', lang: 'en-GB' }],
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      speaking: false, pending: false,
    })
    area = 'phonics'
    render(<SocraticChat />)
    await screen.findByRole('dialog', { name: 'Sound Time' })
    const watchLine = 'Listen: kuh, ah, tuh. Put the sounds together: cat!'
    await waitFor(() => expect(spoken.map((s) => s.text)).toContain(watchLine))
    expect(spoken.find((s) => s.text === watchLine)?.lang).toBe('en-GB')
    fireEvent.click(screen.getByRole('button', { name: 'Hear it again' }))
    await waitFor(() => expect(spoken.filter((s) => s.text === watchLine).length).toBe(2))
    const speakCalls = fetchMock.mock.calls.filter(([u]) => String(u).includes('/tutor/speak'))
    for (const [, init] of speakCalls) {
      const body = String((init as RequestInit | undefined)?.body ?? '')
      expect(body).not.toContain('Listen:')
      expect(body).not.toContain('kuh')
    }
  })

  it('opens nothing for an area that is not built', async () => {
    area = 'math'
    render(<SocraticChat />)
    await screen.findAllByText(/Sound Time/)
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(screen.queryByRole('dialog', { name: 'Sound Time' })).toBeNull()
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/k2-practice/'))).toBe(false)
  })
})
