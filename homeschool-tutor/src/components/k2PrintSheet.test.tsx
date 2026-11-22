/**
 * K-2 rounds print as paper practice sheets through the same printer as
 * Practice Coach (utils/printDocument.ts); the device's print dialog saves
 * the same sheet as a PDF. These tests pin that a sheet carries no answers,
 * leaves off what only works by ear, draws its pictures without the app's
 * screen styles, and that each round's finish screen really prints.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import type { PhonicsLesson } from '../services/k2PhonicsTypes'
import type { MathLesson } from '../services/k2MathTypes'
import type { MapLesson, MapScene } from '../services/mapPracticeTypes'
import { buildPrintHtml, type PrintItem } from '../utils/printDocument'
import { K2_PRINT_CSS, mapPrintItems, mathPrintItems, phonicsPrintItems } from './k2PrintSheet'
import K2PhonicsPractice from './K2PhonicsPractice'
import K2MathPractice from './K2MathPractice'
import MapPractice from './MapPractice'

const printSheet = vi.hoisted(() => vi.fn((_sheet: unknown) => Promise.resolve(true)))
vi.mock('../utils/printDocument', async (original) => ({ ...(await original<object>()), printSheet }))

const t = i18n.t.bind(i18n)
/** What a reader of the printed page sees: text, never attributes. */
const visible = (items: PrintItem[]) => {
  const div = document.createElement('div')
  div.innerHTML = buildPrintHtml({ title: 'x', items, copies: ['student'], labels: { name: 'N', date: 'D', keyTitle: 'K' } })
  return div.textContent ?? ''
}

const phonics = (): PhonicsLesson => ({
  lesson_id: 'L1', area: 'phonics', level: '1', domain: 'cvc_blending', your_turn_tries: 2,
  watch: {
    prompt: { key: 'read_word_choice', args: {} },
    display: { kind: 'word', word: 'cat', graphemes: [{ text: 'c' }, { text: 'a' }, { text: 't' }] },
    choice_kind: 'picture', choices: ['dog', 'cat', 'sun'], answer: { choice: 'cat' },
  },
  together: [{
    phase: 'together', index: 0, prompt: { key: 'read_word_choice', args: {} },
    display: { kind: 'word', word: 'pig', graphemes: [{ text: 'p', sound: 'puh' }, { text: 'i' }, { text: 'g' }] },
    choice_kind: 'picture', choices: ['pig', 'bus', 'hat'],
  }],
  your_turn: [
    {
      phase: 'your_turn', index: 0, prompt: { key: 'read_word_choice', args: {} },
      display: { kind: 'word', graphemes: [{ text: 'm' }, { text: 'a' }, { text: 'p' }] },
      choice_kind: 'picture', choices: ['map', 'cup', 'fox'],
    },
    {
      phase: 'your_turn', index: 1, prompt: { key: 'sight_word_choice', args: { word: 'the' } },
      display: { kind: 'none' }, choice_kind: 'word', choices: ['the', 'and', 'is'],
    },
    {
      phase: 'your_turn', index: 2, prompt: { key: 'rhyme_choice', args: { word: 'cat' } },
      display: { kind: 'listen', word: 'cat' }, choice_kind: 'picture', choices: ['hat', 'cup', 'dog'],
    },
  ],
})

const math = (): MathLesson => ({
  lesson_id: 'M1', area: 'math', level: 'K', topic: 'count', skill: 'cc.count_objects_20', your_turn_tries: 2,
  watch: null,
  together: [{
    phase: 'together', index: 0, prompt: { key: 'count_how_many', args: {} },
    display: { diagram: { kind: 'counters', groups: [{ color: 'red', count: 4 }] }, guide: true },
    choice_kind: 'number', choices: ['3', '4', '5'],
  }],
  your_turn: [{
    phase: 'your_turn', index: 0, prompt: { key: 'count_how_many', args: {} },
    display: { diagram: { kind: 'ten_frame', red: 6, yellow: 0 }, guide: false },
    choice_kind: 'build', choices: [], build: { start: 0, capacity: 10, take_away: false },
  }],
})

const scene = (): MapScene => ({
  cols: 3, rows: 3, style: 'map', items: [{ symbol: 'house', col: 0, row: 0 }, { symbol: 'tree', col: 2, row: 2 }],
  water: [], path: [], compass: 'labeled', grid_labels: true, key: true,
})

const map = (): MapLesson => ({
  lesson_id: 'P1', level: '1', skill: 'symbols', your_turn_tries: 2,
  watch: { scene: scene(), prompt: { key: 'tap_symbol', args: { symbol: 'house' } }, answer_kind: 'tap', answer: { cell: [0, 0] } },
  together: [],
  your_turn: [{ phase: 'your_turn', index: 0, scene: scene(), prompt: { key: 'tap_symbol', args: { symbol: 'tree' } }, answer_kind: 'tap' }],
})

beforeEach(async () => { await i18n.changeLanguage('en'); printSheet.mockClear() })
afterEach(cleanup)

describe('K-2 practice sheets', () => {
  it('prints Sound Time with drawn pictures and letters, and nothing that only works by ear', () => {
    const items = phonicsPrintItems(t, phonics())
    expect(items).toHaveLength(2)
    expect(items.every((i) => i.answerSpace === 'letter')).toBe(true)
    expect(items[0].diagramHtml).toContain('>pig</p>')
    expect(items[1].diagramHtml).toMatch(/<svg viewBox="0 0 64 64"/)
    const text = visible(items)
    // The picture choices are lettered, never named: their word is the answer.
    expect(text).toMatch(/A.*B.*C/s)
    for (const word of ['cup', 'fox', 'dog', 'hat', 'cat']) expect(text).not.toContain(word)
    // One short line for the letter, not open answer lines.
    expect(buildPrintHtml({ title: 'x', items, copies: ['student'], labels: { name: 'N', date: 'D', keyTitle: 'K' } })
      .match(/class="line"/g)).toHaveLength(2)
  })

  it('prints Number Time pieces in plain colours, without guide numbers', () => {
    const items = mathPrintItems(t, math())
    expect(items[0].options).toEqual(['3', '4', '5'])
    expect(items[1].details).toEqual([t('k2Print.drawCounters')])
    for (const item of items) {
      expect(item.diagramHtml).not.toMatch(/class="(?!k2pic")/)
      expect(item.diagramHtml).not.toMatch(/<text/)
    }
  })

  it('prints a map with its grid and asks for an X on paper', () => {
    const items = mapPrintItems(t, map(), (task) => t(`mapPractice.prompt.${task.prompt.key}`), (c) => c)
    expect(items).toHaveLength(1)
    expect(items[0].details).toEqual([t('k2Print.markSquare')])
    expect(items[0].answerSpace).toBe('picture')
    expect(buildPrintHtml({ title: 'x', items, copies: ['student'], labels: { name: 'N', date: 'D', keyTitle: 'K' } })).not.toContain('class="line"')
    expect(items[0].diagramHtml).toContain('data-cell="A1"')
    expect(K2_PRINT_CSS).toContain('.k2pic .absolute')
    expect(items[0].diagramHtml).toMatch(/^<div class="k2pic">/)
  })

  it('has every print line in both languages', () => {
    for (const lang of ['en', 'es']) {
      const keys = Object.keys(i18n.getResourceBundle(lang, 'translation').k2Print ?? {})
      expect(keys.sort()).toEqual(['button', 'circle', 'drawCounters', 'markSquare', 'title'])
    }
  })
})

describe('each round prints from its finish screen', () => {
  it('Sound Time', async () => {
    const lesson = { ...phonics(), watch: null }
    render(<K2PhonicsPractice transport={{ load: () => Promise.resolve(lesson), answer: vi.fn() }} onClose={vi.fn()} canSpeak />)
    fireEvent.click(await screen.findByRole('button', { name: 'Print or save as PDF' }))
    await waitFor(() => expect(printSheet).toHaveBeenCalledTimes(1))
    const sheet = printSheet.mock.calls[0][0] as unknown as { title: string; items: PrintItem[]; copies: string[]; css: string }
    expect(sheet.title).toBe('Sound Time: practice sheet')
    expect(sheet.copies).toEqual(['student'])
    expect(sheet.items).toHaveLength(2)
    expect(sheet.css).toBe(K2_PRINT_CSS)
  })

  it('Number Time', async () => {
    render(<K2MathPractice transport={{ load: () => Promise.resolve(math()), answer: vi.fn() }} onClose={vi.fn()} canSpeak />)
    fireEvent.click(await screen.findByRole('button', { name: 'Print or save as PDF' }))
    await waitFor(() => expect(printSheet).toHaveBeenCalledTimes(1))
    expect((printSheet.mock.calls[0][0] as unknown as { items: PrintItem[] }).items).toHaveLength(2)
  })

  it('Map Practice, and says so when printing does not start', async () => {
    printSheet.mockResolvedValueOnce(false)
    render(<MapPractice transport={{ load: () => Promise.resolve({ ...map(), your_turn: [] }), answer: vi.fn() }} onClose={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: t('mapPractice.letsTry') }))
    fireEvent.click(await screen.findByRole('button', { name: 'Print or save as PDF' }))
    await screen.findByRole('alert')
    expect(screen.getByRole('alert').textContent).toBe(t('printSheet.failed'))
    expect(printSheet).toHaveBeenCalledTimes(1)
  })

})
