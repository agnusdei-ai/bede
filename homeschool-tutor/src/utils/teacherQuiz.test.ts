import { describe, expect, it } from 'vitest'
import type { GeneratedQuiz, ProposedScore } from '../services/api'
import {
  addQuestion, allSettled, blankQuiz, editQuestion, exportFile, fromGenerated, initialSettlement,
  needsLook, parseImport, removeQuestion, settleQuestion,
} from './teacherQuiz'

const generated: GeneratedQuiz = {
  title: 'Plants', subject: 'science', grade: '4', kind: 'quiz', level: 'on_level', coverage: [], est_minutes: 3,
  questions: [
    { number: 1, type: 'short_answer', topic: '', prompt: 'What do leaves need?', options: [], answer: 'sunlight', answer_check: 'verify', second_answer: 'light' },
    { number: 4, type: 'computation', topic: '', prompt: '12 × 3 =', options: [], answer: '36', answer_check: 'computed' },
  ],
}

describe('teacher quiz helpers', () => {
  it('turns a drafted quiz into Bede suggestions the teacher has not approved', () => {
    const quiz = fromGenerated(generated)
    expect(quiz.questions.map((q) => [q.number, q.key_source, q.key_approved])).toEqual([[1, 'bede', false], [2, 'bede', false]])
    expect(quiz.questions[0].reading_note).toContain('light')
    expect(quiz.approved).toBe(false)
    expect(quiz.questions.every(needsLook)).toBe(true)
  })

  it('typing an answer makes it the teacher’s own, and any edit un-approves the quiz', () => {
    const quiz = { ...fromGenerated(generated), approved: true }
    const edited = editQuestion(quiz, 1, { answer: '37' })
    expect(edited.questions[1]).toMatchObject({ answer: '37', key_source: 'teacher', key_approved: true, answer_check: null })
    expect(edited.approved).toBe(false)
    const reworded = editQuestion({ ...edited, approved: true }, 0, { prompt: 'What do green leaves need?' })
    expect(reworded.questions[0].key_source).toBe('bede')  // a prompt edit does not approve the answer
    expect(reworded.approved).toBe(false)
  })

  it('Looks right settles the reading and the answer, and nothing else', () => {
    const quiz = fromGenerated(generated)
    const settled = settleQuestion(quiz, 0)
    expect(settled.questions[0]).toMatchObject({ key_approved: true, reading_note: null, key_source: 'bede' })
    expect(needsLook(settled.questions[0])).toBe(false)
    expect(needsLook(settled.questions[1])).toBe(true)
  })

  it('keeps questions numbered in order as they are added and removed', () => {
    const quiz = addQuestion(addQuestion(blankQuiz('history', '5', 'Rome')))
    expect(removeQuestion(quiz, 0).questions.map((q) => q.number)).toEqual([1, 2])
    expect(removeQuestion(blankQuiz('history', '5', 'Rome'), 0).questions).toHaveLength(1)
  })

  it('a saved file opens again, and anything else is refused', () => {
    const quiz = fromGenerated(generated)
    expect(parseImport(exportFile(quiz))).toEqual(quiz)
    expect(parseImport('{"title":"x","questions":[]}')).toBeNull()
    expect(parseImport('not json')).toBeNull()
  })

  it('a result marked for the teacher does not count until the teacher settles it', () => {
    const results: ProposedScore[] = [
      { number: 1, response: '42', max_points: 1, proposed_points: 1, method: 'numeric', needs_teacher: false, reasons: [] },
      { number: 2, response: 'paris', max_points: 1, proposed_points: 1, method: 'key_match', needs_teacher: true, reasons: ['reading_uncertain'] },
    ]
    const settled = initialSettlement(results)
    expect(settled).toEqual({ 1: 1, 2: null })
    expect(allSettled(settled, results)).toBe(false)
    expect(allSettled({ ...settled, 2: 0 }, results)).toBe(true)
  })
})
