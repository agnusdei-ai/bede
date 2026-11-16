/**
 * K-2 practical math (docs/K2_PRACTICE.md §5.3): the screen draws what the
 * server sends and asks the server whether an answer is right. These tests
 * pin the three steps, that every line is spoken as well as shown, that a
 * building answer is the number of counters on the frame (reached by drag or
 * by tap), that nothing can be typed, that no score, timer or streak appears
 * and Bede never says "wrong", reduced motion, the target sizes (as a class
 * contract), and that both languages have every key the server can ask for.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import en from '../i18n/locales/en.json'
import es from '../i18n/locales/es.json'
import type { MathLesson } from '../services/api'
import K2MathPractice from './K2MathPractice'

const fetchMathLesson = vi.hoisted(() => vi.fn())
const answerMathTask = vi.hoisted(() => vi.fn())
vi.mock('../services/api', () => ({ fetchMathLesson, answerMathTask }))

const lesson = (): MathLesson => ({
  lesson_id: 'M1', area: 'math', level: '1', topic: 'add', skill: 'oa.add_within_20', your_turn_tries: 2,
  watch: {
    prompt: { key: 'add_build', args: { a: '4', b: '2' } },
    display: { diagram: { kind: 'ten_frame', frames: 1, red: 4 }, guide: true, ghost: 6 },
    choice_kind: 'build', choices: Array.from({ length: 11 }, (_, i) => String(i)),
    build: { start: 4, capacity: 10, take_away: false }, answer: { choice: '6' },
  },
  together: [
    {
      phase: 'together', index: 0, prompt: { key: 'add_build', args: { a: '3', b: '2' } },
      display: { diagram: { kind: 'ten_frame', frames: 1, red: 3 }, guide: true, ghost: 5 },
      choice_kind: 'build', choices: Array.from({ length: 11 }, (_, i) => String(i)),
      build: { start: 3, capacity: 10, take_away: false },
    },
    {
      phase: 'together', index: 1, prompt: { key: 'add_how_many', args: { a: '5', b: '3' } },
      display: { diagram: { kind: 'ten_frame', frames: 1, red: 5, yellow: 3 }, guide: true },
      choice_kind: 'number', choices: ['7', '8', '9'],
    },
  ],
  your_turn: [{
    phase: 'your_turn', index: 0, prompt: { key: 'add_how_many', args: { a: '6', b: '1' } },
    display: { diagram: { kind: 'ten_frame', frames: 1, red: 6, yellow: 1 }, guide: false },
    choice_kind: 'number', choices: ['6', '7', '8'],
  }],
})

const open = async (onSpeak = vi.fn(), onClose = vi.fn()) => {
  render(<K2MathPractice token="tok" studentName="Sam" onClose={onClose} onSpeak={onSpeak} />)
  await screen.findByTestId('math-line')
  return { onSpeak, onClose }
}

let reduceMotion = false
beforeEach(async () => {
  await i18n.changeLanguage('en')
  reduceMotion = false
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: reduceMotion && query.includes('reduce'), media: query,
    addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(),
  })) as unknown as typeof window.matchMedia
  fetchMathLesson.mockReset().mockResolvedValue(lesson())
  answerMathTask.mockReset()
})
afterEach(() => { cleanup(); vi.useRealTimers() })

const SCORE_WORDS = /\b(score|points?|streak|timer|seconds?|wrong|incorrect|fail(ed)?|percent|%)\b/i
const frameCount = () => document.querySelectorAll('[data-testid="math-build-frame"] [data-full]').length

describe('K2MathPractice', () => {
  it('walks Watch, Together, Your turn, speaking every line, and finishes', async () => {
    reduceMotion = true
    const { onSpeak } = await open()
    expect(screen.getByText('Watch').getAttribute('aria-current')).toBe('step')
    expect(onSpeak).toHaveBeenCalledWith('Here are 4. Watch me put in 2 more. Now there are 6.')
    // Watch: the move is shown, and nothing can be moved or checked.
    expect(frameCount()).toBe(6)
    expect(screen.getByRole('button', { name: 'Put in a counter' })).toHaveProperty('disabled', true)
    expect(screen.queryByRole('button', { name: 'Check' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))

    // Together, building: start from the 3 already there, put in 2 by tapping.
    expect(screen.getByText('Together').getAttribute('aria-current')).toBe('step')
    expect(onSpeak).toHaveBeenLastCalledWith('Here are 3. Put in 2 more.')
    expect(frameCount()).toBe(3)
    expect(document.querySelectorAll('[data-ghost]')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Put a counter in box 4' }))
    fireEvent.click(screen.getByRole('button', { name: 'Put in a counter' }))
    answerMathTask.mockResolvedValueOnce({ understood: true, correct: true })
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    await screen.findByText('Yes, that’s it!')
    expect(answerMathTask).toHaveBeenCalledWith('tok', 'Sam', 'M1', 'together', 0, { choice: '5' })
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    // Together, choosing: the guide may name the total.
    expect(screen.getByTestId('math-ten-frame').getAttribute('aria-label')).toBe('A ten-frame with 8 counters, 0 crossed out')
    // A miss shows the answer straight away.
    answerMathTask.mockResolvedValueOnce({ understood: true, correct: false, reveal: { choice: '8' } })
    fireEvent.click(screen.getByRole('button', { name: '9' }))
    await screen.findByText('Here it is. Tap Next when you are ready.')
    expect(document.querySelector('[data-revealed]')?.getAttribute('aria-label')).toBe('8')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    // Your turn: no numbers on the counters.
    expect(screen.getByText('Your turn').getAttribute('aria-current')).toBe('step')
    expect(onSpeak).toHaveBeenLastCalledWith('6 red and 1 yellow. How many in all?')
    expect(document.querySelectorAll('[data-testid="math-ten-frame"] text')).toHaveLength(0)
    // ...and its accessible name does not say how many there are in all.
    expect(screen.getByTestId('math-ten-frame').getAttribute('aria-label')).toBe('A ten-frame with counters')
    expect(screen.getByRole('img', { name: 'A ten-frame with counters' })).toBeTruthy()
    answerMathTask.mockResolvedValueOnce({ understood: true, correct: false, tries_left: 1 })
    fireEvent.click(screen.getByRole('button', { name: '6' }))
    await screen.findByText('Let’s look again. Try once more.')
    answerMathTask.mockResolvedValueOnce({ understood: true, correct: true, recorded: true })
    fireEvent.click(screen.getByRole('button', { name: '7' }))
    await screen.findByText('Yes, that’s it!')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('You finished Number Time!')
    expect(document.body.textContent ?? '').not.toMatch(SCORE_WORDS)
    expect(document.body.textContent ?? '').not.toMatch(/\d+\s*(\/|of|out of)\s*\d+/)
  })

  it('offers nothing to type at any step: an answer is a tap, a count on the frame, or speech', async () => {
    reduceMotion = true
    await open()
    const noTyping = () => {
      expect(screen.queryByRole('textbox')).toBeNull()
      expect(screen.queryByRole('spinbutton')).toBeNull()
      expect(document.querySelector('input, textarea, [contenteditable]')).toBeNull()
    }
    noTyping()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    noTyping()
    answerMathTask.mockResolvedValue({ understood: true, correct: true })
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    await screen.findByText('Yes, that’s it!')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    noTyping()
    // Every answer sent is one of the question's own choices.
    for (const call of answerMathTask.mock.calls) {
      const [, , , phase, index, body] = call
      const task = phase === 'together' ? lesson().together[index] : lesson().your_turn[index]
      expect(task.choices).toContain(body.choice)
    }
  })

  it('builds the answer by dragging a counter from the tray as well as by tapping', async () => {
    reduceMotion = true
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    const frame = screen.getByTestId('math-build-frame')
    const tray = screen.getByTestId('math-tray')
    document.elementFromPoint = vi.fn(() => frame.querySelector('button')) as typeof document.elementFromPoint
    for (let i = 0; i < 2; i += 1) {
      fireEvent.pointerDown(tray, { clientX: 10, clientY: 400, pointerId: 1, pointerType: 'touch' })
      fireEvent.pointerMove(tray, { clientX: 50, clientY: 100, pointerId: 1, pointerType: 'touch' })
      fireEvent.pointerUp(tray, { clientX: 50, clientY: 100, pointerId: 1, pointerType: 'touch' })
    }
    expect(frameCount()).toBe(5)
    answerMathTask.mockResolvedValueOnce({ understood: true, correct: true })
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    await screen.findByText('Yes, that’s it!')
    expect(answerMathTask).toHaveBeenLastCalledWith('tok', 'Sam', 'M1', 'together', 0, { choice: '5' })
  })

  it('in Watch puts the counters on one at a time, or all at once with reduced motion', async () => {
    await open()
    expect(frameCount()).toBe(4)
    await waitFor(() => expect(frameCount()).toBe(6), { timeout: 4000 })
    cleanup()
    reduceMotion = true
    render(<K2MathPractice token="tok" studentName="Sam" onClose={vi.fn()} onSpeak={vi.fn()} />)
    await screen.findByTestId('math-line')
    expect(frameCount()).toBe(6)
  })

  it('in Together, a take-away frame outlines the counters to take, and taking them answers it', async () => {
    reduceMotion = true
    const base = lesson()
    fetchMathLesson.mockResolvedValue({
      ...base, topic: 'subtract',
      together: [{
        phase: 'together', index: 0, prompt: { key: 'subtract_build', args: { a: '9', b: '3' } },
        display: { diagram: { kind: 'ten_frame', frames: 1, red: 9 }, guide: true, ghost: 6 },
        choice_kind: 'build', choices: Array.from({ length: 11 }, (_, i) => String(i)),
        build: { start: 9, capacity: 10, take_away: true },
      }],
    })
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    expect(screen.getByTestId('math-line').textContent).toBe('Here are 9. Take 3 away.')
    expect(Array.from(document.querySelectorAll('[data-remove]')).map((el) => el.getAttribute('aria-label'))).toEqual(
      ['Take this counter away, box 7', 'Take this counter away, box 8', 'Take this counter away, box 9'])
    for (let i = 0; i < 3; i += 1) fireEvent.click(screen.getByRole('button', { name: 'Take one out' }))
    expect(document.querySelectorAll('[data-remove]')).toHaveLength(0)
    answerMathTask.mockResolvedValueOnce({ understood: true, correct: true })
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    await screen.findByText('Yes, that’s it!')
    expect(answerMathTask).toHaveBeenLastCalledWith('tok', 'Sam', 'M1', 'together', 0, { choice: '6' })
  })

  it('a failed check counts nothing and lets the child try again', async () => {
    reduceMotion = true
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    answerMathTask.mockRejectedValueOnce(new Error('offline'))
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    await screen.findByRole('alert')
    expect(screen.getByRole('button', { name: 'Check' })).toHaveProperty('disabled', false)
  })

  it('shows the right count on the frame when the answer is shown', async () => {
    reduceMotion = true
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    answerMathTask.mockResolvedValueOnce({ understood: true, correct: false, reveal: { choice: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Check' }))
    await screen.findByText('Here it is. Tap Next when you are ready.')
    expect(frameCount()).toBe(5)
  })

  it('names the compare choices in words with a counter beside them, never by color alone', async () => {
    reduceMotion = true
    fetchMathLesson.mockResolvedValue({
      ...lesson(), topic: 'compare',
      watch: {
        prompt: { key: 'compare_more', args: {} },
        display: { diagram: { kind: 'counters', groups: [{ color: 'red', count: 3 }, { color: 'yellow', count: 5 }] }, guide: true },
        choice_kind: 'color', choices: ['red', 'yellow', 'same'], answer: { choice: 'yellow' },
      },
    })
    const { onSpeak } = await open()
    expect(onSpeak).toHaveBeenCalledWith(
      'Watch me match each red counter with a yellow one. Some yellow ones have no partner, so there are more yellow.')
    for (const name of ['Red', 'Yellow', 'The same']) expect(screen.getByRole('button', { name })).toBeTruthy()
    expect(document.querySelector('[data-revealed]')?.getAttribute('aria-label')).toBe('Yellow')
  })

  it('shows no score, timer or streak and never says wrong, in either language', () => {
    for (const block of [en.k2Math, es.k2Math]) {
      for (const value of Object.values(flatten(block))) {
        expect(value).not.toMatch(SCORE_WORDS)
        expect(value).not.toMatch(/\b(mal|incorrect[oa]|equivocad[oa]|puntos?|racha)\b/i)
      }
    }
  })

  it('meets the K-2 target sizes by class contract, in rem so they grow with the text', async () => {
    reduceMotion = true
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    for (const button of screen.getAllByRole('button')) {
      expect(button.className, button.outerHTML).toMatch(/min-h-1[46]/)
      expect(button.className, button.outerHTML).not.toMatch(/\b(min-)?[hw]-\[\d+px\]/)
    }
    expect(screen.getByRole('button', { name: 'Check' }).className).toContain('min-h-16')
    const source = readFileSync(join(__dirname, 'K2MathPractice.tsx'), 'utf8')
    expect(source).not.toMatch(/\b(w|min-w|max-w|h)-\[\d+px\]/)
    expect(source).not.toMatch(/style=\{\{[^}]*(width|height)\s*:\s*\d/)
    expect(source).not.toMatch(/framer-motion|react-spring|gsap|lottie/)
    // Choice groups wrap and keep 8px apart.
    expect(source).toMatch(/className="flex flex-wrap justify-center gap-2" role="group"/)
  })

  it('tells the server whether the device can speak, and never fetches while that is unknown', async () => {
    render(<K2MathPractice token="tok" studentName="Sam" onClose={vi.fn()} />)
    await screen.findByTestId('math-line')
    expect(fetchMathLesson).toHaveBeenLastCalledWith('tok', 'Sam', false)
    cleanup()
    fetchMathLesson.mockClear()
    render(<K2MathPractice token="tok" studentName="Sam" onClose={vi.fn()} onSpeak={vi.fn()} canSpeak={null} />)
    await new Promise((r) => setTimeout(r, 20))
    expect(fetchMathLesson).not.toHaveBeenCalled()
  })

  it('has the same keys in English and Spanish, and a line for every question the server asks', () => {
    expect(keys(en.k2Math)).toEqual(keys(es.k2Math))
    const builder = readFileSync(join(__dirname, '../../../homeschool-api/services/k2_practice/practical_math.py'), 'utf8')
    const table = builder.match(/_QUESTION = \{([\s\S]*?)\n\}/)?.[1] ?? ''
    const promptKeys = [...table.matchAll(/"([a-z_]+)":/g)].map((m) => m[1])
    expect(promptKeys.length).toBe(9)
    expect(new Set(promptKeys)).toEqual(new Set(Object.keys(en.k2Math.prompt)))
    expect(new Set(promptKeys)).toEqual(new Set(Object.keys(en.k2Math.watch)))
    // The compare choices the server offers each have a word.
    const compare = builder.match(/COMPARE_CHOICES = \(([^)]*)\)/)?.[1].match(/"(\w+)"/g)?.map((k) => k.slice(1, -1)) ?? []
    expect(new Set(compare)).toEqual(new Set(Object.keys(en.k2Math.choice)))
    expect(new Set(compare)).toEqual(new Set(Object.keys(en.k2Math.compareResult)))
  })

  it('is rerun when the server module changes', () => {
    const workflow = readFileSync(join(__dirname, '../../../.github/workflows/frontend-tests.yml'), 'utf8')
    expect(workflow).toContain("- 'homeschool-api/services/k2_practice/practical_math.py'")
    const filter = workflow.split('\n').find((line) => line.includes('grep -qE')) ?? ''
    expect(filter).toContain('homeschool-api/services/k2_practice/practical_math\\.py')
  })
})

function flatten(obj: object, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(obj)) {
    if (typeof v === 'string') out[prefix + k] = v
    else Object.assign(out, flatten(v as object, `${prefix}${k}.`))
  }
  return out
}

function keys(obj: object): string[] {
  return Object.keys(flatten(obj)).sort()
}
