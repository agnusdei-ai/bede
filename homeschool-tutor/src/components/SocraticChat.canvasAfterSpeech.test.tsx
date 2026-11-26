/**
 * Bede's invite_handwriting card opens the writing pad only once Bede has
 * finished speaking his turn. It used to open the moment the card arrived, so
 * the pad was on screen while Bede was still reading the instructions aloud.
 * Drives the real SocraticChat stream consumer and the real voice hook.
 */
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import type { SessionConfig } from '../types'
import SocraticChat from './SocraticChat'
import { resetVoiceGateForTests } from '../hooks/useTextToSpeech'

// The pad itself needs a real canvas; what is under test is WHEN it opens.
vi.mock('./HandwritingCanvas', () => ({ default: () => <div data-testid="writing-pad" /> }))

const CONFIG = {
  student_name: 'Ada', grade: '4', grade_stage: '3-5', subjects: ['nature_study'],
} as unknown as SessionConfig

const CARD = '✏️ *Sketch the leaf* — Draw the leaf you found and label its edge.'

function sse(chunks: object[]): Response {
  const body = chunks.map((c) => `data: ${JSON.stringify(c)}\n\n`).join('')
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

let voiceAvailable = true
let releaseSpeech: (() => void) | null = null
const fetchMock = vi.fn(async (url: string) => {
  const u = String(url)
  if (u.includes('/tutor/chat')) {
    return sse([
      { type: 'text', content: 'Look closely at your leaf.' },
      { type: 'tool', tool: 'invite_handwriting', content: CARD },
      { type: 'done' },
    ])
  }
  if (u.includes('/tutor/voice')) {
    return new Response(JSON.stringify({ configured: voiceAvailable, where: 'local', available: voiceAvailable }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  if (u.includes('/tutor/speak')) {
    // Bede is "speaking" until the test lets the line finish.
    return new Promise<Response>((resolve) => {
      releaseSpeech = () => resolve(new Response(null, { status: 204, headers: { 'X-TTS-Configured': 'True' } }))
    })
  }
  return new Response('{}', { status: 404 })
})

const padIsOpen = () => screen.queryByTestId('writing-pad') !== null

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
  fetchMock.mockClear()
  vi.stubGlobal('fetch', fetchMock)
  resetVoiceGateForTests()
  voiceAvailable = true
  releaseSpeech = null
  Element.prototype.scrollIntoView = vi.fn()
  act(() => {
    useSessionStore.getState().logout()
    useSessionStore.getState().setAuth('child-token', 'child')
    useSessionStore.getState().setSessionConfig(CONFIG)
    useSessionStore.getState().startSession()
  })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStorage.clear() })

describe('the writing pad Bede invites the child to', () => {
  it('waits until Bede has finished speaking, then opens', async () => {
    render(<SocraticChat />)
    // The card is in the chat and Bede has started reading the turn aloud.
    expect(await screen.findByText(/Sketch the leaf/)).toBeTruthy()
    await waitFor(() => expect(releaseSpeech).not.toBeNull())
    // Still speaking: no pad over his voice.
    await new Promise((r) => setTimeout(r, 50))
    expect(padIsOpen()).toBe(false)
    await act(async () => { releaseSpeech!() })
    await waitFor(() => expect(padIsOpen()).toBe(true))
  })

  it('opens as soon as the turn ends when there is no voice to wait for', async () => {
    voiceAvailable = false
    render(<SocraticChat />)
    expect(await screen.findByText(/Sketch the leaf/)).toBeTruthy()
    await waitFor(() => expect(padIsOpen()).toBe(true))
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/tutor/speak'))).toBe(false)
  })
})
