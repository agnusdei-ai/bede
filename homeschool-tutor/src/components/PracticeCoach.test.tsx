import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  fetchPracticePacks: vi.fn(),
  fetchReadingRoute: vi.fn(),
  readPracticePhotos: vi.fn(),
  confirmPracticeReading: vi.fn(),
  planPractice: vi.fn(),
  approvePracticeSet: vi.fn(),
  discardPracticeSet: vi.fn(),
}))
vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return { ...original, ...mocks }
})

import i18n from '../i18n'
import PracticeCoach, { PRACTICE_ACCEPT, flaggedCount, teacherCount, toBase64Payload } from './PracticeCoach'
import type { GradedAssessment } from '../services/api'

const assessment: GradedAssessment = {
  subject: 'latin',
  sections: [
    {
      label: 'Part 1', instructions: 'Answer in complete Latin sentences.', required_format: 'complete_sentence',
      word_bank: ['avis', 'anas', 'natat', 'est'],
      items: [
        { number: 5, prompt: 'Quid est?', stimulus: 'picture: duck on water', student_response: 'avis',
          teacher_mark: 'incorrect', teacher_correction: 'anas', confidence: 0.93 },
        { number: 6, prompt: 'Quid agit?', student_response: 'natat', teacher_mark: 'correct', confidence: 0.9 },
      ],
    },
    {
      label: 'Part 2', instructions: '', required_format: 'single_word', word_bank: ['vīta'],
      items: [
        { number: 4, prompt: '… est ___.', student_response: 'vīta', teacher_mark: 'correct',
          confidence: 0.7, ask_parent: 'The macron on the i is unclear' },
      ],
    },
    {
      label: 'Part 3', instructions: '', required_format: 'color_fill', word_bank: [],
      items: [{ number: 1, prompt: 'Alba', student_response: 'uncolored', teacher_mark: 'correct', confidence: 0.9 }],
    },
  ],
}

const plan = {
  summary: '3 of 4, by the teacher\'s marks. What to work on: Part 1 #5, wrote avis (bird) for anas (duck).',
  diagnosis: { errors: [
    { item_ref: 'Part 1 #5', category: 'latin.vocab.hypernym_substitution', evidence: 'wrote avis (bird) for anas (duck)', audience: 'parent_and_child' },
    { item_ref: 'Part 1', category: 'core.instruction.format', evidence: 'single words where sentences were asked', audience: 'parent_only' },
  ], strengths: [{ category: 'latin.colors', note: 'Matched every colour word to its colour' }], ask_parent: [] },
  practice_set: {
    targets: ['latin.vocab.hypernym_substitution'], mode: 'drill', est_minutes: 6,
    items: [
      { kind: 'drill', target: 'x', prompt: 'A duck flying. Quid est? Quid agit?', expected_answer: 'Anas est. Anas volat.', hint: '' },
      { kind: 'retrieval', target: 'x', prompt: 'A bird drinking. Quid est? Quid agit?', expected_answer: 'Avis est. Avis bibit.', hint: '' },
    ],
    parent_script: 'Say: is there a more exact word?', recheck_schedule: ['+3d', '+7d'],
  },
  set_id: 11, status: 'draft',
}

const png = () => new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], 'page1.png', { type: 'image/png' })

beforeEach(() => {
  i18n.changeLanguage('en')
  mocks.fetchPracticePacks.mockResolvedValue([{ id: 'latin', display_name: 'Latin' }])
  mocks.fetchReadingRoute.mockResolvedValue({ local_available: true, cloud_provider: 'openai' })
  mocks.readPracticePhotos.mockResolvedValue({
    id: 7, status: 'needs_review', assessment, ask_parent: ['Part 2 #4'],
    teacher_mark_count: { correct: 3, total: 4, source: 'teacher_marks' },
  })
  mocks.confirmPracticeReading.mockResolvedValue({})
  mocks.planPractice.mockResolvedValue(plan)
  mocks.approvePracticeSet.mockResolvedValue({ id: 11, status: 'approved' })
  mocks.discardPracticeSet.mockResolvedValue({ id: 11, status: 'discarded' })
})

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

async function openAndPick() {
  render(<PracticeCoach token="t" studentName="Alex" />)
  fireEvent.click(screen.getByRole('button', { name: 'Start' }))
  await screen.findByRole('option', { name: 'Latin' })
  fireEvent.change(screen.getByLabelText(/scanned PDF of the graded pages/), { target: { files: [png()] } })
}

async function readQuiz() {
  await openAndPick()
  fireEvent.click(screen.getByRole('button', { name: 'Read the quiz' }))
  await screen.findByText('3 of 4, by the teacher\'s marks')
}

describe('helpers', () => {
  it('sends bare base64, the same shape the handwriting canvas sends', () => {
    expect(toBase64Payload('data:image/png;base64,iVBORw0KGgo=')).toBe('iVBORw0KGgo=')
    expect(toBase64Payload('iVBORw0KGgo=')).toBe('iVBORw0KGgo=')
  })

  it('counts the teacher\'s marks and the readings still to settle', () => {
    expect(teacherCount(assessment)).toEqual({ correct: 3, total: 4 })
    expect(flaggedCount(assessment)).toBe(1)
  })
})

describe('where the photos go', () => {
  it('reads on the local model without asking for cloud consent', async () => {
    await openAndPick()
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.getByText(/running on this computer/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Read the quiz' }))
    await waitFor(() => expect(mocks.readPracticePhotos).toHaveBeenCalled())
    const body = mocks.readPracticePhotos.mock.calls[0][2]
    expect(body.cloud_consent).toBe(false)
    expect(body.pages[0].data).not.toMatch(/^data:/)
  })

  it('will not send pages to a cloud provider until the parent ticks consent', async () => {
    mocks.fetchReadingRoute.mockResolvedValue({ local_available: false, cloud_provider: 'openai' })
    await openAndPick()
    const read = screen.getByRole('button', { name: 'Read the quiz' }) as HTMLButtonElement
    expect(screen.getByText(/sent to openai/)).toBeTruthy()
    expect(read.disabled).toBe(true)
    fireEvent.click(read)
    expect(mocks.readPracticePhotos).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(read)
    await waitFor(() => expect(mocks.readPracticePhotos).toHaveBeenCalled())
    expect(mocks.readPracticePhotos.mock.calls[0][2].cloud_consent).toBe(true)
  })
})

describe('reviewing the reading', () => {
  it('blocks planning until every unsure reading is confirmed, then sends the settled reading', async () => {
    await readQuiz()
    expect(screen.getByText('The macron on the i is unclear')).toBeTruthy()
    const confirm = screen.getByRole('button', { name: 'Confirm and plan practice' }) as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Looks right' }))
    expect(confirm.disabled).toBe(false)
    fireEvent.click(confirm)
    await screen.findByText(/Practice set \(about 6 minutes\)/)
    const sent: GradedAssessment = mocks.confirmPracticeReading.mock.calls[0][3]
    expect(flaggedCount(sent)).toBe(0)
    expect(sent.sections[1].items[0].student_response).toBe('vīta')
    expect(mocks.planPractice).toHaveBeenCalledWith('t', 'Alex', 7)
  })

  it('lets the parent correct a misreading before it is saved', async () => {
    await readQuiz()
    fireEvent.change(screen.getByLabelText('Answer written for Part 1 #6'), { target: { value: 'volat' } })
    fireEvent.click(screen.getByRole('button', { name: 'Looks right' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and plan practice' }))
    await waitFor(() => expect(mocks.confirmPracticeReading).toHaveBeenCalled())
    expect(mocks.confirmPracticeReading.mock.calls[0][3].sections[0].items[1].student_response).toBe('volat')
  })
})

describe('approving', () => {
  async function toPlan() {
    await readQuiz()
    fireEvent.click(screen.getByRole('button', { name: 'Looks right' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm and plan practice' }))
    await screen.findByText(/Practice set/)
  }

  it('approves only the items the parent kept', async () => {
    await toPlan()
    fireEvent.click(screen.getByLabelText('Include item 2'))
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))
    await screen.findByText(/Approved\./)
    const [, , setId, sent] = mocks.approvePracticeSet.mock.calls[0]
    expect(setId).toBe(11)
    expect(sent.items.map((i: { prompt: string }) => i.prompt)).toEqual(['A duck flying. Quid est? Quid agit?'])
  })

  it('discards without saving anything for the child', async () => {
    await toPlan()
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }))
    await screen.findByText(/Discarded\./)
    expect(mocks.approvePracticeSet).not.toHaveBeenCalled()
  })

  it('separates what to work on from what is for the parent only', async () => {
    await toPlan()
    expect(screen.getByText('What to work on')).toBeTruthy()
    expect(screen.getByText('Part 1 #5: wrote avis (bird) for anas (duck)')).toBeTruthy()
    expect(screen.getByText('Just for you (not shown to your child)')).toBeTruthy()
    expect(screen.getByText('Part 1: single words where sentences were asked')).toBeTruthy()
    expect(screen.getByText('Matched every colour word to its colour')).toBeTruthy()
  })
})

it('starts over when the parent switches to another child', async () => {
  const { rerender } = render(<PracticeCoach token="t" studentName="Alex" />)
  fireEvent.click(screen.getByRole('button', { name: 'Start' }))
  await screen.findByRole('option', { name: 'Latin' })
  fireEvent.change(screen.getByLabelText(/scanned PDF of the graded pages/), { target: { files: [png()] } })
  fireEvent.click(screen.getByRole('button', { name: 'Read the quiz' }))
  await screen.findByText('3 of 4, by the teacher\'s marks')
  rerender(<PracticeCoach token="t" studentName="Bea" />)
  expect(screen.queryByText('3 of 4, by the teacher\'s marks')).toBeNull()
})

it('is written in Spanish for a Spanish session', async () => {
  i18n.changeLanguage('es')
  render(<PracticeCoach token="t" studentName="Alex" />)
  expect(screen.getByText('Práctica a partir de una prueba calificada')).toBeTruthy()
})

describe('PDF and iPhone uploads', () => {
  it('offers PDF, HEIC and HEIF in the file picker alongside JPEG and PNG', async () => {
    await openAndPick()
    const input = screen.getByLabelText(/scanned PDF of the graded pages/) as HTMLInputElement
    const accepted = input.accept.split(',')
    for (const kind of ['image/jpeg', 'image/png', 'application/pdf', '.pdf', 'image/heic', 'image/heif', '.heic', '.heif']) {
      expect(accepted).toContain(kind)
    }
    expect(input.accept).toBe(PRACTICE_ACCEPT)
    expect(input.multiple).toBe(true)
  })

  it('sends a picked PDF to the reader as bare base64, like any other page', async () => {
    render(<PracticeCoach token="t" studentName="Alex" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    await screen.findByRole('option', { name: 'Latin' })
    const pdf = new File([new TextEncoder().encode('%PDF-1.7 scan')], 'quiz.pdf', { type: 'application/pdf' })
    fireEvent.change(screen.getByLabelText(/scanned PDF of the graded pages/), { target: { files: [pdf] } })
    fireEvent.click(screen.getByRole('button', { name: 'Read the quiz' }))
    await waitFor(() => expect(mocks.readPracticePhotos).toHaveBeenCalled())
    const data = mocks.readPracticePhotos.mock.calls[0][2].pages[0].data as string
    expect(atob(data)).toBe('%PDF-1.7 scan')
    expect(data).not.toMatch(/^data:/)
  })

  it('says what is checked and refused, and does not overclaim about the photos (en)', async () => {
    await openAndPick()
    expect(screen.getByText(/PDF of scanned pages, 6 pages in all/)).toBeTruthy()
    expect(screen.getByText(/scripts, attachments, forms or a password are refused/)).toBeTruthy()
    expect(screen.getByText(/not saved to the database or a file by Bede; they are held in memory while the request runs/)).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/never the photos|virus-free|malware-free/i)
  })

  it('says the same in Spanish', async () => {
    i18n.changeLanguage('es')
    render(<PracticeCoach token="t" studentName="Alex" />)
    fireEvent.click(screen.getByRole('button', { name: /Comenzar|Empezar|Iniciar/ }))
    await screen.findByRole('option', { name: 'Latin' })
    expect(screen.getByText(/PDF de páginas escaneadas/)).toBeTruthy()
    expect(screen.getByText(/no guarda las fotos en la base de datos ni en un archivo/)).toBeTruthy()
  })
})
