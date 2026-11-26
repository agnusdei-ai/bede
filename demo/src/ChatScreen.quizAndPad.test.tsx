/**
 * Two moments where Bede has to stop and let the visitor work:
 *
 * - Starting a quiz from Practice Coach opens it on its own full-screen sheet.
 *   It used to be added above the whole conversation, out of sight, so it
 *   looked as if Start quiz had gone straight back to the chat. While it is
 *   open Bede does not talk or carry on, and finishing hands the result to
 *   Bede, who picks the lesson up from it.
 * - The writing pad Bede invites the visitor to opens only once Bede has
 *   finished speaking his turn, never under his voice.
 */
import { createRef } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { ChatScreen } from './App'
import type { StreamChunk } from './api'
import i18n from './i18n'

// Practice Coach's own drafting is tested in DemoQuizBuilder.test.tsx; here
// it only needs to start a quiz, exactly as its Start quiz button does.
vi.mock('./DemoPracticeCoach', () => ({
  default: ({ onStartQuiz, onClose }: { onStartQuiz: (t: string, q: unknown[]) => void; onClose: () => void }) => (
    <button type="button" onClick={() => {
      onStartQuiz('Leaves quiz', [{ type: 'short_answer', prompt: 'What is 2 + 2?', options: [], answer: '4' }])
      onClose()
    }}>start-the-quiz</button>
  ),
}))
// The pad itself needs a real canvas; what is under test is WHEN it opens.
vi.mock('./HandwritingCanvas', () => ({ default: () => <div data-testid="writing-pad" /> }))

let releaseSpeech: (() => void) | null = null
vi.mock('./api', async (importActual) => ({
  ...(await importActual<typeof import('./api')>()),
  speakViaBackend: () => new Promise((resolve) => {
    releaseSpeech = () => resolve({ audio: null, configured: true })
  }),
}))

type RunChat = Parameters<typeof ChatScreen>[0]['runChat']

function screenWith(runChat: RunChat) {
  return (
    <ChatScreen
      displayName="Sam" grade="4" subjects={['nature_study']} runChat={runChat}
      token="demo-token" code="ABC123" speakToken="demo-token" header={null}
      onFinishDemo={vi.fn()} onSessionInvalid={vi.fn()}
      sessionStateRef={createRef() as never} sessionStartedAt={Date.now()}
    />
  )
}

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
  localStorage.clear()
  releaseSpeech = null
  Element.prototype.scrollIntoView = vi.fn()
})
afterEach(() => { cleanup(); sessionStorage.clear(); localStorage.clear() })

describe('a quiz started from Practice Coach', () => {
  it('opens on its own screen, Bede waits, and the result goes to Bede when it is done', async () => {
    const sent: string[] = []
    const runChat: RunChat = async function* (_s, _h, message) {
      sent.push(message)
      yield { type: 'text', content: 'Hello.' } as StreamChunk
      yield { type: 'done' } as StreamChunk
    }
    render(screenWith(runChat))
    await waitFor(() => expect(sent.length).toBe(1))  // the subject opener
    await act(async () => { releaseSpeech?.() })

    fireEvent.click(screen.getByRole('button', { name: 'Practice Coach' }))
    fireEvent.click(screen.getByText('start-the-quiz'))

    const sheet = await screen.findByRole('dialog', { name: 'Leaves quiz' })
    expect(sheet.textContent).toContain('What is 2 + 2?')

    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    fireEvent.click(await screen.findByRole('button', { name: 'See how it went' }))
    // Nothing was sent to Bede while the quiz had the screen.
    expect(sent.length).toBe(1)
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))

    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Leaves quiz' })).toBeNull())
    await waitFor(() => expect(sent).toContain('I finished the quiz "Leaves quiz" and got 1 of 1 right.'))
  })

  it('can be left without finishing, and nothing is sent', async () => {
    const sent: string[] = []
    const runChat: RunChat = async function* (_s, _h, message) {
      sent.push(message)
      yield { type: 'done' } as StreamChunk
    }
    render(screenWith(runChat))
    await waitFor(() => expect(sent.length).toBe(1))
    fireEvent.click(screen.getByRole('button', { name: 'Practice Coach' }))
    fireEvent.click(screen.getByText('start-the-quiz'))
    await screen.findByRole('dialog', { name: 'Leaves quiz' })
    fireEvent.click(screen.getByRole('button', { name: 'Back to the conversation' }))
    expect(screen.queryByRole('dialog', { name: 'Leaves quiz' })).toBeNull()
    expect(sent.length).toBe(1)
  })
})

describe('the writing pad Bede invites the visitor to', () => {
  it('waits until Bede has finished speaking, then opens', async () => {
    const runChat: RunChat = async function* () {
      yield { type: 'text', content: 'Look closely at your leaf.' } as StreamChunk
      yield { type: 'tool', tool: 'invite_handwriting', content: '✏️ *Sketch the leaf* — Draw it.' } as StreamChunk
      yield { type: 'done' } as StreamChunk
    }
    render(screenWith(runChat))
    expect(await screen.findByText(/Sketch the leaf/)).toBeTruthy()
    await waitFor(() => expect(releaseSpeech).not.toBeNull())
    // Long enough for the lazily loaded pad to have appeared if it were going to.
    await new Promise((r) => setTimeout(r, 500))
    expect(screen.queryByTestId('writing-pad')).toBeNull()
    await act(async () => { releaseSpeech!() })
    expect(await screen.findByTestId('writing-pad')).toBeTruthy()
  })
})

describe('useCanvasAfterSpeech', () => {
  it('is the same file in the app and the demo', () => {
    const demo = readFileSync(join(__dirname, 'useCanvasAfterSpeech.ts'), 'utf8')
    const app = readFileSync(join(__dirname, '../../homeschool-tutor/src/hooks/useCanvasAfterSpeech.ts'), 'utf8')
    expect(demo).toBe(app)
  })
})
