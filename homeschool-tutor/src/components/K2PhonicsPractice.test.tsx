/**
 * K-2 phonics practice (docs/K2_PRACTICE.md §5.1): the screen draws what the
 * server sends and asks the server whether a tap is right. These tests pin
 * the three steps, that every line is spoken as well as shown, that "Your
 * turn" never reads the word aloud when reading it is the skill, that no
 * score, timer or streak appears and Bede never says "wrong", the target
 * sizes (as a class contract, since jsdom lays nothing out), reduced motion,
 * and that both languages have every key.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import en from '../i18n/locales/en.json'
import es from '../i18n/locales/es.json'
import type { PhonicsLesson } from '../services/api'
import K2PhonicsPractice, { PRIMARY, TARGET } from './K2PhonicsPractice'

const fetchPhonicsLesson = vi.hoisted(() => vi.fn())
const answerPhonicsTask = vi.hoisted(() => vi.fn())
vi.mock('../services/api', () => ({ fetchPhonicsLesson, answerPhonicsTask }))

const g = (text: string, sound: string) => ({ text, sound })

const lesson = (): PhonicsLesson => ({
  lesson_id: 'L1', area: 'phonics', level: '1', domain: 'cvc_blending', your_turn_tries: 2,
  watch: {
    prompt: { key: 'read_word_choice', args: {} },
    display: { kind: 'word', word: 'cat', graphemes: [g('c', 'kuh'), g('a', 'ah'), g('t', 'tuh')] },
    choice_kind: 'picture', choices: ['dog', 'cat', 'sun'], answer: { choice: 'cat' },
  },
  together: [{
    phase: 'together', index: 0, prompt: { key: 'read_word_choice', args: {} },
    display: { kind: 'word', word: 'pig', graphemes: [g('p', 'puh'), g('i', 'ih'), g('g', 'guh')] },
    choice_kind: 'picture', choices: ['pig', 'bus', 'hat'],
  }],
  your_turn: [{
    phase: 'your_turn', index: 0, prompt: { key: 'read_word_choice', args: {} },
    display: { kind: 'word', graphemes: [{ text: 'm' }, { text: 'a' }, { text: 'p' }] },
    choice_kind: 'picture', choices: ['map', 'cup', 'fox'],
  }],
})

const open = async (onSpeak = vi.fn(), onClose = vi.fn()) => {
  render(<K2PhonicsPractice token="tok" studentName="Sam" onClose={onClose} onSpeak={onSpeak} />)
  await screen.findByTestId('phonics-line')
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
  fetchPhonicsLesson.mockReset().mockResolvedValue(lesson())
  answerPhonicsTask.mockReset()
})
afterEach(() => { cleanup(); vi.useRealTimers() })

const SCORE_WORDS = /\b(score|points?|streak|timer|seconds?|wrong|incorrect|fail(ed)?|percent|%)\b/i

describe('K2PhonicsPractice', () => {
  it('walks Watch, Together, Your turn, speaking every line, and finishes', async () => {
    const { onSpeak } = await open()
    expect(screen.getByText('Watch').getAttribute('aria-current')).toBe('step')
    // Watch: the move is shown and spoken, and nothing can be tapped.
    expect(onSpeak).toHaveBeenCalledWith('Listen: kuh, ah, tuh. Put the sounds together: cat!')
    expect(document.querySelector('[data-revealed]')?.getAttribute('aria-label')).toBe('cat')
    expect(screen.getByRole('button', { name: 'cat' })).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))

    expect(screen.getByText('Together').getAttribute('aria-current')).toBe('step')
    expect(onSpeak).toHaveBeenLastCalledWith('Read the word. Tap its picture.')
    // Together: tapping a letter says its sound.
    fireEvent.click(screen.getByRole('button', { name: 'Hear p' }))
    expect(onSpeak).toHaveBeenLastCalledWith('puh')
    answerPhonicsTask.mockResolvedValueOnce({ understood: true, correct: false, reveal: { choice: 'pig' } })
    fireEvent.click(screen.getByRole('button', { name: 'bus' }))
    await screen.findByText('Here it is. Tap Next when you are ready.')
    expect(answerPhonicsTask).toHaveBeenCalledWith('tok', 'Sam', 'L1', 'together', 0, { choice: 'bus' })
    expect(document.querySelector('[data-revealed]')?.getAttribute('aria-label')).toBe('pig')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    expect(screen.getByText('Your turn').getAttribute('aria-current')).toBe('step')
    // No letter sounds to tap in Your turn: the reading is the child's.
    expect(screen.queryByRole('button', { name: /^Hear [a-z]$/ })).toBeNull()
    answerPhonicsTask.mockResolvedValueOnce({ understood: true, correct: false, tries_left: 1 })
    fireEvent.click(screen.getByRole('button', { name: 'cup' }))
    await screen.findByText('Let’s look again. Try once more.')
    answerPhonicsTask.mockResolvedValueOnce({ understood: true, correct: true, recorded: true })
    fireEvent.click(screen.getByRole('button', { name: 'map' }))
    await screen.findByText('Yes, that’s it!')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByText('You finished Sound Time!')
    // The finish is a stopping point, never a tally.
    expect(document.body.textContent ?? '').not.toMatch(SCORE_WORDS)
    expect(document.body.textContent ?? '').not.toMatch(/\d+\s*(\/|of|out of)\s*\d+/)
  })

  it('never speaks the word in Your turn when reading it is the skill', async () => {
    const { onSpeak } = await open()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    answerPhonicsTask.mockResolvedValueOnce({ understood: true, correct: true })
    fireEvent.click(screen.getByRole('button', { name: 'pig' }))
    await screen.findByText('Yes, that’s it!')
    onSpeak.mockClear()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    const spoken = onSpeak.mock.calls.map((c) => c[0]).join(' | ')
    expect(spoken).toBe('Read the word. Tap its picture.')
    expect(spoken).not.toMatch(/\bmap\b/)
    fireEvent.click(screen.getByRole('button', { name: 'Hear it again' }))
    expect(onSpeak).toHaveBeenLastCalledWith('Read the word. Tap its picture.')
  })

  it('in Your turn says the cue word aloud but never shows it written when that would give the answer', async () => {
    const letters: PhonicsLesson = {
      ...lesson(), level: 'K', domain: 'letter_sound',
      watch: {
        prompt: { key: 'first_sound_choice', args: { word: 'sun' } },
        display: { kind: 'picture', icon: 'sun', word: 'sun' },
        choice_kind: 'letter', choices: ['s', 'm', 'd'], choice_sounds: { s: 'sss', m: 'mmm', d: 'duh' },
        answer: { choice: 's' },
      },
      together: [{
        phase: 'together', index: 0, prompt: { key: 'first_sound_choice', args: { word: 'moon' } },
        display: { kind: 'picture', icon: 'moon', word: 'moon' }, choice_kind: 'letter', choices: ['m', 'r', 't'],
        choice_sounds: { m: 'mmm', r: 'rrr', t: 'tuh' },
      }],
      your_turn: [{
        phase: 'your_turn', index: 0, prompt: { key: 'first_sound_choice', args: { word: 'pig' } },
        display: { kind: 'picture', icon: 'pig', word: 'pig' }, choice_kind: 'letter', choices: ['p', 'b', 'h'],
      }],
    }
    fetchPhonicsLesson.mockResolvedValue(letters)
    const { onSpeak } = await open()
    expect(onSpeak).toHaveBeenCalledWith('sun starts with the sound sss. We write that sound s.')
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    // Together is guided: the word may be shown, and a tapped letter says its sound.
    expect(screen.getByTestId('phonics-line').textContent).toBe('Which letter starts moon?')
    answerPhonicsTask.mockResolvedValueOnce({ understood: true, correct: true })
    fireEvent.click(screen.getByRole('button', { name: 'm' }))
    expect(onSpeak).toHaveBeenCalledWith('mmm')
    await screen.findByText('Yes, that’s it!')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('Your turn').getAttribute('aria-current')).toBe('step')
    expect(onSpeak).toHaveBeenLastCalledWith('Which letter starts pig?')
    expect(screen.getByTestId('phonics-line').textContent).toBe('Which letter does it start with?')
    expect(screen.getByTestId('phonics-line').textContent).not.toMatch(/\bpig\b/)
    fireEvent.click(screen.getByRole('button', { name: 'Hear it again' }))
    expect(onSpeak).toHaveBeenLastCalledWith('Which letter starts pig?')
  })

  it('shows no score, timer or streak and never says wrong, in either language', async () => {
    for (const locale of ['en', 'es']) {
      await i18n.changeLanguage(locale)
      for (const value of Object.values(flatten(locale === 'en' ? en.k2Phonics : es.k2Phonics))) {
        expect(value).not.toMatch(SCORE_WORDS)
        expect(value).not.toMatch(/\b(mal|incorrect[oa]|equivocad[oa]|puntos?|racha)\b/i)
      }
    }
    await i18n.changeLanguage('en')
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    answerPhonicsTask.mockResolvedValueOnce({ understood: true, correct: false, reveal: { choice: 'pig' } })
    fireEvent.click(screen.getByRole('button', { name: 'bus' }))
    await screen.findByText('Here it is. Tap Next when you are ready.')
    expect(document.body.textContent ?? '').not.toMatch(SCORE_WORDS)
  })

  it('a failed check counts nothing and lets the child try again', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    answerPhonicsTask.mockRejectedValueOnce(new Error('offline'))
    fireEvent.click(screen.getByRole('button', { name: 'pig' }))
    await screen.findByRole('alert')
    expect(screen.getByRole('button', { name: 'pig' })).toHaveProperty('disabled', false)
  })

  it('reveals the letters one at a time, or all at once with reduced motion', async () => {
    // Real timers and waitFor, not a fixed fake-timer advance: under CI load
    // the reveal's interval could start after a fixed advance had run, which
    // read as no letters lit.
    await open()
    const letters = () => Array.from(document.querySelectorAll('[data-testid="phonics-word"] > *'))
    const lit = () => letters().filter((el) => el.className.includes('opacity-100'))
    expect(lit()).toHaveLength(0)
    await waitFor(() => expect(lit()).toHaveLength(3), { timeout: 4000 })
    // Movement is only ever under motion-safe.
    for (const el of letters()) expect(el.className).toMatch(/motion-safe:transition/)
    cleanup()

    // Reduced motion: every letter is there on the very first frame.
    reduceMotion = true
    render(<K2PhonicsPractice token="tok" studentName="Sam" onClose={vi.fn()} onSpeak={vi.fn()} />)
    await screen.findByTestId('phonics-word')
    expect(lit()).toHaveLength(3)
  })

  it('meets the K-2 target sizes by class contract, in rem so they grow with the text', async () => {
    // jsdom performs no layout, so this checks the classes that set the size.
    // Tailwind's min-h-14 is 3.5rem (56px) and min-h-16 is 4rem (64px) at the
    // default text size, and both scale with the text-size control.
    expect(TARGET).toContain('min-h-14')
    expect(TARGET).toContain('min-w-14')
    expect(PRIMARY).toContain('min-h-16')
    expect(PRIMARY).toContain('min-w-16')
    await open()
    for (const button of screen.getAllByRole('button')) {
      const cls = button.className
      expect(cls, button.outerHTML).toMatch(/min-h-1[46]/)
      expect(cls, button.outerHTML).not.toMatch(/\b(min-)?[hw]-\[\d+px\]/)
    }
    const primary = screen.getByRole('button', { name: 'Let’s try one' })
    expect(primary.className).toContain('min-h-16')
    // Groups of targets keep 8px (gap-2) apart and wrap rather than scroll.
    for (const group of [screen.getByRole('group'), screen.getByTestId('phonics-word')]) {
      expect(group.className).toContain('flex-wrap')
      expect(group.className).toMatch(/\bgap-2\b/)
    }
  })

  it('uses no fixed pixel sizes that would force sideways scrolling at 200% text', () => {
    const source = readFileSync(join(__dirname, 'K2PhonicsPractice.tsx'), 'utf8')
    expect(source).not.toMatch(/\b(w|min-w|max-w|h)-\[\d+px\]/)
    expect(source).not.toMatch(/style=\{\{[^}]*(width|height)\s*:\s*\d/)
    expect(source).not.toMatch(/framer-motion|react-spring|gsap|lottie/)
  })

  it('asks for a lesson without ear-only questions when the device cannot speak', async () => {
    // No speaker at all (Bede's voice off).
    render(<K2PhonicsPractice token="tok" studentName="Sam" onClose={vi.fn()} />)
    await screen.findByTestId('phonics-line')
    expect(fetchPhonicsLesson).toHaveBeenLastCalledWith('tok', 'Sam', false)
    cleanup()
    // A speaker, but Bede's voice is off.
    render(<K2PhonicsPractice token="tok" studentName="Sam" onClose={vi.fn()} onSpeak={vi.fn()} canSpeak={false} />)
    await screen.findByTestId('phonics-line')
    expect(fetchPhonicsLesson).toHaveBeenLastCalledWith('tok', 'Sam', false)
    cleanup()
    // Able to speak.
    await open()
    expect(fetchPhonicsLesson).toHaveBeenLastCalledWith('tok', 'Sam', true)
  })

  it('fetches nothing while it is still checking whether the device can speak', async () => {
    const { rerender } = render(
      <K2PhonicsPractice token="tok" studentName="Sam" onClose={vi.fn()} onSpeak={vi.fn()} canSpeak={null} />)
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    expect(fetchPhonicsLesson).not.toHaveBeenCalled()
    rerender(<K2PhonicsPractice token="tok" studentName="Sam" onClose={vi.fn()} onSpeak={vi.fn()} canSpeak />)
    await screen.findByTestId('phonics-line')
    expect(fetchPhonicsLesson).toHaveBeenCalledWith('tok', 'Sam', true)
  })

  it('says a sight-word round needs sound, offers nothing to answer, and sends nothing', async () => {
    fetchPhonicsLesson.mockResolvedValue({
      lesson_id: 'L9', area: 'phonics', level: '2', domain: 'sight_words', your_turn_tries: 2,
      audio: false, needs_audio: true, watch: null, together: [], your_turn: [],
    })
    const onClose = vi.fn()
    render(<K2PhonicsPractice token="tok" studentName="Sam" onClose={onClose} />)
    expect((await screen.findByTestId('phonics-needs-sound')).textContent).toBe(en.k2Phonics.needsSound)
    // Bede's voice is the only voice a round uses, so turning it on is the one fix.
    expect(en.k2Phonics.needsSound).toMatch(/turn on Bede's voice/)
    expect(en.k2Phonics.needsSound).not.toMatch(/install a voice/)
    expect(es.k2Phonics.needsSound).toMatch(/active la voz de Bede/)
    expect(es.k2Phonics.needsSound).not.toMatch(/instale una voz/)
    expect(screen.queryByRole('group', { name: 'Pick an answer' })).toBeNull()
    fireEvent.click(screen.getAllByRole('button', { name: 'Back to Bede' }).pop()!)
    expect(onClose).toHaveBeenCalled()
    expect(answerPhonicsTask).not.toHaveBeenCalled()
  })

  it('has the same keys in English and Spanish, and a line for every question the server asks', () => {
    expect(keys(en.k2Phonics)).toEqual(keys(es.k2Phonics))
    const builder = readFileSync(join(__dirname, '../../../homeschool-api/services/k2_practice/phonics.py'), 'utf8')
    const promptKeys = [...builder.matchAll(/Task\(domain, "([a-z_]+)"/g)].map((m) => m[1])
    expect(new Set(promptKeys)).toEqual(new Set(Object.keys(en.k2Phonics.prompt)))
    expect(new Set(promptKeys)).toEqual(new Set(Object.keys(en.k2Phonics.watch)))
    expect(promptKeys.length).toBe(4)
  })

  it('is rerun when the server module changes', () => {
    const workflow = readFileSync(join(__dirname, '../../../.github/workflows/frontend-tests.yml'), 'utf8')
    expect(workflow).toContain("- 'homeschool-api/services/k2_practice/phonics.py'")
    const filter = workflow.split('\n').find((line) => line.includes('grep -qE')) ?? ''
    expect(filter).toContain('homeschool-api/services/k2_practice/phonics\\.py')
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
