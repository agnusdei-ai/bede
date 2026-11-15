/**
 * A lesson turn must not outlive the chat screen. Leaving the screen (logout,
 * another page, another learner) ends the request in flight, whether it is
 * still waiting for the server or already reading the reply, and stops the
 * retry loop in services/api.ts from sending it again.
 */
import { StrictMode } from 'react'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import type { SessionConfig } from '../types'
import SocraticChat from './SocraticChat'

const CONFIG = {
  student_name: 'Ada', grade: '4', grade_stage: '3-5', subjects: ['living_books'],
} as unknown as SessionConfig

const chatCalls = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.filter(([url]) => String(url).includes('/tutor/chat'))

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
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
  vi.useRealTimers()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

describe('leaving the chat ends the turn in flight', () => {
  it('aborts a request still waiting for the server', async () => {
    const fetchMock = vi.fn((_url: unknown, init?: RequestInit) => new Promise<Response>((_, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    vi.stubGlobal('fetch', fetchMock)
    const { unmount } = render(<SocraticChat />)
    await waitFor(() => expect(chatCalls(fetchMock).length).toBe(1))
    const signal = (chatCalls(fetchMock)[0][1] as RequestInit).signal!
    expect(signal.aborted).toBe(false)
    unmount()
    await waitFor(() => expect(signal.aborted).toBe(true))
  })

  it('stops reading a reply that is still streaming', async () => {
    let cancelled = false
    const body = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new TextEncoder().encode('data: {"type":"text","content":"Hello"}\n')) },
      cancel() { cancelled = true },
    })
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, body } as unknown as Response)
    vi.stubGlobal('fetch', fetchMock)
    const { unmount, findByText } = render(<SocraticChat />)
    await findByText(/Hello/)
    expect(cancelled).toBe(false)
    unmount()
    await waitFor(() => expect(cancelled).toBe(true))
  })

  it('does not send the turn again after the chat has gone', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Load failed'))
    vi.stubGlobal('fetch', fetchMock)
    const { unmount } = render(<SocraticChat />)
    await waitFor(() => expect(chatCalls(fetchMock).length).toBe(1))
    unmount()
    // The first retry would come one second later.
    await new Promise((r) => setTimeout(r, 1600))
    expect(chatCalls(fetchMock).length).toBe(1)
  })

  it('keeps the opening message when development StrictMode remounts the chat', async () => {
    const body = () => new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"type":"text","content":"Good morning"}\ndata: {"type":"done"}\n'))
        controller.close()
      },
    })
    const fetchMock = vi.fn((_url: unknown, init?: RequestInit) => new Promise<Response>((resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      setTimeout(() => resolve({ ok: true, status: 200, body: body() } as unknown as Response), 50)
    }))
    vi.stubGlobal('fetch', fetchMock)
    const { findByText } = render(<StrictMode><SocraticChat /></StrictMode>)
    await findByText(/Good morning/)
    expect(chatCalls(fetchMock).length).toBe(1)
  })

  it('ends the turn when the learner changes while the chat stays up, and opens the new lesson', async () => {
    const fetchMock = vi.fn((_url: unknown, init?: RequestInit) => new Promise<Response>((_, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    vi.stubGlobal('fetch', fetchMock)
    render(<SocraticChat />)
    await waitFor(() => expect(chatCalls(fetchMock).length).toBe(1))
    const first = (chatCalls(fetchMock)[0][1] as RequestInit)
    act(() => {
      useSessionStore.getState().setSessionConfig({ ...CONFIG, student_name: 'Ben' } as SessionConfig)
      useSessionStore.getState().startSession()
    })
    await waitFor(() => expect(first.signal!.aborted).toBe(true))
    await waitFor(() => expect(chatCalls(fetchMock).length).toBe(2))
    const second = JSON.parse(String((chatCalls(fetchMock)[1][1] as RequestInit).body))
    expect(second.session_config.student_name).toBe('Ben')
    expect(JSON.parse(String(first.body)).session_config.student_name).toBe('Ada')
  })

  it('writes nothing into a session that replaced its own', async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(new TextEncoder().encode('data: {"type":"text","content":"Hello Ada"}\n')) },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, body } as unknown as Response))
    const { unmount, findByText } = render(<SocraticChat />)
    await findByText(/Hello Ada/)
    // Logout, then another learner signs in and their first reply starts,
    // all before the old turn has finished winding down.
    unmount()
    act(() => {
      const store = useSessionStore.getState()
      store.logout()
      store.setAuth('other-token', 'child')
      store.setSessionConfig({ ...CONFIG, student_name: 'Ben' } as SessionConfig)
      store.startSession()
      store.startAssistantStream()
      store.appendAssistantChunk('Hello Ben')
    })
    await new Promise((r) => setTimeout(r, 300))
    const state = useSessionStore.getState()
    expect(state.isStreaming).toBe(true)
    const text = state.displayMessages.map((m) => m.content).join(' | ')
    expect(text).toContain('Hello Ben')
    expect(text).not.toContain('Hello Ada')
    expect(text).not.toMatch(/⚠️/)
  })

  it('a logout clears the streaming mark the cut-off turn can no longer clear', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})))
    const { unmount } = render(<SocraticChat />)
    await waitFor(() => expect(useSessionStore.getState().isStreaming).toBe(true))
    unmount()
    act(() => { useSessionStore.getState().logout() })
    expect(useSessionStore.getState().isStreaming).toBe(false)
  })
})
