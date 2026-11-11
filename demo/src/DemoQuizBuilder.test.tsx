import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import './i18n'
import type { GeneratedQuiz, QuizOptions } from './api'
import DemoQuizBuilder from './DemoQuizBuilder'

const api = vi.hoisted(() => ({
  copyDemoQuizSource: vi.fn(),
  fetchDemoQuizOptions: vi.fn(),
  generateDemoQuiz: vi.fn(),
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

const options = (route: QuizOptions['route']): QuizOptions => ({
  subjects: [{ id: 'mathematics', display_name: 'Mathematics' }, { id: 'history', display_name: 'History & Geography' }],
  grades: ['K', '1', '2', '3', '4', '5', '6', '7', '8'],
  kinds: ['ad_hoc', 'quiz', 'unit_test', 'midterm', 'final', 'prep_exam'],
  levels: ['review', 'on_level', 'challenge'],
  max_questions: 50,
  route,
})

const quiz: GeneratedQuiz = {
  title: 'Addition quiz', subject: 'mathematics', grade: '3', kind: 'quiz', level: 'on_level',
  coverage: ['two-digit addition'], est_minutes: 4,
  questions: [
    { number: 1, type: 'computation', topic: 'addition', prompt: '27 + 15 =', options: [], answer: '42', answer_check: 'computed' },
    { number: 2, type: 'multiple_choice', topic: 'addition', prompt: 'Which is 10 more than 35?', options: ['25', '45', '36'], answer: '45', answer_check: 'verify' },
  ],
}

describe('demo quiz builder', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.generateDemoQuiz.mockResolvedValue({ quiz, report: { answers_recomputed: 0, dropped: 0, short_by: 0 } })
  })

  it('drafts from a typed topic on the demo provider with the tick, while photos stay off', async () => {
    // The live demo: no local model and photo reading switched off, but a
    // typed topic can be drafted on the provider the chat already uses.
    api.fetchDemoQuizOptions.mockResolvedValue(options({ local_available: false, cloud_provider: null, draft_provider: 'openai' }))
    render(<DemoQuizBuilder token="t" onApproved={vi.fn()} />)
    fireEvent.change(await screen.findByLabelText('What to cover'), { target: { value: 'Multiplication' } })
    expect(screen.queryByText('No AI model is available to draft quizzes right now.')).toBeNull()
    expect(screen.getByText(/A typed topic or pasted quiz works here/)).toBeTruthy()
    expect(screen.getByLabelText(/Or add photos/)).toHaveProperty('disabled', true)

    const draft = screen.getByRole('button', { name: 'Draft quiz' })
    expect(draft).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByLabelText('I agree to send this to OpenAI to draft the quiz.'))
    fireEvent.click(draft)
    await waitFor(() => expect(api.generateDemoQuiz).toHaveBeenCalledWith('t', expect.objectContaining({
      focus: 'Multiplication', cloud_consent: true, pages: [],
    })))
  })

  it('prints the kept questions, and a separate answer key, with buttons a thumb can hit', async () => {
    api.fetchDemoQuizOptions.mockResolvedValue(options({ local_available: true, cloud_provider: null, draft_provider: null }))
    printed.sheets.length = 0
    printed.html.length = 0
    render(<DemoQuizBuilder token="t" onApproved={vi.fn()} />)
    fireEvent.change(await screen.findByLabelText('What to cover'), { target: { value: 'Addition' } })
    fireEvent.click(screen.getByRole('button', { name: 'Draft quiz' }))
    const printQuiz = await screen.findByRole('button', { name: 'Print quiz' })
    const printKey = screen.getByRole('button', { name: 'Print answer key' })
    expect(printQuiz.className).toContain('min-h-[44px]')
    expect(printKey.className).toContain('min-h-[44px]')

    fireEvent.click(screen.getByRole('checkbox', { name: 'Include question 1' }))
    fireEvent.click(printQuiz)
    await waitFor(() => expect(printed.html).toHaveLength(1))
    expect(printed.sheets[0]).toMatchObject({ copies: ['student'], title: 'Addition quiz' })
    expect(printed.html[0]).not.toContain('27 + 15 =')
    expect(printed.html[0]).toContain('Which is 10 more than 35?')
    expect(printed.html[0]).toContain('<li>A) 25</li><li>B) 45</li><li>C) 36</li>')
    expect(printed.html[0]).toContain('Name <span class="fill">')
    expect(printed.html[0]).not.toContain('class="ans"')

    fireEvent.click(printKey)
    await waitFor(() => expect(printed.html).toHaveLength(2))
    expect(printed.sheets[1]).toMatchObject({ copies: ['key'] })
    expect(printed.html[1]).toContain('<h1>Addition quiz: answer key</h1>')
    expect(printed.html[1]).toContain('<p class="ans">45</p>')
  })

  it('a long source is copied out a part at a time, then drafted from the text', async () => {
    api.fetchDemoQuizOptions.mockResolvedValue(options({ local_available: true, cloud_provider: null, draft_provider: null }))
    api.copyDemoQuizSource.mockImplementation(async (_t: string, body: { pages: unknown[]; first_page: number }) => ({
      text: `[Pages ${body.first_page}-${body.first_page + body.pages.length - 1}]`, pages_read: body.pages.length,
    }))
    render(<DemoQuizBuilder token="t" onApproved={vi.fn()} />)
    const files = Array.from({ length: 8 }, (_, i) => new File([`p${i}`], `p${i}.jpg`, { type: 'image/jpeg' }))
    fireEvent.change(await screen.findByLabelText(/Or add photos/), { target: { files } })
    fireEvent.click(screen.getByRole('button', { name: 'Draft quiz' }))
    await waitFor(() => expect(api.generateDemoQuiz).toHaveBeenCalled())
    expect(api.copyDemoQuizSource.mock.calls.map((c) => c[1].first_page)).toEqual([1, 7])
    expect(api.generateDemoQuiz.mock.calls[0][1]).toMatchObject({
      pages: [], source_pages_text: '[Pages 1-6]\n\n[Pages 7-8]',
    })
  })

  it('refuses a choice of files over 1 GB before anything is sent', async () => {
    api.fetchDemoQuizOptions.mockResolvedValue(options({ local_available: true, cloud_provider: null, draft_provider: null }))
    render(<DemoQuizBuilder token="t" onApproved={vi.fn()} />)
    const big = (n: number) => Object.defineProperty(new File(['x'], `${n}.pdf`, { type: 'application/pdf' }), 'size', { value: 25 * 1024 * 1024 })
    fireEvent.change(await screen.findByLabelText(/Or add photos/), { target: { files: Array.from({ length: 41 }, (_, i) => big(i)) } })
    expect(await screen.findByText(/more than 1 GB/)).toBeTruthy()
    expect(api.copyDemoQuizSource).not.toHaveBeenCalled()
  })

  it('needs something to learn from, then drafts with every choice the adult made', async () => {
    api.fetchDemoQuizOptions.mockResolvedValue(options({ local_available: true, cloud_provider: null }))
    render(<DemoQuizBuilder token="t" onApproved={vi.fn()} />)
    const draft = await screen.findByRole('button', { name: 'Draft quiz' })
    expect(draft).toHaveProperty('disabled', true)

    fireEvent.change(screen.getByLabelText('Grade'), { target: { value: '7' } })
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'final' } })
    fireEvent.change(screen.getByLabelText('Level'), { target: { value: 'challenge' } })
    fireEvent.change(screen.getByLabelText('Questions'), { target: { value: '40' } })
    fireEvent.change(screen.getByLabelText('What to cover'), { target: { value: 'equations' } })
    fireEvent.click(draft)

    await waitFor(() => expect(api.generateDemoQuiz).toHaveBeenCalledWith('t', expect.objectContaining({
      subject: 'mathematics', grade: '7', kind: 'final', level: 'challenge', question_count: 40,
      focus: 'equations', cloud_consent: false,
    })))
  })

  it('needs the consent tick before anything goes to a cloud provider', async () => {
    api.fetchDemoQuizOptions.mockResolvedValue(options({ local_available: false, cloud_provider: 'OpenAI', draft_provider: 'OpenAI' }))
    render(<DemoQuizBuilder token="t" onApproved={vi.fn()} />)
    fireEvent.change(await screen.findByLabelText('What to cover'), { target: { value: 'fractions' } })
    expect(screen.getByRole('button', { name: 'Draft quiz' })).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Draft quiz' }))
    await waitFor(() => expect(api.generateDemoQuiz).toHaveBeenCalledWith('t', expect.objectContaining({ cloud_consent: true })))
  })

  it('shows which answers were worked out and which to check, and sends the student only the questions', async () => {
    api.fetchDemoQuizOptions.mockResolvedValue(options({ local_available: true, cloud_provider: null }))
    const onApproved = vi.fn()
    render(<DemoQuizBuilder token="t" onApproved={onApproved} />)
    fireEvent.change(await screen.findByLabelText('What to cover'), { target: { value: 'addition' } })
    fireEvent.click(screen.getByRole('button', { name: 'Draft quiz' }))

    expect(await screen.findByText('Worked out')).toBeTruthy()
    expect(screen.getByText('Check')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Answer for question 2'), { target: { value: '45!' } })
    fireEvent.click(screen.getByLabelText('Include question 1'))
    fireEvent.click(screen.getByRole('button', { name: 'Use this quiz' }))

    expect(onApproved).toHaveBeenCalledWith([
      { index: 0, prompt: 'Which is 10 more than 35?\nA) 25\nB) 45\nC) 36', hint: '' },
    ])
    expect(JSON.stringify(onApproved.mock.calls)).not.toContain('45!')
  })
})
