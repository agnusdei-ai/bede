import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  fetchPracticeDelivery: vi.fn(),
  recordPracticeOutcome: vi.fn(),
}))
vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return { ...original, ...mocks }
})

import i18n from '../i18n'
import PracticeDelivery, { MAX_PRACTICE_ANSWER_CHARS } from './PracticeDelivery'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('approved practice delivery', () => {
  beforeEach(() => {
    i18n.changeLanguage('en')
    mocks.fetchPracticeDelivery.mockResolvedValue([{
      id: 21,
      items: [{ index: 0, prompt: 'A duck swimming. Quid agit?', hint: 'Think of the verb.' }],
      completed_indices: [],
    }])
    mocks.recordPracticeOutcome.mockResolvedValue({ recorded: true, already_recorded: false })
  })

  afterEach(() => {
    cleanup()
    vi.resetAllMocks()
  })

  it('shows only the approved prompt, records the response, and sends it into Socratic chat', async () => {
    const onAnswer = vi.fn()
    render(<PracticeDelivery token="sample-token" studentName="Sample Learner" onAnswer={onAnswer} />)

    expect(await screen.findByText('A duck swimming. Quid agit?')).toBeTruthy()
    expect(screen.queryByText(/Anas natat/)).toBeNull()
    fireEvent.change(screen.getByRole('textbox', { name: 'Your answer' }), {
      target: { value: 'Anas natat.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send my answer to Bede' }))

    await waitFor(() => expect(mocks.recordPracticeOutcome).toHaveBeenCalledWith(
      'sample-token', 'Sample Learner', 21, 0, 'Anas natat.',
    ))
    expect(onAnswer).toHaveBeenCalledWith('A duck swimming. Quid agit?', 'Anas natat.')
    expect(await screen.findByRole('button', { name: 'Check for approved practice' })).toBeTruthy()
  })

  it('shows the picture a picture problem needs', async () => {
    mocks.fetchPracticeDelivery.mockResolvedValue([{
      id: 22,
      items: [{ index: 0, prompt: 'What time does the clock show?', hint: '', diagram: { kind: 'clock', hour: 4, minute: 30 } }],
      completed_indices: [],
    }])
    render(<PracticeDelivery token="sample-token" studentName="Sample Learner" onAnswer={vi.fn()} />)
    expect(await screen.findByText('What time does the clock show?')).toBeTruthy()
    expect(screen.getByRole('img', { name: /A clock/ }).querySelector('svg')).not.toBeNull()
  })

  it('does not send an answer to Bede when outcome recording fails', async () => {
    mocks.recordPracticeOutcome.mockRejectedValue(new Error('failed'))
    const onAnswer = vi.fn()
    render(<PracticeDelivery token="sample-token" studentName="Sample Learner" onAnswer={onAnswer} />)
    await screen.findByText('A duck swimming. Quid agit?')
    fireEvent.change(screen.getByRole('textbox', { name: 'Your answer' }), {
      target: { value: 'Anas natat.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send my answer to Bede' }))
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(onAnswer).not.toHaveBeenCalled()
  })
})


describe('an answer while Bede is still replying', () => {
  beforeEach(() => {
    i18n.changeLanguage('en')
    mocks.fetchPracticeDelivery.mockResolvedValue([{
      id: 21,
      items: [{ index: 0, prompt: 'A duck swimming. Quid agit?', hint: 'Think of the verb.' }],
      completed_indices: [],
    }])
    mocks.recordPracticeOutcome.mockResolvedValue({ recorded: true, already_recorded: false })
  })
  afterEach(() => { cleanup(); vi.resetAllMocks() })

  // The chat drops anything sent while Bede streams. Before this, the answer
  // was recorded and the card moved on, but Bede never heard it: found by the
  // Firefox browser journey, where the opener was still streaming.
  it('cannot be sent until Bede has finished, so it is never recorded without reaching Bede', async () => {
    const onAnswer = vi.fn()
    const { rerender } = render(<PracticeDelivery token="t" studentName="Sample Learner" onAnswer={onAnswer} busy />)
    await screen.findByText('A duck swimming. Quid agit?')
    fireEvent.change(screen.getByRole('textbox', { name: 'Your answer' }), { target: { value: 'Anas natat.' } })
    const button = screen.getByRole('button', { name: /Send my answer to Bede/ }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    fireEvent.click(button)
    expect(mocks.recordPracticeOutcome).not.toHaveBeenCalled()
    expect(onAnswer).not.toHaveBeenCalled()

    rerender(<PracticeDelivery token="t" studentName="Sample Learner" onAnswer={onAnswer} busy={false} />)
    expect(button.disabled).toBe(false)
    fireEvent.click(button)
    await waitFor(() => expect(onAnswer).toHaveBeenCalledWith('A duck swimming. Quid agit?', 'Anas natat.'))
    expect(mocks.recordPracticeOutcome).toHaveBeenCalledTimes(1)
  })

  it('limits the answer box to what the server accepts', async () => {
    render(<PracticeDelivery token="t" studentName="Sample Learner" onAnswer={vi.fn()} />)
    const box = await screen.findByRole('textbox', { name: 'Your answer' }) as HTMLTextAreaElement
    expect(box.maxLength).toBe(MAX_PRACTICE_ANSWER_CHARS)
    const model = readFileSync(resolve(__dirname, '../../../homeschool-api/models/practice.py'), 'utf8')
    const m = model.match(/class PracticeOutcomeRequest[\s\S]*?response:\s*str\s*=\s*Field\([^)]*max_length=(\d+)/)
    expect(m, 'PracticeOutcomeRequest.response no longer declares a max_length').not.toBeNull()
    expect(Number(m![1])).toBe(MAX_PRACTICE_ANSWER_CHARS)
  })

  it('the chat passes "Bede is replying" to the card', () => {
    const chat = readFileSync(resolve(__dirname, './SocraticChat.tsx'), 'utf8')
    expect(chat).toMatch(/<PracticeDelivery[\s\S]*?busy=\{isStreaming\}/)
  })
})


describe('the practice card leaves room for the conversation', () => {
  beforeEach(() => {
    i18n.changeLanguage('en')
    mocks.fetchPracticeDelivery.mockResolvedValue([{ id: 21, items: [{ index: 0, prompt: 'Quid agit?', hint: 'verb' }], completed_indices: [] }])
  })
  afterEach(() => { cleanup(); vi.resetAllMocks() })

  // jsdom has no layout, so this pins the classes; the measured guarantee is
  // the browser journey's conversation_visible_at_200 check.
  it('is height-capped and scrolls on its own', async () => {
    render(<PracticeDelivery token="t" studentName="Sample Learner" onAnswer={vi.fn()} />)
    const card = await screen.findByRole('region', { name: /practice question/i })
    expect(card.className).toMatch(/max-h-\[25dvh\]/)
    expect(card.className).toMatch(/overflow-y-auto/)
    expect(card.className).toMatch(/shrink-0/)
  })
})
