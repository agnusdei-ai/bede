import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  PracticeConsentRequired, TeacherQuizProblems, approveTeacherQuiz, scoreTeacherQuiz, type TeacherQuiz,
} from './api'

// The real client functions, with only the network stubbed: the route each
// one calls and how each refusal reaches the screen.

const quiz: TeacherQuiz = {
  format: 'bede.teacher-quiz', version: 1, title: 'q', subject: 'history', grade: '4', approved: false,
  questions: [{ number: 1, type: 'short_answer', prompt: 'p', options: [], answer: 'a', accepted_answers: [], points: 1, key_source: 'bede', key_approved: false }],
}

function reply(status: number, body: unknown) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(body), { status }))
}

afterEach(() => vi.restoreAllMocks())

describe('teacher quiz API client', () => {
  it('posts to the educator teacher-quiz route with the token', async () => {
    const spy = reply(200, { quiz: { ...quiz, approved: true }, problems: [] })
    const out = await approveTeacherQuiz('tok', quiz)
    expect(out.quiz.approved).toBe(true)
    const [url, init] = spy.mock.calls[0]
    expect(String(url)).toMatch(/\/practice\/educator\/teacher-quiz\/approve$/)
    expect((init!.headers as Record<string, string>).Authorization).toBe('Bearer tok')
    expect(JSON.parse(init!.body as string)).toEqual({ quiz })
  })

  it('a refused key arrives as the list of problems to settle', async () => {
    reply(422, { detail: { problems: [{ number: 1, problem: 'key_not_approved' }], message: 'm' } })
    await expect(approveTeacherQuiz('tok', quiz)).rejects.toBeInstanceOf(TeacherQuizProblems)
  })

  it('a missing upload tick arrives as a consent request naming the school model', async () => {
    reply(409, { detail: { consent_required: true, provider: "the school's own AI model", message: 'm' } })
    const err = await scoreTeacherQuiz('tok', { quiz, pages: [{ data: 'x' }], responses: [], upload_consent: false }).catch((e) => e)
    expect(err).toBeInstanceOf(PracticeConsentRequired)
    expect(err.provider).toBe("the school's own AI model")
  })

  it('an honest no-local-model refusal is shown as the server wrote it', async () => {
    reply(409, { detail: "Teacher quizzes are read on the school's own AI model, and none is set up on this install." })
    await expect(scoreTeacherQuiz('tok', { quiz, pages: [{ data: 'x' }], responses: [], upload_consent: true }))
      .rejects.toThrow(/none is set up/)
  })
})
