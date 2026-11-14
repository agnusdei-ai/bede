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
  fetchDemoReadingProgress: vi.fn(),
  planDemoPractice: vi.fn(),
  readDemoPracticePhotos: vi.fn(),
}))

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  ...api,
}))

const printed = vi.hoisted(() => ({ sheets: [] as unknown[], html: [] as string[] }))
vi.mock('./printDocument', async (importOriginal) => {
  const original = await importOriginal<typeof import('./printDocument')>()
  return {
    ...original,
    // The real page builder, without opening a print dialog. What the button
    // passes is what this records, so these tests check the call site.
    printSheet: async (sheet: Parameters<typeof original.buildPrintHtml>[0]) => {
      printed.sheets.push(sheet)
      printed.html.push(original.buildPrintHtml(sheet))
      return true
    },
  }
})

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
  it('shows a progress bar with the percentage while the pages are read', async () => {
    let finish: (v: unknown) => void = () => undefined
    api.readDemoPracticePhotos.mockImplementation(() => new Promise((r) => { finish = r }))
    api.fetchDemoReadingProgress.mockResolvedValue({ stage: 'reading', done: 6, total: 12 })
    render(<DemoPracticeCoach token="sample-token" onClose={vi.fn()} onApproved={vi.fn()} />)
    await screen.findByRole('option', { name: 'Latin' })
    fireEvent.change(screen.getByLabelText(/Choose image files/i), { target: { files: [new File(['x'], 'q.jpg', { type: 'image/jpeg' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Read quiz' }))
    const bar = await screen.findByRole('progressbar')
    await waitFor(() => expect(bar.getAttribute('aria-valuenow')).toBe('48'), { timeout: 3000 })
    expect(screen.getByText(/48% · Read 6 of 12 pages/)).toBeTruthy()
    const sent = api.readDemoPracticePhotos.mock.calls[0][1]
    expect(api.fetchDemoReadingProgress).toHaveBeenCalledWith('sample-token', sent.progress_id)
    finish({ id: 0, status: 'needs_review', assessment, ask_parent: [], teacher_mark_count: { correct: 0, total: 1, source: 'teacher_marks' }, pages_read: 1 })
    await waitFor(() => expect(screen.queryByRole('progressbar')).toBeNull())
  })

  it('draws a picture the page had, and never shows a "picture:" description', async () => {
    const pictured: DemoPracticeAssessment = { ...assessment, sections: [{ ...assessment.sections[0], items: [
      { ...assessment.sections[0].items[0], stimulus: 'picture: duck on water', diagram: { kind: 'pictures', groups: [{ icon: 'duck', count: 1 }, { icon: 'water', count: 1 }] } },
      { ...assessment.sections[0].items[0], number: 2, stimulus: 'picture: the Battle of Hastings', diagram: null },
    ] }] }
    api.readDemoPracticePhotos.mockResolvedValue({
      id: 0, status: 'needs_review', assessment: pictured, ask_parent: [],
      teacher_mark_count: { correct: 0, total: 2, source: 'teacher_marks' },
    })
    render(<DemoPracticeCoach token="sample-token" onClose={vi.fn()} onApproved={vi.fn()} />)
    await screen.findByRole('option', { name: 'Latin' })
    fireEvent.change(screen.getByLabelText(/Choose image files/i), { target: { files: [new File(['x'], 'q.jpg', { type: 'image/jpeg' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Read quiz' }))
    expect(await screen.findByRole('img', { name: /Pictures: 1 duck, 1 water/ })).toBeTruthy()
    expect(screen.queryByText(/picture:/i)).toBeNull()
    expect(screen.getByText(/the Battle of Hastings/)).toBeTruthy()
  })

  it('has no page limit: a long upload is sent in parts, each continuing the last', async () => {
    api.readDemoPracticePhotos.mockImplementation(async (_t: string, body: { pages: unknown[] }) => ({
      id: 0, status: 'needs_review', assessment, ask_parent: [],
      teacher_mark_count: { correct: 0, total: 1, source: 'teacher_marks' }, pages_read: body.pages.length,
    }))
    render(<DemoPracticeCoach token="sample-token" onClose={vi.fn()} onApproved={vi.fn()} />)
    await screen.findByRole('option', { name: 'Latin' })
    const files = Array.from({ length: 9 }, (_, i) => new File([`page-${i}`], `p${i}.jpg`, { type: 'image/jpeg' }))
    fireEvent.change(screen.getByLabelText(/Choose image files/i), { target: { files } })
    fireEvent.click(screen.getByRole('button', { name: 'Read quiz' }))
    await waitFor(() => expect(api.readDemoPracticePhotos).toHaveBeenCalledTimes(2))
    const [first, second] = api.readDemoPracticePhotos.mock.calls.map((c) => c[1])
    expect(first.pages).toHaveLength(6)
    expect(first).toMatchObject({ first_page: 1, continues: undefined })
    expect(second.pages).toHaveLength(3)
    expect(second).toMatchObject({ first_page: 7, continues: assessment })
  })

  it.each([
    ['JPEG', 'image/jpeg', 'sample-jpeg'],
    ['PNG', 'image/png', 'sample-png'],
    ['scanned PDF', 'application/pdf', '%PDF-sample-scan'],
  ])('reads sample %s uploads, supports adult correction, and requires explicit approval', async (_label, mime, content) => {
    const onApproved = vi.fn()
    render(<DemoPracticeCoach token="sample-token" onClose={vi.fn()} onApproved={onApproved} />)

    await screen.findByRole('option', { name: 'Latin' })
    const input = screen.getByLabelText(/Choose image files/i)
    const file = new File([content], `sample.${mime === 'application/pdf' ? 'pdf' : mime === 'image/png' ? 'png' : 'jpg'}`, { type: mime })
    fireEvent.change(input, { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Read quiz' }))

    await waitFor(() => expect(api.readDemoPracticePhotos).toHaveBeenCalledOnce())
    expect(api.readDemoPracticePhotos).toHaveBeenCalledWith('sample-token', {
      subject: 'latin',
      pages: [{ data: btoa(content) }],
      cloud_consent: false,
      first_page: 1,
      continues: undefined,
      progress_id: expect.any(String),
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

  it('prints the kept practice items as a worksheet, without the answers', async () => {
    printed.sheets.length = 0
    printed.html.length = 0
    render(<DemoPracticeCoach token="sample-token" onClose={vi.fn()} onApproved={vi.fn()} />)
    await screen.findByRole('option', { name: 'Latin' })
    fireEvent.change(screen.getByLabelText(/Choose image files/i), { target: { files: [new File(['x'], 'page.jpg', { type: 'image/jpeg' })] } })
    fireEvent.click(screen.getByRole('button', { name: 'Read quiz' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Looks right' }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirm review and plan practice' }))
    const print = await screen.findByRole('button', { name: 'Print worksheet' })
    expect(print.className).toContain('min-h-[44px]')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include practice question 1' }))
    fireEvent.click(print)
    await waitFor(() => expect(printed.html).toHaveLength(1))
    expect(printed.sheets[0]).toMatchObject({ copies: ['student'], title: 'Practice' })
    expect(printed.html[0]).toContain('Translate amo.')
    expect(printed.html[0]).not.toContain('Translate aqua.')
    expect(printed.html[0]).not.toContain('I love.')
    expect(printed.html[0]).toContain('Date <span class="fill">')
  })

  it('requires per-upload consent before sending pages to the cloud reader', async () => {
    api.fetchDemoPracticeReadingRoute.mockResolvedValue({ local_available: false, cloud_provider: 'OpenAI' })
    render(<DemoPracticeCoach token="sample-token" onClose={vi.fn()} onApproved={vi.fn()} />)
    await screen.findByText(/send these pages to OpenAI/i)
    expect(screen.getByText(/OpenAI may keep the images for up to 30 days/)).toBeTruthy()
    expect(screen.getByText(/crop out a full name first/)).toBeTruthy()
    const picker = screen.getByLabelText(/Choose image files/i) as HTMLInputElement
    for (const kind of ['image/jpeg', 'image/png', 'image/webp', 'image/avif', 'application/pdf']) {
      expect(picker.accept.split(',')).toContain(kind)
    }
    expect(picker.accept).not.toMatch(/heic/i)
    expect(screen.queryByText(/HEIC/)).toBeNull()  // the coach does not list what it cannot read
    fireEvent.change(screen.getByLabelText(/Choose image files/i), {
      target: { files: [new File(['sample'], 'sample.png', { type: 'image/png' })] },
    })
    expect(screen.getByRole('button', { name: 'Read quiz' })).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Read quiz' }))
    await waitFor(() => expect(api.readDemoPracticePhotos).toHaveBeenCalledWith('sample-token', expect.objectContaining({ cloud_consent: true })))
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
