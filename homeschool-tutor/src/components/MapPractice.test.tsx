/**
 * Map practice (K-2): the screen draws what the server sends and asks the
 * server whether an answer is right. These tests pin the three steps, that
 * "Your turn" shows no hints, that a failed check never crashes or counts,
 * and that both languages have a sentence for every question the server
 * can ask (homeschool-api/services/map_practice.py).
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import en from '../i18n/locales/en.json'
import es from '../i18n/locales/es.json'
import type { MapLesson, MapScene as Scene } from '../services/api'
import { mapTransport } from '../services/practiceTransports'
import MapPractice, { promptText } from './MapPractice'
import { KNOWN_SYMBOLS } from './MapScene'

const fetchMapLesson = vi.hoisted(() => vi.fn())
const answerMapTask = vi.hoisted(() => vi.fn())
vi.mock('../services/api', () => ({ fetchMapLesson, answerMapTask }))

const scene = (extra: Partial<Scene> = {}): Scene => ({
  cols: 3, rows: 3, style: 'map',
  items: [{ symbol: 'house', col: 1, row: 1 }, { symbol: 'tree', col: 1, row: 0 }],
  water: [], path: [], compass: 'labeled', grid_labels: false, key: false, ...extra,
})

const lesson = (): MapLesson => ({
  lesson_id: 'L1', level: '1', skill: 'four_directions', your_turn_tries: 2,
  watch: {
    scene: scene(), prompt: { key: 'direction_tap', args: { direction: 'north', reference: 'house' } },
    answer_kind: 'tap', guide_cells: [[1, 0]], answer: { cell: [1, 0] },
  },
  together: [{
    phase: 'together', index: 0, scene: scene(),
    prompt: { key: 'direction_tap', args: { direction: 'north', reference: 'house' } },
    answer_kind: 'tap', guide_cells: [[1, 0]],
  }],
  your_turn: [{
    phase: 'your_turn', index: 0, scene: scene({ compass: 'north_only' }),
    prompt: { key: 'direction_choice', args: { thing: 'tree', reference: 'house' } },
    answer_kind: 'choice', choices: ['north', 'south', 'east', 'west'],
  }],
})

const open = async (onClose = vi.fn(), onSpeak?: (s: string) => void) => {
  render(<MapPractice transport={mapTransport('tok', 'Sam')} onClose={onClose} onSpeak={onSpeak} />)
  await screen.findByTestId('map-question')
  return onClose
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
  fetchMapLesson.mockReset().mockResolvedValue(lesson())
  answerMapTask.mockReset()
})
afterEach(cleanup)

describe('MapPractice', () => {
  it('walks Watch, Together, Your turn and finishes', async () => {
    const onClose = await open()
    expect(screen.getByText('Watch').getAttribute('aria-current')).toBe('step')
    // Watch shows the move: the answer is marked and nothing can be tapped.
    expect(document.querySelector('[data-revealed]')).not.toBeNull()
    expect(screen.queryByRole('button', { name: /Square B1/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))

    expect(screen.getByText('Together').getAttribute('aria-current')).toBe('step')
    expect(document.querySelector('[data-guide]')).not.toBeNull()
    answerMapTask.mockResolvedValueOnce({ understood: true, correct: true })
    fireEvent.click(screen.getByRole('button', { name: 'Square B1: tree' }))
    await screen.findByText('Yes, that’s it!')
    expect(answerMapTask).toHaveBeenCalledWith('tok', 'Sam', 'L1', 'together', 0, { cell: [1, 0] })
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    expect(screen.getByText('Your turn').getAttribute('aria-current')).toBe('step')
    answerMapTask.mockResolvedValueOnce({ understood: true, correct: true, recorded: true })
    fireEvent.click(screen.getByRole('button', { name: 'north' }))
    await screen.findByText('Yes, that’s it!')
    expect(answerMapTask).toHaveBeenLastCalledWith('tok', 'Sam', 'L1', 'your_turn', 0, { choice: 'north' })
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    await screen.findByText('You finished the map practice!')
    fireEvent.click(screen.getAllByRole('button', { name: 'Back to Bede' })[1])
    expect(onClose).toHaveBeenCalled()
  })

  it('shows no hints in Your turn, even if a lesson carried some', async () => {
    const withHints = lesson()
    withHints.your_turn[0] = { ...withHints.together[0], phase: 'your_turn' }
    fetchMapLesson.mockResolvedValue(withHints)
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    answerMapTask.mockResolvedValueOnce({ understood: true, correct: true })
    fireEvent.click(screen.getByRole('button', { name: 'Square B1: tree' }))
    await screen.findByText('Yes, that’s it!')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('Your turn').getAttribute('aria-current')).toBe('step')
    expect(document.querySelector('[data-guide]')).toBeNull()
  })

  it('lets the child try again after a miss, then shows the answer', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    answerMapTask.mockResolvedValueOnce({ understood: true, correct: true })
    fireEvent.click(screen.getByRole('button', { name: 'Square B1: tree' }))
    await screen.findByText('Yes, that’s it!')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))

    answerMapTask.mockResolvedValueOnce({ understood: true, correct: false, tries_left: 1 })
    fireEvent.click(screen.getByRole('button', { name: 'south' }))
    await screen.findByText(/Not quite/)
    expect(screen.queryByRole('button', { name: 'Next' })).toBeNull()

    answerMapTask.mockResolvedValueOnce({ understood: true, correct: false, tries_left: 0, reveal: { choice: 'north' } })
    fireEvent.click(screen.getByRole('button', { name: 'east' }))
    await screen.findByText('The answer is marked in green.')
    expect(screen.getByRole('button', { name: 'north' }).hasAttribute('data-revealed')).toBe(true)
    expect((screen.getByRole('button', { name: 'south' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByRole('button', { name: 'Next' })).toBeTruthy()
  })

  it('says so and lets the child retry when an answer cannot be checked', async () => {
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Let’s try one' }))
    answerMapTask.mockRejectedValueOnce(new TypeError('Load failed'))
    fireEvent.click(screen.getByRole('button', { name: 'Square B1: tree' }))
    await screen.findByText('That could not be checked. Try again.')
    expect(screen.queryByText(/Load failed/)).toBeNull()
    answerMapTask.mockResolvedValueOnce({ understood: true, correct: true })
    fireEvent.click(screen.getByRole('button', { name: 'Square B1: tree' }))
    await screen.findByText('Yes, that’s it!')
  })

  it('offers a retry when the lesson cannot be loaded, and the way back still works', async () => {
    fetchMapLesson.mockReset().mockRejectedValueOnce(new Error('map practice 503')).mockResolvedValue(lesson())
    const onClose = vi.fn()
    render(<MapPractice transport={mapTransport('tok', 'Sam')} onClose={onClose} />)
    await screen.findByText('The map could not be loaded.')
    fireEvent.click(screen.getByRole('button', { name: 'Back to Bede' }))
    expect(onClose).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await screen.findByTestId('map-question')
  })

  it('reads each question aloud once when a voice is given', async () => {
    const onSpeak = vi.fn()
    await open(vi.fn(), onSpeak)
    await waitFor(() => expect(onSpeak).toHaveBeenCalledTimes(1))
    expect(onSpeak).toHaveBeenCalledWith('Tap what is north of the house.')
  })

  it('draws only known symbols', async () => {
    const odd = lesson()
    odd.watch.scene.items.push({ symbol: 'street_sign', col: 0, row: 0 })
    fetchMapLesson.mockResolvedValue(odd)
    await open()
    expect(document.body.textContent).not.toContain('street_sign')
  })
})

describe('map practice wording', () => {
  const server = readFileSync(join(__dirname, '../../../homeschool-api/services/map_practice.py'), 'utf8')

  it('has a sentence in both languages for every question the server can ask', () => {
    const keys = new Set([...server.matchAll(/"([a-z_]+_(?:tap|choice|match))"/g)].map((m) => m[1]))
    keys.delete('scene_choice') // an answer kind, not a question
    expect(keys.size).toBeGreaterThanOrEqual(14)
    for (const key of keys) {
      expect(en.mapPractice.prompt, key).toHaveProperty(key)
      expect(es.mapPractice.prompt, key).toHaveProperty(key)
    }
  })

  it('is rerun when the server module changes', () => {
    // Without the module in the workflow's filters, a change to the server's
    // questions would skip this suite.
    const workflow = readFileSync(join(__dirname, '../../../.github/workflows/frontend-tests.yml'), 'utf8')
    expect(workflow).toContain("- 'homeschool-api/services/map_practice.py'")
    const filter = workflow.split('\n').find((line) => line.includes('grep -qE')) ?? ''
    expect(filter).toContain('homeschool-api/services/map_practice\\.py')
  })

  it('names every symbol the server can draw, in both languages', () => {
    const block = server.match(/^SYMBOLS[^=]*=\s*\(([^)]*)\)/m)
    const symbols = [...(block?.[1] ?? '').matchAll(/"([a-z]+)"/g)].map((m) => m[1])
    expect(symbols.length).toBeGreaterThan(5)
    expect([...KNOWN_SYMBOLS].sort()).toEqual([...symbols].sort())
    for (const locale of [en, es]) {
      for (const family of ['symbol', 'symbolThe', 'symbolOf'] as const) {
        expect(Object.keys(locale.mapPractice[family]).sort()).toEqual([...symbols].sort())
      }
    }
  })

  it('leaves no unfilled gap in any sentence', async () => {
    const prompts: [string, Record<string, string | number>][] = [
      ['position_choice', { thing: 'barn', reference: 'well' }],
      ['next_to_tap', { reference: 'pond' }],
      ['path_end_tap', { start: 'gate' }],
      ['find_symbol_tap', { thing: 'pond' }],
      ['direction_tap', { direction: 'east', reference: 'house' }],
      ['direction_choice', { thing: 'gate', reference: 'house' }],
      ['place_tap', { thing: 'rock', direction: 'north', reference: 'tree' }],
      ['walk_tap', { start: 'gate', first_steps: 2, first: 'east', second_steps: 1, second: 'north' }],
      ['square_tap', { square: 'C4' }],
      ['square_choice', { thing: 'rock' }],
      ['ground_tap', { ground: 'land' }],
      ['ground_choice', { square: 'C5' }],
    ]
    for (const lng of ['en', 'es']) {
      await i18n.changeLanguage(lng)
      for (const [key, args] of prompts) {
        const text = promptText(i18n.t.bind(i18n), { key, args })
        expect(text, `${lng} ${key}`).not.toMatch(/\{\{|mapPractice\.|undefined/)
      }
    }
    await i18n.changeLanguage('es')
    expect(promptText(i18n.t.bind(i18n), { key: 'direction_tap', args: { direction: 'east', reference: 'house' } }))
      .toBe('Toca lo que está al este de la casa.')
  })
})
