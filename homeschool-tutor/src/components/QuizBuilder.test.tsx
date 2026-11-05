import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  fetchQuizOptions: vi.fn(),
  generateQuiz: vi.fn(),
  fetchEducatorQuizOptions: vi.fn(),
  generateEducatorQuiz: vi.fn(),
}))
vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return { ...original, ...mocks }
})

import i18n from '../i18n'
import QuizBuilder from './QuizBuilder'
import type { GeneratedQuiz, QuizOptions } from '../services/api'

afterEach(cleanup)

const options = (route: QuizOptions['route']): QuizOptions => ({
  subjects: [{ id: 'science', display_name: 'Science' }],
  grades: ['K', '1', '2', '3', '4', '5', '6', '7', '8'],
  kinds: ['ad_hoc', 'quiz', 'unit_test', 'midterm', 'final', 'prep_exam'],
  levels: ['review', 'on_level', 'challenge'],
  max_questions: 50,
  route,
})

const quiz: GeneratedQuiz = {
  title: 'Plants quiz', subject: 'science', grade: '4', kind: 'midterm', level: 'on_level',
  coverage: ['photosynthesis'], est_minutes: 3,
  questions: [
    { number: 1, type: 'short_answer', topic: 'plants', prompt: 'What do leaves need to make food?', options: [], answer: 'sunlight', answer_check: 'verify', second_answer: 'light' },
    { number: 3, type: 'short_answer', topic: 'plants', prompt: 'What gas do plants take in?', options: [], answer: 'carbon dioxide', answer_check: 'checked' },
    { number: 2, type: 'computation', topic: 'measurement', prompt: '12 × 3 =', options: [], answer: '36', answer_check: 'computed' },
  ],
}

describe('QuizBuilder', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    await i18n.changeLanguage('en')
    mocks.generateQuiz.mockResolvedValue({ quiz, report: { answers_recomputed: 0, dropped: 0, short_by: 0 } })
  })

  it('drafts for this student with the chosen grade and type, and prints the quiz without answers', async () => {
    mocks.fetchQuizOptions.mockResolvedValue(options({ local_available: true, cloud_provider: null }))
    const written: string[] = []
    const win = { document: { write: (h: string) => written.push(h), close: vi.fn() }, print: vi.fn() }
    vi.spyOn(window, 'open').mockReturnValue(win as unknown as Window)

    render(<QuizBuilder token="t" studentName="Ava" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    fireEvent.change(await screen.findByLabelText('Type'), { target: { value: 'midterm' } })
    fireEvent.change(screen.getByLabelText('Grade'), { target: { value: '4' } })
    fireEvent.change(screen.getByLabelText('What to cover'), { target: { value: 'plants' } })
    fireEvent.click(screen.getByRole('button', { name: 'Draft quiz' }))

    await waitFor(() => expect(mocks.generateQuiz).toHaveBeenCalledWith('t', 'Ava', expect.objectContaining({
      subject: 'science', grade: '4', kind: 'midterm', focus: 'plants',
    })))
    expect(await screen.findByText('Worked out')).toBeTruthy()
    expect(screen.getByText('Check')).toBeTruthy()
    expect(screen.getByText('Double-checked')).toBeTruthy()
    expect(screen.getByText('A second check said: light')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Print quiz' }))
    expect(written[0]).toContain('What do leaves need to make food?')
    expect(written[0]).not.toContain('sunlight')

    fireEvent.click(screen.getByRole('button', { name: 'Print answer key' }))
    expect(written[1]).toContain('sunlight')
  })

  it('draws a picture question on screen and in the printed quiz', async () => {
    mocks.fetchQuizOptions.mockResolvedValue(options({ local_available: true, cloud_provider: null }))
    mocks.generateQuiz.mockResolvedValue({ quiz: { ...quiz, questions: [{
      number: 1, type: 'short_answer', topic: 'fractions', prompt: 'What fraction of the bar is shaded?', options: [],
      answer: '3/4', answer_check: 'computed', diagram: { kind: 'fraction_bar', parts: 4, shaded: 3 },
    }] }, report: { answers_recomputed: 0, dropped: 0, short_by: 0 } })
    const written: string[] = []
    const win = { document: { write: (h: string) => written.push(h), close: vi.fn() }, print: vi.fn() }
    vi.spyOn(window, 'open').mockReturnValue(win as unknown as Window)
    render(<QuizBuilder token="t" studentName="Ava" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    fireEvent.change(await screen.findByLabelText('What to cover'), { target: { value: 'fractions' } })
    fireEvent.click(screen.getByRole('button', { name: 'Draft quiz' }))
    expect(await screen.findByRole('img', { name: /A bar in 4 equal parts, 3 of them shaded/ })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Print quiz' }))
    expect(written[0]).toContain('<svg')
    expect((written[0].match(/<rect/g) ?? []).length).toBe(4)
    expect(written[0]).not.toContain('3/4')
  })

  it('drafts from typed text on the cloud provider when photo reading is off', async () => {
    mocks.fetchQuizOptions.mockResolvedValue(options({ local_available: false, cloud_provider: null, draft_provider: 'OpenAI' }))
    render(<QuizBuilder token="t" studentName="Ava" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    fireEvent.change(await screen.findByLabelText('What to cover'), { target: { value: 'plants' } })
    expect(screen.getByText(/Photos can't be read on this install yet/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Draft quiz' })).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Draft quiz' }))
    await waitFor(() => expect(mocks.generateQuiz).toHaveBeenCalledWith('t', 'Ava', expect.objectContaining({ cloud_consent: true })))
  })

  it('needs the consent tick before a cloud provider drafts anything', async () => {
    mocks.fetchQuizOptions.mockResolvedValue(options({ local_available: false, cloud_provider: 'OpenAI', draft_provider: 'OpenAI' }))
    render(<QuizBuilder token="t" studentName="Ava" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    fireEvent.change(await screen.findByLabelText('What to cover'), { target: { value: 'plants' } })
    expect(screen.getByRole('button', { name: 'Draft quiz' })).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Draft quiz' }))
    await waitFor(() => expect(mocks.generateQuiz).toHaveBeenCalledWith('t', 'Ava', expect.objectContaining({ cloud_consent: true })))
  })

  it('a teacher drafts for a class through the teacher route, with no student and no cloud', async () => {
    mocks.fetchEducatorQuizOptions.mockResolvedValue(options({ local_available: true, cloud_provider: null }))
    mocks.generateEducatorQuiz.mockResolvedValue({ quiz, report: { answers_recomputed: 0, dropped: 0, short_by: 0 } })
    render(<QuizBuilder token="t" audience="educator" />)
    expect(screen.getByText(/on the school’s own AI model/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    fireEvent.change(await screen.findByLabelText('What to cover'), { target: { value: 'plants' } })
    fireEvent.click(screen.getByRole('button', { name: 'Draft quiz' }))
    await waitFor(() => expect(mocks.generateEducatorQuiz).toHaveBeenCalledWith('t', expect.objectContaining({ focus: 'plants', cloud_consent: false })))
    expect(mocks.generateQuiz).not.toHaveBeenCalled()
    expect(mocks.fetchQuizOptions).not.toHaveBeenCalled()
  })

  it('tells a teacher plainly when the school has no local model', async () => {
    mocks.fetchEducatorQuizOptions.mockResolvedValue(options({ local_available: false, cloud_provider: null }))
    render(<QuizBuilder token="t" audience="educator" />)
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    expect(await screen.findByText(/none is set up here/)).toBeTruthy()
  })

  it('every quiz string exists in Spanish too', () => {
    const en = i18n.getResourceBundle('en', 'translation').quizBuilder
    const es = i18n.getResourceBundle('es', 'translation').quizBuilder
    const keys = (o: object, p = ''): string[] => Object.entries(o).flatMap(([k, v]) =>
      typeof v === 'object' ? keys(v, `${p}${k}.`) : [`${p}${k}`])
    expect(keys(es).sort()).toEqual(keys(en).sort())
  })
})
