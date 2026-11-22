import { describe, expect, it } from 'vitest'
import { checkAnswer, nextQuestion, parseNumber, stepLevel, type RunnableQuestion } from './quizRunner'

const mc: RunnableQuestion = { type: 'multiple_choice', prompt: 'Who built the pyramids?', options: ['Romans', 'Egyptians', 'Vikings'], answer: 'Egyptians' }
const num: RunnableQuestion = { type: 'computation', prompt: '48 ÷ 6 =', options: [], answer: '8' }
const frac: RunnableQuestion = { type: 'short_answer', prompt: 'How much is shaded?', options: [], answer: '3/4' }
const words: RunnableQuestion = { type: 'short_answer', prompt: 'Which river flooded?', options: [], answer: 'the Nile' }

describe('checking an answer', () => {
  it('checks a choice by its text or its letter', () => {
    expect(checkAnswer(mc, 'egyptians')).toBe('right')
    expect(checkAnswer(mc, 'B')).toBe('right')
    expect(checkAnswer(mc, 'a')).toBe('wrong')
  })
  it('checks numbers, fractions and mixed numbers by value', () => {
    expect(checkAnswer(num, ' 8 ')).toBe('right')
    expect(checkAnswer(num, '9')).toBe('wrong')
    expect(checkAnswer(frac, '0.75')).toBe('right')
    expect(parseNumber('1 1/2')).toBe(1.5)
  })
  it('never marks a worded answer wrong just because the words differ', () => {
    expect(checkAnswer(words, 'The Nile!')).toBe('right')
    expect(checkAnswer(words, 'the river Nile')).toBe('open')
    expect(checkAnswer({ ...words, type: 'written_response' }, 'the Nile')).toBe('open')
  })
})

describe('adapting the next question', () => {
  const pool: RunnableQuestion[] = [
    { ...num, difficulty: 'on' }, { ...num, difficulty: 'easier' }, { ...num, difficulty: 'harder' }, { ...num, difficulty: 'on' },
  ]
  it('steps up after a right answer, down after a miss, and holds on an open one', () => {
    expect(stepLevel('on', 'right')).toBe('harder')
    expect(stepLevel('on', 'wrong')).toBe('easier')
    expect(stepLevel('harder', 'right')).toBe('harder')
    expect(stepLevel('on', 'open')).toBe('on')
  })
  it('picks the next unanswered question at the target level, else the nearest', () => {
    expect(nextQuestion(pool, new Set(), 'on')).toBe(0)
    expect(nextQuestion(pool, new Set([0]), 'harder')).toBe(2)
    expect(nextQuestion(pool, new Set([0, 2]), 'harder')).toBe(3)
    expect(nextQuestion(pool, new Set([0, 1, 2, 3]), 'on')).toBeNull()
  })
})
