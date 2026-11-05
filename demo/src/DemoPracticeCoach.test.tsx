import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import './i18n'
import type { DemoPracticeAssessment, DemoPracticeSetDraft } from './api'
import DemoPracticeCoach from './DemoPracticeCoach'
import DemoPracticeDelivery from './DemoPracticeDelivery'

const api = vi.hoisted(() => ({
  approveDemoPractice: vi.fn(),
  fetchDemoPracticePacks: vi.fn(),
  fetchDemoPracticeReadingRoute: vi.fn(),
  planDemoPractice: vi.fn(),
  readDemoPracticePhotos: vi.fn(),
}))

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  ...api,
}))

afterEach(cleanup)

const assessment: DemoPracticeAssessment = {
  subject: 'latin',
  sections: [{
    label: 'Vocabulary',
    instructions: 'Choose a word from the bank.',
    required_format: 'single_word',
    word_bank: ['amo', 'aqua'],
    items: [{
      number: 1,
      prompt: 'What does amo mean?',
      student_response: 'water',
      teacher_mark: 'incorrect',
      teacher_correction: 'love',
      confidence: 0.5,
      ask_parent: 'Check the teacher mark.',
    }],
  }],
}

const practiceSet: DemoPracticeSetDraft = {
  targets: ['vocabulary'],
  mode: 'retrieval',
  est_minutes: 5,
  items: [
    { kind: 'retrieval', target: 'vocabulary', prompt: 'Translate aqua.', expected_answer: 'water', hint: 'Think of a familiar word.' },
    { kind: 'retrieval', target: 'vocabulary', prompt: 'Translate amo.', expected_answer: 'I love.', hint: 'Think of affection.' },
  ],
  parent_script: 'Offer the hint only if needed.',
  recheck_schedule: ['+3d', '+7d'],
}

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchDemoPracticePacks.mockResolvedValue([{ id: 'latin', display_name: 'Latin' }])
  api.fetchDemoPracticeReadingRoute.mockResolvedValue({ local_available: true, cloud_provider: null })
  api.readDemoPracticePhotos.mockResolvedValue({
    id: 0,
    status: 'needs_review',
    assessment,
    ask_parent: ['Vocabulary #1: Check the teacher mark.'],
    teacher_mark_count: { correct: 0, total: 1, source: 'teacher_marks' },
  })
  api.planDemoPractice.mockResolvedValue({
    summary: 'Review the teacher-marked vocabulary error.',
    diagnosis: {
      errors: [{ item_ref: 'Vocabulary #1', category: 'meaning', evidence: 'The answer does not match the word.', audience: 'parent_and_child' }],
      strengths: [{ category: 'effort', note: 'The learner attempted the item.' }],
      ask_parent: [],
    },
    practice_set: practiceSet,
  })
  api.approveDemoPractice.mockImplementation(async (_token: string, value: DemoPracticeSetDraft) => ({
    approved: true,
    items: value.items.map(({ prompt, hint }, index) => ({ index, prompt, hint })),
  }))
})

describe('demo Practice Coach', () => {
  it.each([
    ['JPEG', 'image/jpeg', 'synthetic-jpeg'],
    ['PNG', 'image/png', 'synthetic-png'],
    ['scanned PDF', 'application/pdf', '%PDF-synthetic-scan'],
  ])('reads synthetic %s uploads, supports adult correction, and requires explicit approval', async (_label, mime, content) => {
    const onApproved = vi.fn()
    render(<DemoPracticeCoach token="synthetic-token" onClose={vi.fn()} onApproved={onApproved} />)

    await screen.findByRole('option', { name: 'Latin' })
    const input = screen.getByLabelText(/Choose up to/i)
    const file = new File([content], `synthetic.${mime === 'application/pdf' ? 'pdf' : mime === 'image/png' ? 'png' : 'jpg'}`, { type: mime })
    fireEvent.change(input, { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Read quiz' }))

    await waitFor(() => expect(api.readDemoPracticePhotos).toHaveBeenCalledOnce())
    expect(api.readDemoPracticePhotos).toHaveBeenCalledWith('synthetic-token', {
      subject: 'latin',
      pages: [{ data: btoa(content) }],
      cloud_consent: false,
    })
    expect(await screen.findByDisplayValue('water')).toBeTruthy()
    fireEvent.change(screen.getByLabelText("Learner's answer for Vocabulary #1"), { target: { value: 'amo' } })
    fireEvent.click(screen.getByRole('button', { name: 'Looks right' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm review and plan practice' }))

    await waitFor(() => expect(api.planDemoPractice).toHaveBeenCalledOnce())
    expect(api.planDemoPractice.mock.calls[0][1].sections[0].items[0]).toMatchObject({
      student_response: 'amo',
      ask_parent: null,
      confidence: 1,
    })
    expect(await screen.findByText('The learner attempted the item.')).toBeTruthy()
    expect(screen.getByText('water', { exact: false })).toBeTruthy()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include practice question 2' }))
    fireEvent.click(screen.getByRole('button', { name: 'Approve and start this practice' }))

    await waitFor(() => expect(onApproved).toHaveBeenCalledOnce())
    expect(api.approveDemoPractice.mock.calls[0][1].items).toEqual([practiceSet.items[0]])
    expect(onApproved.mock.calls[0][0]).toEqual([
      { index: 0, prompt: 'Translate aqua.', hint: 'Think of a familiar word.' },
    ])
    expect(onApproved.mock.calls[0][0][0]).not.toHaveProperty('expected_answer')
    expect(onApproved.mock.calls[0][0][0]).not.toHaveProperty('parent_script')
  })

  it('requires per-upload consent before sending pages to the cloud reader', async () => {
    api.fetchDemoPracticeReadingRoute.mockResolvedValue({ local_available: false, cloud_provider: 'OpenAI' })
    render(<DemoPracticeCoach token="synthetic-token" onClose={vi.fn()} onApproved={vi.fn()} />)
    await screen.findByText(/send these pages to OpenAI/i)
    expect(screen.getByText(/OpenAI may keep the page images for up to 30 days/)).toBeTruthy()
    expect(screen.getByText(/crop out anything you would rather not send/)).toBeTruthy()
    const picker = screen.getByLabelText(/Choose up to/i) as HTMLInputElement
    for (const kind of ['image/jpeg', 'image/png', 'image/webp', 'image/avif', 'application/pdf']) {
      expect(picker.accept.split(',')).toContain(kind)
    }
    expect(picker.accept).not.toMatch(/heic/i)
    fireEvent.change(screen.getByLabelText(/Choose up to/i), {
      target: { files: [new File(['synthetic'], 'synthetic.png', { type: 'image/png' })] },
    })
    expect(screen.getByRole('button', { name: 'Read quiz' })).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Read quiz' }))
    await waitFor(() => expect(api.readDemoPracticePhotos).toHaveBeenCalledWith('synthetic-token', expect.objectContaining({ cloud_consent: true })))
  })
})

describe('demo practice delivery', () => {
  it('records a submitted outcome in session state and sends only prompt and response to Bede', () => {
    const onAnswer = vi.fn()
    render(
      <DemoPracticeDelivery
        items={[{ index: 0, prompt: 'Translate aqua.', hint: 'Think of a familiar word.' }]}
        busy={false}
        onAnswer={onAnswer}
      />,
    )
    expect(screen.getByText('Translate aqua.')).toBeTruthy()
    expect(screen.queryByText('water')).toBeNull()
    fireEvent.change(screen.getByLabelText('Your response'), { target: { value: 'water' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send answer to Bede' }))
    expect(onAnswer).toHaveBeenCalledWith('Translate aqua.', 'water')
    expect(screen.getByRole('status').textContent).toContain('1')
    expect(within(screen.getByRole('status')).queryByText('water')).toBeNull()
  })
})
