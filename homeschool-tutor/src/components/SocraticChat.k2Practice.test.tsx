/**
 * Bede's invite_practice card actually opens the phonics round: the chat
 * reads the server's `area` off the tool chunk and mounts K2PhonicsPractice,
 * which loads its lesson from the practice route. The card can reopen it.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import type { SessionConfig } from '../types'
import SocraticChat from './SocraticChat'
import { resetVoiceGateForTests } from '../hooks/useTextToSpeech'

const CONFIG = {
  student_name: 'Ada', grade: '1', grade_stage: 'K-2', subjects: ['language_arts'],
} as unknown as SessionConfig

const CARD = '🔤 *Sound Time* — Let’s play with sounds and words.'
const MATH_CARD = '🔢 *Number Time* — Let’s play with counters and numbers.'
const MATH_LESSON = {
  lesson_id: 'M1', area: 'math', level: '1', topic: 'add', skill: 'oa.add_within_20', your_turn_tries: 2,
  watch: {
    prompt: { key: 'add_how_many', args: { a: '5', b: '3' } },
    display: { diagram: { kind: 'ten_frame', frames: 1, red: 5, yellow: 3 }, guide: true },
    choice_kind: 'number', choices: ['7', '8', '9'], answer: { choice: '8' },
  },
  together: [], your_turn: [],
}
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
/** What GET /tutor/voice answers ('fail' = the request itself fails). */
let voiceStatus: { configured: boolean; where: string | null; available: boolean } | 'fail' = { configured: true, where: 'local', available: true }
/** How /tutor/speak answers: 204 = Bede's voice is set up but the line
 *  failed; 'hang' = it never answers. */
let speakAnswer: 204 | 'hang' = 204
/** A phonics lesson with a Together step, so a child actually answers. */
let lessonFor: () => object = () => LESSON
const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
  if (String(url).includes('/tutor/chat')) {
    return sse([{ type: 'tool', tool: 'invite_practice', area, content: area === 'math' ? MATH_CARD : CARD }, { type: 'done' }])
  }
  if (String(url).includes('/tutor/voice')) {
    if (voiceStatus === 'fail') throw new TypeError('Load failed')
    return new Response(JSON.stringify(voiceStatus), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  if (String(url).includes('/tutor/speak')) {
    if (speakAnswer === 'hang') return new Promise<Response>(() => {})
    // Bede's voice is configured; the call returns no audio, so the hook
    // stays silent rather than switching to another voice.
    return new Response(null, { status: 204, headers: { 'X-TTS-Configured': 'True' } })
  }
  if (String(url).includes('/answers')) {
    return new Response(JSON.stringify({ understood: true, correct: true }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  if (String(url).includes('/k2-practice/') && String(url).includes('/math/')) {
    return new Response(JSON.stringify(MATH_LESSON), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  if (String(url).includes('/k2-practice/')) {
    return new Response(JSON.stringify(lessonFor()), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  return new Response('{}', { status: 404 })
})

/** The lines sent to Bede's own voice (`/tutor/speak`), in order. */
function spokenByBede(): string[] {
  return fetchMock.mock.calls
    .filter(([u]) => String(u).includes('/tutor/speak'))
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)).text)
}

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
  resetVoiceGateForTests()
  voiceStatus = { configured: true, where: 'local', available: true }
  speakAnswer = 204
  lessonFor = () => LESSON
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

  it("speaks the phonics round in Bede's own voice, never an on-device or default voice", async () => {
    // Owner direction 2026-11-18: every feature uses Bede's voice, the same
    // /tutor/speak path as the chat, with no other voice as a default.
    const deviceSpoken: string[] = []
    class Utterance { text: string; lang = ''; voice: unknown = null; rate = 1; pitch = 1
      constructor(text: string) { this.text = text } }
    vi.stubGlobal('SpeechSynthesisUtterance', Utterance)
    vi.stubGlobal('speechSynthesis', {
      speak: (u: Utterance) => deviceSpoken.push(u.text), cancel: vi.fn(), pause: vi.fn(), resume: vi.fn(),
      getVoices: () => [{ name: 'Daniel', lang: 'en-GB', localService: true }],
      addEventListener: vi.fn(), removeEventListener: vi.fn(), speaking: false, pending: false,
    })
    area = 'phonics'
    render(<SocraticChat />)
    await screen.findByRole('dialog', { name: 'Sound Time' })
    const watchLine = 'Listen: kuh, ah, tuh. Put the sounds together: cat!'
    await waitFor(() => expect(spokenByBede()).toContain(watchLine))
    fireEvent.click(screen.getByRole('button', { name: 'Hear it again' }))
    await waitFor(() => expect(spokenByBede().filter((s) => s === watchLine).length).toBe(2))
    expect(deviceSpoken).toEqual([])
  })

  it('does not read the turn aloud in Bede’s voice after the round opens', async () => {
    // The stream finishes AFTER the round has opened: the end-of-turn speech
    // must not then read the card over the round. Only the round's own lines
    // are spoken.
    area = 'phonics'
    render(<SocraticChat />)
    await screen.findByRole('dialog', { name: 'Sound Time' })
    await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
    expect(spokenByBede().some((s) => s.includes('play with sounds'))).toBe(false)
  })

  it('asks for a lesson without ear-only questions when Bede’s voice is off', async () => {
    act(() => { useSessionStore.getState().setSessionConfig({ ...CONFIG, voice_narration_enabled: false } as SessionConfig) })
    area = 'phonics'
    render(<SocraticChat />)
    await screen.findByRole('dialog', { name: 'Sound Time' })
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/k2-practice/'))).toBe(true))
    const lessonUrls = fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes('/phonics/lesson'))
    expect(lessonUrls.every((u) => u.endsWith('/phonics/lesson?audio=false'))).toBe(true)
    expect(spokenByBede()).toEqual([])
  })

  it('opens the math round for area "math", which loads its lesson from the math route', async () => {
    area = 'math'
    render(<SocraticChat />)
    expect(await screen.findByRole('dialog', { name: 'Number Time' })).toBeTruthy()
    const urls = fetchMock.mock.calls.map(([u]) => String(u))
    expect(urls.some((u) => u.includes('/k2-practice/Ada/math/lesson'))).toBe(true)
    expect(urls.some((u) => u.includes('/phonics/lesson'))).toBe(false)
    expect(screen.queryByRole('dialog', { name: 'Sound Time' })).toBeNull()
    // Closing returns to the chat; the math card reopens the math round, not phonics.
    fireEvent.click(screen.getByRole('button', { name: 'Back to Bede' }))
    expect(screen.queryByRole('dialog', { name: 'Number Time' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Start Sound Time' })).toBeNull()
    fireEvent.click(await screen.findByRole('button', { name: 'Start Number Time' }))
    expect(await screen.findByRole('dialog', { name: 'Number Time' })).toBeTruthy()
  })

  it("speaks the math round in Bede's own voice, never an on-device or default voice", async () => {
    // Owner direction 2026-11-18: Number Time speaks in Bede's natural voice,
    // the same /tutor/speak path the chat uses, and defaults to nothing else.
    const deviceSpoken: string[] = []
    class Utterance { text: string; lang = ''; voice: unknown = null; rate = 1; pitch = 1
      constructor(text: string) { this.text = text } }
    vi.stubGlobal('SpeechSynthesisUtterance', Utterance)
    vi.stubGlobal('speechSynthesis', {
      speak: (u: Utterance) => deviceSpoken.push(u.text), cancel: vi.fn(), pause: vi.fn(), resume: vi.fn(),
      getVoices: () => [{ name: 'Daniel', lang: 'en-GB', localService: true }],
      addEventListener: vi.fn(), removeEventListener: vi.fn(), speaking: false, pending: false,
    })
    area = 'math'
    render(<SocraticChat />)
    await screen.findByRole('dialog', { name: 'Number Time' })
    const watchLine = '5 red and 3 yellow. I count them all: 8.'
    await waitFor(() => expect(spokenByBede()).toContain(watchLine))
    await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
    expect(deviceSpoken).toEqual([])
  })

  it('reopens the right round from a stored card by the card prefix the server writes', () => {
    // The stored card keeps no area, so the chat tells math from phonics by
    // the server's locale-independent prefix. Both copies must agree.
    const chat = readFileSync(join(__dirname, 'SocraticChat.tsx'), 'utf8')
    const server = readFileSync(join(__dirname, '../../../homeschool-api/services/k2_practice/__init__.py'), 'utf8')
    const ts = chat.match(/const MATH_CARD_PREFIX = '\\u\{([0-9A-F]+)\} '/)?.[1]
    const py = server.match(/"math": "\\U([0-9A-F]{8}) "/)?.[1]
    expect(ts).toBeTruthy()
    expect(parseInt(ts!, 16)).toBe(parseInt(py!, 16))
    expect(MATH_CARD.codePointAt(0)).toBe(parseInt(py!, 16))
  })

  it('opens nothing for an area that is not built', async () => {
    area = 'spelling'
    render(<SocraticChat />)
    await screen.findAllByText(/Sound Time/)
    await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
    expect(screen.queryByRole('dialog', { name: 'Sound Time' })).toBeNull()
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/k2-practice/'))).toBe(false)
  })
})

// ── Installed Bede with no working voice: text-first, never another voice ──

const TOGETHER_LESSON = {
  ...LESSON,
  together: [{
    phase: 'together', index: 0, prompt: { key: 'read_word_choice', args: {} },
    display: { kind: 'word', word: 'sun', graphemes: [{ text: 's', sound: 'sss' }, { text: 'u', sound: 'uh' }, { text: 'n', sound: 'nnn' }] },
    choice_kind: 'picture', choices: ['sun', 'pig'],
  }],
}

/** Everything the browser's own speech engine was asked to say. */
function trapBrowserSpeech(): string[] {
  const said: string[] = []
  class Utterance { text: string; constructor(text: string) { this.text = text } }
  vi.stubGlobal('SpeechSynthesisUtterance', Utterance)
  vi.stubGlobal('speechSynthesis', {
    speak: (u: Utterance) => said.push(u.text), cancel: vi.fn(), pause: vi.fn(), resume: vi.fn(),
    getVoices: () => [{ name: 'Daniel', lang: 'en-GB', localService: true }],
    addEventListener: vi.fn(), removeEventListener: vi.fn(), speaking: false, pending: false,
  })
  return said
}

/** Plays Sound Time through Watch and one Together answer, as a child would. */
async function playOneAnswer() {
  await screen.findByRole('dialog', { name: 'Sound Time' })
  fireEvent.click(await screen.findByRole('button', { name: 'Let’s try one' }))
  fireEvent.click(await screen.findByRole('button', { name: 'sun' }))
  expect(await screen.findByText('Yes, that’s it!')).toBeTruthy()
}

/** Nothing on screen tells the child about the voice, a provider or a key. */
function expectNoVoiceErrorShown() {
  const VOICE_TROUBLE = /OpenAI|API key|speech service|voice (is )?(unavailable|not (set up|configured))|couldn.t (speak|play)|narration/i
  expect(document.body.textContent ?? '').not.toMatch(VOICE_TROUBLE)
  for (const alert of screen.queryAllByRole('alert')) expect(alert.textContent ?? '').not.toMatch(VOICE_TROUBLE)
}

describe("installed Bede with no working voice", () => {
  it.each([
    ['no voice set up', { configured: false, where: null, available: false }],
    ['Piper set up but not answering', { configured: true, where: 'local', available: false }],
  ] as const)('%s: the round and chat carry on, nothing is spoken, nothing is sent', async (_name, status) => {
    voiceStatus = status
    lessonFor = () => TOGETHER_LESSON
    const browser = trapBrowserSpeech()
    area = 'phonics'
    render(<SocraticChat />)
    await playOneAnswer()
    // Without a voice the round asks for no ear-only questions.
    const lessonUrls = fetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes('/phonics/lesson?'))
    expect(lessonUrls.length).toBeGreaterThan(0)
    expect(lessonUrls).toEqual(lessonUrls.map(() => expect.stringMatching(/audio=false$/)))
    // Back to the chat, which still works.
    fireEvent.click(screen.getByRole('button', { name: 'Back to Bede' }))
    expect(screen.queryByRole('dialog', { name: 'Sound Time' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Start Sound Time' })).toBeTruthy()
    expect(spokenByBede()).toEqual([])
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/tutor/speak'))).toBe(false)
    expect(browser).toEqual([])
    expectNoVoiceErrorShown()
  })

  it('a status check that fails is silent too, never the browser voice', async () => {
    voiceStatus = 'fail'
    lessonFor = () => TOGETHER_LESSON
    const browser = trapBrowserSpeech()
    area = 'phonics'
    render(<SocraticChat />)
    await playOneAnswer()
    expect(spokenByBede()).toEqual([])
    expect(browser).toEqual([])
    expectNoVoiceErrorShown()
  })

  it('a provider error: lines are tried in Bede’s voice, fail quietly, and the round goes on', async () => {
    lessonFor = () => TOGETHER_LESSON
    const browser = trapBrowserSpeech()
    area = 'phonics'
    render(<SocraticChat />)
    await playOneAnswer()
    await waitFor(() => expect(spokenByBede().length).toBeGreaterThan(0))
    expect(browser).toEqual([])
    expectNoVoiceErrorShown()
  })

  it('a line that never comes back does not hold the round up', async () => {
    speakAnswer = 'hang'
    lessonFor = () => TOGETHER_LESSON
    const browser = trapBrowserSpeech()
    area = 'phonics'
    render(<SocraticChat />)
    await playOneAnswer()
    expect(browser).toEqual([])
    expectNoVoiceErrorShown()
  })

  it('only the round’s own fixed lines go to Bede’s voice, never what the child chose', async () => {
    lessonFor = () => TOGETHER_LESSON
    area = 'phonics'
    render(<SocraticChat />)
    await playOneAnswer()
    await waitFor(() => expect(spokenByBede()).toContain('Yes, that’s it!'))
    const fixed = new Set([
      'Listen: kuh, ah, tuh. Put the sounds together: cat!', // Watch
      'Read the word. Tap its picture.', // Together prompt
      'Yes, that’s it!', // feedback
    ])
    for (const line of spokenByBede()) expect(fixed.has(line), `unexpected line sent: ${line}`).toBe(true)
    expect(spokenByBede()).not.toContain('sun')
  })
})
