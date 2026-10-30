/**
 * The demo's Practice Coach card. Each gate below was verified by breaking
 * the line of PracticeCoach.tsx it guards (see the commit message), because
 * a gate that does not fail when removed is decoration.
 *
 *   consent       nothing is read without the tick, and the tick is per upload
 *   flagged       an unsettled reading cannot be planned
 *   untick        only the items the visitor keeps are approved or printed
 *   print         the child's copy carries prompts, never the answers
 *   reset         another quiz starts from nothing
 *   allowance     an exhausted session reads nothing more
 *   no local      the demo never offers or mentions a local model
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  fetchPracticePacks: vi.fn(),
  fetchPracticeRoute: vi.fn(),
  readPracticePhotos: vi.fn(),
  confirmPracticeReading: vi.fn(),
  planPractice: vi.fn(),
  approvePracticeSet: vi.fn(),
  discardPracticeSet: vi.fn(),
}))

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return { ...actual, ...api }
})

import { PracticeConsentRequired, PracticeQuotaExceeded, TrialSessionEndedError } from './api'
import PracticeCoachPanel, { PracticeCoachCard } from './PracticeCoach'
import i18n from './i18n'

const item = (number: number, extra: Record<string, unknown> = {}) => ({
  number, prompt: `Prompt ${number}`, student_response: `Answer ${number}`,
  teacher_mark: 'incorrect', teacher_correction: null, confidence: 1, ask_parent: null, ...extra,
})

const READING = (flagged = 2) => ({
  id: 7,
  status: 'needs_review',
  assessment: {
    subject: 'latin',
    sections: [{
      label: 'Part A', instructions: 'Write a sentence.', required_format: 'complete_sentence', word_bank: [],
      items: [
        item(1),
        item(2, flagged >= 1 ? { confidence: 0.4, ask_parent: 'Is this macron there?' } : {}),
        item(3, flagged >= 2 ? { confidence: 0.5 } : {}),
      ],
    }],
  },
  ask_parent: [],
  teacher_mark_count: { correct: 0, total: 3, source: 'teacher_marks' },
  uploads_remaining: 2,
})

const PLAN = {
  summary: 'x',
  diagnosis: {
    errors: [
      { item_ref: 'Part A #1', category: 'c', evidence: 'Used the general word', audience: 'parent_and_child' },
      { item_ref: 'Part A #2', category: 'd', evidence: 'Left blank', audience: 'parent_only' },
    ],
    strengths: [{ category: 's', note: 'Colour words were solid' }],
    ask_parent: [],
  },
  set_id: 11,
  status: 'draft',
  practice_set: {
    targets: ['t'], mode: 'drill', est_minutes: 6, parent_script: 'Say this.', recheck_schedule: ['+3d'],
    items: [
      { kind: 'drill', target: 't', prompt: 'Practice one', expected_answer: 'SECRET-ONE', hint: 'h1' },
      { kind: 'drill', target: 't', prompt: 'Practice two', expected_answer: 'SECRET-TWO', hint: '' },
      { kind: 'retrieval', target: 't', prompt: 'Practice three', expected_answer: 'SECRET-THREE', hint: '' },
    ],
  },
}

const ROUTE = { cloud_provider: 'openai', uploads_remaining: 3, max_uploads: 3, max_pages: 3 }

beforeEach(() => {
  api.fetchPracticePacks.mockResolvedValue([{ id: 'latin', display_name: 'Latin' }])
  api.fetchPracticeRoute.mockResolvedValue({ ...ROUTE })
  api.readPracticePhotos.mockResolvedValue(READING())
  api.confirmPracticeReading.mockResolvedValue({ ...READING(0), status: 'confirmed' })
  api.planPractice.mockResolvedValue(PLAN)
  api.approvePracticeSet.mockResolvedValue({ id: 11, status: 'approved' })
  api.discardPracticeSet.mockResolvedValue({ id: 11, status: 'discarded' })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  i18n.changeLanguage('en')
})

async function mount(props: { onSessionEnded?: () => void } = {}) {
  render(<PracticeCoachCard token="tok" {...props} />)
  await screen.findByRole('option', { name: 'Latin' })
}

const fileInput = () => document.querySelector('input[type="file"]') as HTMLInputElement
const readButton = () => screen.getByRole('button', { name: /Read the quiz/ }) as HTMLButtonElement
const consentBox = () => screen.getByRole('checkbox', { name: /Tick to send these pages to openai/ }) as HTMLInputElement

const pick = (name = 'quiz.png', type = 'image/png') =>
  fireEvent.change(fileInput(), { target: { files: [new File(['x'], name, { type })] } })

async function uploadAndRead() {
  pick()
  fireEvent.click(consentBox())
  await act(async () => { fireEvent.click(readButton()) })
  await screen.findByText(/Please check 2 answers/)
}

const settle = () => screen.getAllByRole('button', { name: 'Looks right' }).forEach((b) => fireEvent.click(b))

describe('consent', () => {
  it('names the provider and will not read until it is ticked', async () => {
    await mount()
    expect(consentBox().checked).toBe(false)
    pick()
    expect(readButton().disabled).toBe(true)
    await act(async () => { fireEvent.click(readButton()) })
    expect(api.readPracticePhotos).not.toHaveBeenCalled()

    fireEvent.click(consentBox())
    expect(readButton().disabled).toBe(false)
  })

  it('sends the tick with the upload and asks again for the next one', async () => {
    await mount()
    await uploadAndRead()
    expect(api.readPracticePhotos).toHaveBeenCalledTimes(1)
    expect(api.readPracticePhotos.mock.calls[0][1].cloud_consent).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'Start over' }))
    expect(consentBox().checked).toBe(false)
    pick()
    expect(readButton().disabled).toBe(true)
  })

  it('un-ticks itself even when the read fails', async () => {
    api.readPracticePhotos.mockRejectedValueOnce(new Error('The pages could not be read right now'))
    await mount()
    pick(); fireEvent.click(consentBox())
    await act(async () => { fireEvent.click(readButton()) })
    await screen.findByRole('alert')
    expect(consentBox().checked).toBe(false)
  })

  it('shows the server consent refusal in the visitor words', async () => {
    api.readPracticePhotos.mockRejectedValueOnce(new PracticeConsentRequired('openai', 'x'))
    await mount()
    pick(); fireEvent.click(consentBox())
    await act(async () => { fireEvent.click(readButton()) })
    expect((await screen.findByRole('alert')).textContent).toContain('openai')
  })

  it('offers no way to read without a provider, and never mentions a local model', async () => {
    api.fetchPracticeRoute.mockResolvedValue({ ...ROUTE, cloud_provider: null })
    await mount()
    expect(screen.getByText(/no AI provider set up/)).toBeTruthy()
    pick()
    expect(readButton().disabled).toBe(true)
    expect(document.body.textContent).not.toMatch(/running on this computer|local model/i)
  })
})

describe('the picker', () => {
  it('accepts PDF and iPhone HEIC like the product, and is capped at the demo page limit', async () => {
    await mount()
    const accept = fileInput().getAttribute('accept')!
    for (const kind of ['application/pdf', '.pdf', 'image/heic', 'image/heif', '.heic', '.heif', 'image/jpeg', 'image/png']) {
      expect(accept).toContain(kind)
    }
    const many = Array.from({ length: 5 }, (_, i) => new File(['x'], `p${i}.png`, { type: 'image/png' }))
    fireEvent.change(fileInput(), { target: { files: many } })
    fireEvent.click(consentBox())
    await act(async () => { fireEvent.click(readButton()) })
    await screen.findByText(/Please check/)
    expect(api.readPracticePhotos.mock.calls[0][1].pages).toHaveLength(3)
  })
})

describe('flagged readings', () => {
  it('cannot be planned until each flagged answer is settled', async () => {
    await mount()
    await uploadAndRead()
    const confirm = screen.getByRole('button', { name: /Confirm and plan practice/ }) as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    await act(async () => { fireEvent.click(confirm) })
    expect(api.planPractice).not.toHaveBeenCalled()

    fireEvent.click(screen.getAllByRole('button', { name: 'Looks right' })[0])
    expect(confirm.disabled).toBe(true)  // one of two still open
    fireEvent.click(screen.getAllByRole('button', { name: 'Looks right' })[0])
    expect(confirm.disabled).toBe(false)

    await act(async () => { fireEvent.click(confirm) })
    expect(api.confirmPracticeReading).toHaveBeenCalledTimes(1)
    expect(api.planPractice).toHaveBeenCalledTimes(1)
    await screen.findByText(/Practice set \(about 6 minutes\)/)
  })

  it('sends the visitor corrections, not the first reading', async () => {
    await mount()
    await uploadAndRead()
    fireEvent.change(screen.getByLabelText('Answer written for Part A #1'), { target: { value: 'Corrected' } })
    settle()
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Confirm and plan practice/ })) })
    expect(api.confirmPracticeReading.mock.calls[0][2].sections[0].items[0].student_response).toBe('Corrected')
  })
})

async function toPlan() {
  await mount()
  await uploadAndRead()
  settle()
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Confirm and plan practice/ })) })
  await screen.findByText(/Practice set/)
}

describe('the practice set', () => {
  it('keeps the parent-only findings under their own heading', async () => {
    await toPlan()
    expect(screen.getByText('Just for you (not shown to your child)')).toBeTruthy()
    expect(screen.getByText('What to work on')).toBeTruthy()
    expect(screen.getByText('What was solid')).toBeTruthy()
  })

  it('approves only the items that are still ticked', async () => {
    await toPlan()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include item 2' }))
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Approve' })) })
    const sent = api.approvePracticeSet.mock.calls[0][2]
    expect(sent.items.map((i: { prompt: string }) => i.prompt)).toEqual(['Practice one', 'Practice three'])
    expect(screen.getByRole('status').textContent).toMatch(/does not keep it after your session/)
  })

  it('will not approve or print with nothing ticked', async () => {
    await toPlan()
    for (const n of [1, 2, 3]) fireEvent.click(screen.getByRole('checkbox', { name: `Include item ${n}` }))
    expect((screen.getByRole('button', { name: 'Approve' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: /Print worksheet/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it("prints the ticked prompts and never the answers", async () => {
    await toPlan()
    const doc = { write: vi.fn(), close: vi.fn() }
    const print = vi.fn()
    vi.spyOn(window, 'open').mockReturnValue({ document: doc, print } as unknown as Window)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include item 1' }))
    fireEvent.click(screen.getByRole('button', { name: /Print worksheet/ }))
    const html = doc.write.mock.calls[0][0] as string
    expect(html).toContain('Practice two')
    expect(html).toContain('Practice three')
    expect(html).not.toContain('Practice one')
    expect(html).not.toMatch(/SECRET/)
    expect(print).toHaveBeenCalled()
  })

  it('discarding keeps nothing', async () => {
    await toPlan()
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Discard' })) })
    expect(api.discardPracticeSet).toHaveBeenCalledWith('tok', 11)
    expect(screen.getByRole('status').textContent).toMatch(/Nothing was kept/)
  })
})

describe('starting another quiz', () => {
  it('clears the last one completely', async () => {
    await toPlan()
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Discard' })) })
    fireEvent.click(screen.getByRole('button', { name: 'Another quiz' }))
    expect(screen.queryByText(/Practice set/)).toBeNull()
    expect(screen.queryByLabelText('Answer written for Part A #1')).toBeNull()
    expect(consentBox().checked).toBe(false)
    expect(readButton().disabled).toBe(true)
  })

  it('does not leave the earlier plan on screen when the next read fails', async () => {
    await toPlan()
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Discard' })) })
    fireEvent.click(screen.getByRole('button', { name: 'Another quiz' }))
    api.readPracticePhotos.mockRejectedValueOnce(new Error('nope'))
    pick(); fireEvent.click(consentBox())
    await act(async () => { fireEvent.click(readButton()) })
    await screen.findByRole('alert')
    expect(screen.queryByText(/Practice set/)).toBeNull()
    expect(screen.queryByText(/does not keep it after your session/)).toBeNull()
  })
})

describe('the session allowance', () => {
  it('is shown, counts down, and disables reading when spent', async () => {
    api.fetchPracticeRoute.mockResolvedValue({ ...ROUTE, uploads_remaining: 0 })
    await mount()
    expect(screen.getByText('Quiz reads left in this demo session: 0 of 3.')).toBeTruthy()
    pick(); fireEvent.click(consentBox())
    expect(readButton().disabled).toBe(true)
  })

  it('follows the server after a read', async () => {
    await mount()
    expect(screen.getByText('Quiz reads left in this demo session: 3 of 3.')).toBeTruthy()
    await uploadAndRead()
    fireEvent.click(screen.getByRole('button', { name: 'Start over' }))
    expect(screen.getByText('Quiz reads left in this demo session: 2 of 3.')).toBeTruthy()
  })

  it("turns the server's quota refusal into a spent allowance", async () => {
    api.readPracticePhotos.mockRejectedValueOnce(new PracticeQuotaExceeded('This demo reads up to 3 quizzes per session'))
    await mount()
    pick(); fireEvent.click(consentBox())
    await act(async () => { fireEvent.click(readButton()) })
    expect((await screen.findByRole('alert')).textContent).toMatch(/up to 3 quizzes/)
    expect(screen.getByText('Quiz reads left in this demo session: 0 of 3.')).toBeTruthy()
  })
})

describe('the session ending', () => {
  it('hands off to the demo own session-ended screen', async () => {
    api.readPracticePhotos.mockRejectedValueOnce(new TrialSessionEndedError('ended'))
    const onSessionEnded = vi.fn()
    await mount({ onSessionEnded })
    pick(); fireEvent.click(consentBox())
    await act(async () => { fireEvent.click(readButton()) })
    await waitFor(() => expect(onSessionEnded).toHaveBeenCalledTimes(1))
  })

  it('does not refetch its options when the parent passes a new callback each render', async () => {
    const { rerender } = render(<PracticeCoachCard token="tok" onSessionEnded={() => {}} />)
    await screen.findByRole('option', { name: 'Latin' })
    rerender(<PracticeCoachCard token="tok" onSessionEnded={() => {}} />)
    rerender(<PracticeCoachCard token="tok" onSessionEnded={() => {}} />)
    expect(api.fetchPracticeRoute).toHaveBeenCalledTimes(1)
  })
})

describe('the panel and the privacy statement', () => {
  it('states the memory-only promise where the visitor reads it, in both languages', async () => {
    render(<PracticeCoachPanel token="tok" onClose={() => {}} />)
    await screen.findByRole('option', { name: 'Latin' })
    expect(screen.getByRole('dialog')).toBeTruthy()
    expect(document.body.textContent).toMatch(/does not save the pages/)
    expect(document.body.textContent).toMatch(/stay in memory for this demo session only/)
    cleanup()
    await act(async () => { await i18n.changeLanguage('es') })
    render(<PracticeCoachCard token="tok" />)
    await screen.findByRole('option', { name: 'Latin' })
    expect(document.body.textContent).toMatch(/permanecen en memoria solo durante esta sesión/)
  })

  it('closes', async () => {
    const onClose = vi.fn()
    render(<PracticeCoachPanel token="tok" onClose={onClose} />)
    await screen.findByRole('option', { name: 'Latin' })
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalled()
  })
})
