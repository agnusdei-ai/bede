import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import QuizRunner, { type RunnerQuestion } from './QuizRunner'

const questions: RunnerQuestion[] = [
  { type: 'computation', prompt: '5 + 5 =', options: [], answer: '10', difficulty: 'on', explanation: 'Five and five make ten.' },
  { type: 'computation', prompt: '2 + 1 =', options: [], answer: '3', difficulty: 'easier' },
  { type: 'computation', prompt: '48 ÷ 6 =', options: [], answer: '8', difficulty: 'harder' },
  { type: 'multiple_choice', prompt: 'Which is biggest?', options: ['3', '30', '13'], answer: '30', difficulty: 'on' },
]

beforeEach(() => { void i18n.changeLanguage('en') })
afterEach(cleanup)

const answer = (text: string) => {
  fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: 'Check' }))
}

describe('taking a quiz', () => {
  it('shows the answer and its explanation only after the student answers', () => {
    render(<QuizRunner title="Sums" questions={questions} onFinish={vi.fn()} />)
    expect(screen.getByText('5 + 5 =')).toBeTruthy()
    expect(screen.queryByText(/The answer is/)).toBeNull()
    expect(screen.queryByText('Why: Five and five make ten.')).toBeNull()
    answer('11')
    expect(screen.getByText('Not quite. The answer is 10.')).toBeTruthy()
    expect(screen.getByText('Why: Five and five make ten.')).toBeTruthy()
  })

  it('steps down after a miss and up after a right answer', () => {
    render(<QuizRunner title="Sums" questions={questions} onFinish={vi.fn()} />)
    answer('11')
    fireEvent.click(screen.getByRole('button', { name: 'Next question' }))
    expect(screen.getByText('2 + 1 =')).toBeTruthy()
    answer('3')
    expect(screen.getByText("That's right.")).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Next question' }))
    // Back up to on level (the remaining on-level question), not the hardest.
    expect(screen.getByText('Which is biggest?')).toBeTruthy()
  })

  it('checks a choice when it is tapped and reports the total at the end', () => {
    const onFinish = vi.fn()
    render(<QuizRunner title="Sums" questions={questions.slice(3)} onFinish={onFinish} />)
    fireEvent.click(screen.getByRole('button', { name: 'B) 30' }))
    expect(screen.getByText("That's right.")).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'See how it went' }))
    expect(screen.getByText('You got 1 of 1 right.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onFinish).toHaveBeenCalledWith({ total: 1, right: 1, wrong: 0, open: 0 })
  })
})
