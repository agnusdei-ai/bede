import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  fetchEducatorQuizOptions: vi.fn(),
  approveTeacherQuiz: vi.fn(),
  extractTeacherQuiz: vi.fn(),
  reviewTeacherQuiz: vi.fn(),
  scoreTeacherQuiz: vi.fn(),
  finalizeTeacherQuiz: vi.fn(),
}))
vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return { ...original, ...mocks }
})
const printed = vi.hoisted(() => ({ sheets: [] as unknown[], html: [] as string[] }))
vi.mock('../utils/printDocument', async (importOriginal) => {
  const original = await importOriginal<typeof import('../utils/printDocument')>()
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

import i18n from '../i18n'
import TeacherQuizStudio, { teacherUploadProblem } from './TeacherQuizStudio'
import { TeacherQuizProblems, type QuizOptions, type TeacherQuiz } from '../services/api'

afterEach(cleanup)

const options = (local: boolean): QuizOptions => ({
  subjects: [{ id: 'mathematics', display_name: 'Mathematics' }, { id: 'history', display_name: 'History' }],
  grades: ['K', '1', '2', '3', '4', '5', '6', '7', '8'],
  kinds: ['quiz'], levels: ['on_level'], max_questions: 50,
  route: { local_available: local, cloud_provider: null, draft_provider: null },
})

const approvedQuiz: TeacherQuiz = {
  format: 'bede.teacher-quiz', version: 1, title: 'Week 3', subject: 'mathematics', grade: '4', approved: true,
  questions: [
    { number: 1, type: 'computation', prompt: '27 + 15 =', options: [], answer: '42', accepted_answers: [], points: 1, key_source: 'teacher', key_approved: true },
    { number: 2, type: 'short_answer', prompt: 'Capital of France?', options: [], answer: 'Paris', accepted_answers: [], points: 1, key_source: 'page', key_approved: true },
  ],
}

function printSpy() {
  printed.sheets.length = 0
  printed.html.length = 0
  return printed.html
}

describe('TeacherQuizStudio', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    await i18n.changeLanguage('en')
    mocks.fetchEducatorQuizOptions.mockResolvedValue(options(true))
  })

  it('a quiz the teacher writes is approved by the server, then prints without its key', async () => {
    mocks.approveTeacherQuiz.mockImplementation(async (_t: string, quiz: TeacherQuiz) => ({ quiz: { ...quiz, approved: true }, problems: [] }))
    const written = printSpy()
    render(<TeacherQuizStudio token="t" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    fireEvent.change(await screen.findByLabelText('Quiz title'), { target: { value: 'Fractions' } })
    fireEvent.click(screen.getByRole('button', { name: 'Write a new quiz' }))
    fireEvent.change(screen.getByLabelText('Question 1'), { target: { value: '3/4 + 1/4 =' } })
    fireEvent.change(screen.getByLabelText('Answer for question 1'), { target: { value: '1' } })
    expect(screen.getByTestId('source-1').textContent).toBe('Your answer')
    expect((screen.getByRole('button', { name: 'Print quiz' }) as HTMLButtonElement).disabled).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'Check and approve the key' }))
    await screen.findByText('The answer key is approved.')
    const sent = mocks.approveTeacherQuiz.mock.calls[0][1] as TeacherQuiz
    expect(sent.questions[0]).toMatchObject({ prompt: '3/4 + 1/4 =', answer: '1', key_source: 'teacher', key_approved: true })

    fireEvent.click(screen.getByRole('button', { name: 'Print quiz' }))
    await waitFor(() => expect(written).toHaveLength(1))
    expect(written[0]).toContain('3/4 + 1/4 =')
    expect(written[0]).toContain('Name <span class="fill">')
    expect(written[0]).not.toContain('class="ans"')
    fireEvent.click(screen.getByRole('button', { name: 'Print answer key' }))
    await waitFor(() => expect(written).toHaveLength(2))
    expect(written[1]).toContain('class="ans">1<')
    expect(written[1]).not.toContain('class="fill"')
  })

  it('an uploaded quiz needs the tick first, and shows where each answer came from', async () => {
    mocks.extractTeacherQuiz.mockResolvedValue({
      quiz: {
        ...approvedQuiz, approved: false,
        questions: [
          { ...approvedQuiz.questions[0], key_source: 'bede', key_approved: false, answer_check: 'computed' },
          { ...approvedQuiz.questions[1], key_source: 'page', key_approved: false, reading_note: 'Could be Paris or Parts.' },
        ],
      },
      problems: [{ number: 1, problem: 'key_not_approved' }, { number: 2, problem: 'reading_unsettled' }],
    })
    render(<TeacherQuizStudio token="t" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    const upload = await screen.findByLabelText(/Or add photos or a PDF of the quiz/)
    fireEvent.change(upload, { target: { files: [new File(['x'], 'quiz.jpg', { type: 'image/jpeg' })] } })
    const read = screen.getByRole('button', { name: 'Read the quiz' }) as HTMLButtonElement
    expect(read.disabled).toBe(true)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(read.disabled).toBe(false)
    fireEvent.click(read)

    await waitFor(() => expect(mocks.extractTeacherQuiz).toHaveBeenCalledWith('t', expect.objectContaining({ upload_consent: true })))
    expect((await screen.findByTestId('source-1')).textContent).toBe('Suggested by Bede')
    expect(screen.getByTestId('source-2').textContent).toBe('Read from your page')
    expect(screen.getByText('Check this: Could be Paris or Parts.')).toBeTruthy()
    expect(screen.getByText(/Question 2: Bede was unsure of its reading/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Looks right, question 2' }))
    expect(screen.queryByText('Check this: Could be Paris or Parts.')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Looks right, question 2' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Looks right, question 1' })).toBeTruthy()
  })

  it('shows what the server refused, and nothing is approved', async () => {
    mocks.approveTeacherQuiz.mockRejectedValue(new TeacherQuizProblems([{ number: 1, problem: 'no_key' }], 'x'))
    render(<TeacherQuizStudio token="t" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Write a new quiz' }))
    fireEvent.click(screen.getByRole('button', { name: 'Check and approve the key' }))
    expect(await screen.findByText('Question 1: Add the answer.')).toBeTruthy()
    expect(screen.queryByText('The answer key is approved.')).toBeNull()
    expect((screen.getByRole('button', { name: "Score a student's work" }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('with no school model, reading is off and the teacher is told why', async () => {
    mocks.fetchEducatorQuizOptions.mockResolvedValue(options(false))
    render(<TeacherQuizStudio token="t" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    expect(await screen.findByText(/This install has no school AI model/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Paste the quiz text'), { target: { value: '1. 2 + 2 =' } })
    expect((screen.getByRole('button', { name: 'Read the quiz' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('results marked for the teacher count only after the teacher settles them', async () => {
    mocks.scoreTeacherQuiz.mockResolvedValue({
      possible: 2, read_by: null,
      results: [
        { number: 1, response: '42', max_points: 1, proposed_points: 1, method: 'numeric', needs_teacher: false, reasons: [] },
        { number: 2, response: 'It is Paris', max_points: 1, proposed_points: 0, method: 'key_match', needs_teacher: true, reasons: ['not_in_key'] },
      ],
    })
    mocks.finalizeTeacherQuiz.mockResolvedValue({ results: [], total: 2, possible: 2 })
    const written = printSpy()
    render(<TeacherQuizStudio token="t" incoming={approvedQuiz} />)
    fireEvent.click(await screen.findByRole('button', { name: "Score a student's work" }))
    fireEvent.click(screen.getByText("Or type the student's answers"))
    fireEvent.change(screen.getByLabelText("Student's answer to question 1"), { target: { value: '42' } })
    fireEvent.change(screen.getByLabelText("Student's answer to question 2"), { target: { value: 'It is Paris' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose scores' }))

    await screen.findByText(/This answer does not match your key/)
    const sent = mocks.scoreTeacherQuiz.mock.calls[0][1]
    expect(sent.responses).toEqual([{ number: 1, response: '42' }, { number: 2, response: 'It is Paris' }])
    expect(sent.pages).toEqual([])
    const approveResults = screen.getByRole('button', { name: 'Approve these results' }) as HTMLButtonElement
    expect(approveResults.disabled).toBe(true)
    expect(screen.getByText('Some results still need your review before they count.')).toBeTruthy()

    // The teacher decides the wording is right after all.
    fireEvent.change(screen.getByLabelText('Score for question 2'), { target: { value: '1' } })
    expect(approveResults.disabled).toBe(false)
    fireEvent.click(approveResults)
    await screen.findByText('Total: 2 of 2')
    expect(mocks.finalizeTeacherQuiz.mock.calls[0][1].results).toEqual([{ number: 1, points: 1 }, { number: 2, points: 1 }])

    fireEvent.click(screen.getByRole('button', { name: 'Print results' }))
    await waitFor(() => expect(written).toHaveLength(1))
    expect(written[0]).toContain('Name <span class="fill">')
    expect(written[0]).toContain('class="ans">1 / 1<')
    expect(written[0]).toContain('Total: 2 of 2')
  })

  it('a student’s pages need the tick, and the next student starts clean', async () => {
    mocks.scoreTeacherQuiz.mockResolvedValue({
      possible: 2, read_by: "the school's own AI model",
      results: [{ number: 1, response: '41', max_points: 1, proposed_points: 1, method: 'numeric', needs_teacher: true, reasons: ['reading_uncertain'] }],
    })
    render(<TeacherQuizStudio token="t" incoming={approvedQuiz} />)
    fireEvent.click(await screen.findByRole('button', { name: "Score a student's work" }))
    fireEvent.change(screen.getByLabelText(/one student's completed quiz/), {
      target: { files: [new File(['x'], 'work.jpg', { type: 'image/jpeg' })] },
    })
    const propose = screen.getByRole('button', { name: 'Propose scores' }) as HTMLButtonElement
    expect(propose.disabled).toBe(true)
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(propose)
    await waitFor(() => expect(mocks.scoreTeacherQuiz).toHaveBeenCalled())
    expect(mocks.scoreTeacherQuiz.mock.calls[0][1]).toMatchObject({ upload_consent: true, responses: [] })
    const row = (await screen.findByText(/Bede was not sure it read this answer/)).closest('li')!
    fireEvent.click(within(row).getByRole('button', { name: 'Looks right, question 1' }))
    expect((screen.getByLabelText('Score for question 1') as HTMLInputElement).value).toBe('1')
    fireEvent.click(screen.getByRole('button', { name: 'Next student' }))
    expect(screen.queryByText(/Bede was not sure it read this answer/)).toBeNull()
    expect(screen.getByRole('button', { name: 'Propose scores' })).toBeTruthy()
  })

  it('reads in Spanish as plain sentences', async () => {
    await i18n.changeLanguage('es')
    render(<TeacherQuizStudio token="t" />)
    expect(screen.getByText('Tu propio examen, con clave de respuestas')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Empezar' }))
    expect(await screen.findByRole('button', { name: 'Escribir un examen nuevo' })).toBeTruthy()
    await i18n.changeLanguage('en')
  })
})

describe('teacher quiz copy', () => {
  it('the labels docs/PRACTICE_COACH.md quotes are the labels on screen', async () => {
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    const en = (await import('../i18n/locales/en.json')).default
    const doc = readFileSync(join(__dirname, '../../../docs/PRACTICE_COACH.md'), 'utf8').replace(/\s+/g, ' ')
    const quoted = [
      en.teacherQuiz.title, en.teacherQuiz.source.teacher, en.teacherQuiz.source.page, en.teacherQuiz.source.bede,
      en.practiceCoach.looksRight, en.teacherQuiz.approve, en.teacherQuiz.approveResults, en.teacherQuiz.export,
      en.teacherQuiz.import, en.quizBuilder.editAsTeacher, en.quizBuilder.title,
    ]
    for (const label of quoted) expect(doc, label).toContain(`**${label}**`)
  })

  it('never says "synthetic" in either language', async () => {
    const en = (await import('../i18n/locales/en.json')).default as Record<string, unknown>
    const es = (await import('../i18n/locales/es.json')).default as Record<string, unknown>
    for (const locale of [en, es]) {
      expect(JSON.stringify(locale.teacherQuiz).toLowerCase()).not.toContain('synthetic')
      expect(JSON.stringify(locale.teacherQuiz).toLowerCase()).not.toContain('sintétic')
    }
  })

  it('takes any number of quiz pages, and refuses only by size, with a way forward', async () => {
    render(<TeacherQuizStudio token="t" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    const input = await screen.findByLabelText(/PDF of the quiz/)
    const page = (mb: number, i: number) => new File([new Uint8Array(mb * 1024 * 1024)], `p${i}.jpg`, { type: 'image/jpeg' })
    fireEvent.change(input, { target: { files: Array.from({ length: 13 }, (_, i) => page(1, i)) } })
    expect(screen.getByText('13 file(s) added')).toBeTruthy()
    fireEvent.change(input, { target: { files: [page(20, 1), page(20, 2)] } })
    expect(screen.getByRole('alert').textContent).toMatch(/more than 24 MB together.*paste the quiz/)
    expect(screen.queryByText(/file\(s\) added/)).toBeNull()
  })
})

describe('teacherUploadProblem', () => {
  it('has no page count, only the byte limits one request can carry', () => {
    expect(teacherUploadProblem(Array.from({ length: 200 }, () => ({ size: 1000 })))).toBeNull()
    expect(teacherUploadProblem([{ size: 26 * 1024 * 1024 }])).toBe('file')
    expect(teacherUploadProblem([{ size: 13 * 1024 * 1024 }, { size: 12 * 1024 * 1024 }])).toBe('total')
  })
})
