/**
 * A message longer than the server accepts is never sent. It used to go out,
 * come back refused, and reach the child as "we lost the connection", which
 * was untrue and invited resending the same message forever. Now the words
 * stay in the box and the child is told plainly what to do.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import type { SessionConfig } from '../types'
import SocraticChat, { MAX_CHILD_MESSAGE_CHARS } from './SocraticChat'

const CONFIG = {
  student_name: 'Ada',
  grade: '4',
  grade_stage: '3-5',
  subjects: ['living_books'],
} as unknown as SessionConfig

// The opener's request: any refusal keeps it quiet; what matters is that no
// FURTHER request is made for the over-long message.
const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) } as unknown as Response)

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

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

const tutorCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).includes('/tutor/chat')).length

async function typeAndSend(text: string) {
  render(<SocraticChat />)
  const box = (await screen.findAllByRole('textbox')).pop() as HTMLTextAreaElement
  await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
  const before = tutorCalls()
  const connectionNotices = screen.queryAllByText(/lost the connection|check your connection/i).length
  fireEvent.change(box, { target: { value: text } })
  await act(async () => { fireEvent.keyDown(box, { key: 'Enter', code: 'Enter' }) })
  return { box, before, connectionNotices }
}

describe('a message longer than the server accepts', () => {
  it('is not sent, keeps the words, and says so plainly', async () => {
    const long = 'The river flooded. '.repeat(200).slice(0, MAX_CHILD_MESSAGE_CHARS + 50)
    const { box, before, connectionNotices } = await typeAndSend(long)
    expect(await screen.findByText(/longer than one message can be \(2000 characters\)/)).toBeTruthy()
    expect(tutorCalls()).toBe(before)
    expect(box.value).toBe(long.trim())
    // The opener's own (mocked) failure may already show one; this send adds none.
    expect(screen.queryAllByText(/lost the connection|check your connection/i).length).toBe(connectionNotices)
  })

  it('a message exactly at the limit is still sent', async () => {
    const { before } = await typeAndSend('a'.repeat(MAX_CHILD_MESSAGE_CHARS))
    await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
    expect(tutorCalls()).toBe(before + 1)
    expect(screen.queryByText(/longer than one message can be/)).toBeNull()
  })

  it('says it in Spanish too', async () => {
    i18n.changeLanguage('es')
    await typeAndSend('x'.repeat(MAX_CHILD_MESSAGE_CHARS + 1))
    expect(await screen.findByText(/más largo de lo que cabe en un mensaje \(2000 caracteres\)/)).toBeTruthy()
  })
})

describe('the limit is the server’s own', () => {
  it('matches TutorRequest.child_message max_length in models/schemas.py', () => {
    const schemas = readFileSync(resolve(__dirname, '../../../homeschool-api/models/schemas.py'), 'utf8')
    const m = schemas.match(/child_message:\s*str\s*=\s*Field\([^)]*max_length=(\d+)/)
    expect(m, 'TutorRequest.child_message no longer declares a max_length').not.toBeNull()
    expect(Number(m![1])).toBe(MAX_CHILD_MESSAGE_CHARS)
  })
})
