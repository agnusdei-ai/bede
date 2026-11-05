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
import PracticeDelivery from './PracticeDelivery'

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
    render(<PracticeDelivery token="synthetic-token" studentName="Synthetic Learner" onAnswer={onAnswer} />)

    expect(await screen.findByText('A duck swimming. Quid agit?')).toBeTruthy()
    expect(screen.queryByText(/Anas natat/)).toBeNull()
    fireEvent.change(screen.getByRole('textbox', { name: 'Your answer' }), {
      target: { value: 'Anas natat.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send my answer to Bede' }))

    await waitFor(() => expect(mocks.recordPracticeOutcome).toHaveBeenCalledWith(
      'synthetic-token', 'Synthetic Learner', 21, 0, 'Anas natat.',
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
    render(<PracticeDelivery token="synthetic-token" studentName="Synthetic Learner" onAnswer={vi.fn()} />)
    expect(await screen.findByText('What time does the clock show?')).toBeTruthy()
    expect(screen.getByRole('img', { name: /A clock/ }).querySelector('svg')).not.toBeNull()
  })

  it('does not send an answer to Bede when outcome recording fails', async () => {
    mocks.recordPracticeOutcome.mockRejectedValue(new Error('failed'))
    const onAnswer = vi.fn()
    render(<PracticeDelivery token="synthetic-token" studentName="Synthetic Learner" onAnswer={onAnswer} />)
    await screen.findByText('A duck swimming. Quid agit?')
    fireEvent.change(screen.getByRole('textbox', { name: 'Your answer' }), {
      target: { value: 'Anas natat.' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send my answer to Bede' }))
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(onAnswer).not.toHaveBeenCalled()
  })
})
