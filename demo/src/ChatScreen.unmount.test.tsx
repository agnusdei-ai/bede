/**
 * A demo lesson turn must not outlive the chat screen: leaving it (logout,
 * another screen) cancels the turn in flight. The cancel is deferred one
 * tick so development StrictMode's immediate remount keeps the opening
 * message. Mirrors homeschool-tutor's SocraticChat.unmount.test.tsx.
 */
import { StrictMode, createRef } from 'react'
import { cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ChatScreen } from './App'
import type { StreamChunk } from './api'
import i18n from './i18n'

type RunChat = Parameters<typeof ChatScreen>[0]['runChat']

function screenWith(runChat: RunChat) {
  return (
    <ChatScreen
      displayName="Sam" grade="2" subjects={['living_books']} runChat={runChat}
      token="demo-token" code="ABC123" header={null}
      onFinishDemo={vi.fn()} onSessionInvalid={vi.fn()}
      sessionStateRef={createRef() as never} sessionStartedAt={Date.now()}
    />
  )
}

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
  localStorage.clear()
  Element.prototype.scrollIntoView = vi.fn()
})
afterEach(() => { cleanup(); sessionStorage.clear(); localStorage.clear() })

describe('leaving the demo chat ends the turn in flight', () => {
  it('aborts the turn when the screen closes', async () => {
    const signals: AbortSignal[] = []
    const runChat: RunChat = async function* (_s, _h, _m, _d, signal) {
      signals.push(signal)
      await new Promise((_, reject) => signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))
      yield { type: 'done' } as StreamChunk
    }
    const { unmount } = render(screenWith(runChat))
    await waitFor(() => expect(signals.length).toBe(1))
    expect(signals[0].aborted).toBe(false)
    unmount()
    await waitFor(() => expect(signals[0].aborted).toBe(true))
  })

  it('keeps the opening message when development StrictMode remounts the chat', async () => {
    let calls = 0
    const runChat: RunChat = async function* (_s, _h, _m, _d, signal) {
      calls += 1
      await new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        setTimeout(resolve, 50)
      })
      yield { type: 'text', content: 'Good morning' } as StreamChunk
      yield { type: 'done' } as StreamChunk
    }
    const { findByText } = render(<StrictMode>{screenWith(runChat)}</StrictMode>)
    await findByText(/Good morning/)
    expect(calls).toBe(1)
  })
})
