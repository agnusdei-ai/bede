/**
 * The precedence rule is the whole point of this hook, and it is the kind of
 * rule that is easy to state and easy to get subtly wrong — so it is pinned
 * here rather than left to the docstring.
 *
 * Two directions matter equally:
 *   - the CHILD can move the setting on the device in front of them, because
 *     an accommodation out of reach mid-passage is not much of one;
 *   - the PARENT still has the last word, because deciding a child needs an
 *     accommodation is the parent's call, not the software's.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { beforeEach, describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'

import {
  READING_PRESENTATION_KEY_PREFIX,
  resolvePresentation,
  useReadingPresentation,
} from './useReadingPresentation'
import type { ReadingPresentation } from '../utils/readingPresentation'

const ADA = 'Ada'
const WREN = 'Wren'

function parentSet(over: Partial<ReadingPresentation> = {}): ReadingPresentation {
  return { letter_spacing: 'normal', line_spacing: 'normal', ...over }
}

function storedFor(student: string): Record<string, unknown> | null {
  const raw = localStorage.getItem(`${READING_PRESENTATION_KEY_PREFIX}${student}`)
  return raw ? JSON.parse(raw) : null
}

beforeEach(() => {
  localStorage.clear()
})

describe('what is in force', () => {
  it('is the parent’s setting when the child has changed nothing', () => {
    const { result } = renderHook(() =>
      useReadingPresentation(parentSet({ letter_spacing: 'wide' }), ADA),
    )
    expect(result.current.presentation.letter_spacing).toBe('wide')
  })

  it('is the child’s choice once they make one on this device', () => {
    const { result } = renderHook(() => useReadingPresentation(parentSet(), ADA))
    act(() => result.current.setLetterSpacing('wider'))
    expect(result.current.presentation.letter_spacing).toBe('wider')
  })

  it('goes back to the parent when the parent changes their mind', () => {
    // The rule that keeps the parent in charge. A child widened the spacing;
    // the parent has since set something different, so the override is stale
    // and is ignored — the same reading `_build_static_prompt`'s rule 9 gives
    // a parent's own current_unit against a stored bookmark.
    const { result } = renderHook(() => useReadingPresentation(parentSet(), ADA))
    act(() => result.current.setLetterSpacing('wider'))

    const { result: afterParentEdit } = renderHook(() =>
      useReadingPresentation(parentSet({ letter_spacing: 'wide' }), ADA),
    )
    expect(afterParentEdit.current.presentation.letter_spacing).toBe('wide')
  })

  it('seeds against the PARENT’s value, not the child’s own last change', () => {
    // The defect this caught during development: recording the EFFECTIVE
    // value as the seed means a child's second change re-seeds against their
    // own first, and the parent's later edit is then ignored forever.
    const { result } = renderHook(() => useReadingPresentation(parentSet(), ADA))
    act(() => result.current.setLetterSpacing('wide'))
    act(() => result.current.setLetterSpacing('wider'))
    expect(storedFor(ADA)!.letterSeed).toBe('normal')

    const { result: afterParentEdit } = renderHook(() =>
      useReadingPresentation(parentSet({ letter_spacing: 'wide' }), ADA),
    )
    expect(afterParentEdit.current.presentation.letter_spacing).toBe('wide')
  })

  it('treats the two settings independently', () => {
    const { result } = renderHook(() =>
      useReadingPresentation(parentSet({ line_spacing: 'loose' }), ADA),
    )
    act(() => result.current.setLetterSpacing('wider'))
    expect(result.current.presentation).toEqual({
      letter_spacing: 'wider',
      line_spacing: 'loose',
    })
  })
})

describe('what the child’s change does NOT do', () => {
  it('never writes back to the student’s saved config', () => {
    // Structural: the hook is handed a config and returns a value, and has no
    // route to StudentConfig at all. A child cannot undo, for every device,
    // what a parent decided.
    const config = parentSet({ letter_spacing: 'wide' })
    const { result } = renderHook(() => useReadingPresentation(config, ADA))
    act(() => result.current.setLetterSpacing('normal'))
    expect(config.letter_spacing).toBe('wide')
  })

  it('does not follow the child to another student on the same tablet', () => {
    const { result } = renderHook(() => useReadingPresentation(parentSet(), ADA))
    act(() => result.current.setLetterSpacing('wider'))

    const { result: sibling } = renderHook(() => useReadingPresentation(parentSet(), WREN))
    expect(sibling.current.presentation.letter_spacing).toBe('normal')
    expect(storedFor(WREN)).toBeNull()
  })

  it('is ignored entirely when there is no student to attribute it to', () => {
    const { result } = renderHook(() => useReadingPresentation(parentSet(), null))
    act(() => result.current.setLetterSpacing('wider'))
    expect(result.current.presentation.letter_spacing).toBe('normal')
    expect(localStorage.length).toBe(0)
  })
})

describe('reading back a store someone can edit', () => {
  it('falls back to the parent’s value on malformed JSON rather than throwing', () => {
    localStorage.setItem(`${READING_PRESENTATION_KEY_PREFIX}${ADA}`, '{not json')
    const { result } = renderHook(() =>
      useReadingPresentation(parentSet({ letter_spacing: 'wide' }), ADA),
    )
    expect(result.current.presentation.letter_spacing).toBe('wide')
  })

  it('lets one bad field cost only itself', () => {
    // The stated answer to the demo's objection to storing a blob.
    localStorage.setItem(
      `${READING_PRESENTATION_KEY_PREFIX}${ADA}`,
      JSON.stringify({
        letter: 'enormous',
        letterSeed: 'normal',
        line: 'loose',
        lineSeed: 'normal',
      }),
    )
    const { result } = renderHook(() => useReadingPresentation(parentSet(), ADA))
    expect(result.current.presentation).toEqual({
      letter_spacing: 'normal',
      line_spacing: 'loose',
    })
  })

  it('resolves to a parent value that is itself absent or unknown', () => {
    expect(resolvePresentation(undefined, {})).toEqual({
      letter_spacing: 'normal',
      line_spacing: 'normal',
    })
    expect(
      resolvePresentation({ letter_spacing: 'sideways' } as unknown as ReadingPresentation, {}),
    ).toEqual({ letter_spacing: 'normal', line_spacing: 'normal' })
  })
})

describe('the panel says what a setting does, never what a reader has', () => {
  const panel = readFileSync(join(__dirname, '../components/TextSizeControl.tsx'), 'utf8')

  it('names no condition in any visible label', () => {
    // Same rule the parent-facing panel already holds itself to, applied to
    // the copy a CHILD sees. A control named after a diagnosis would have
    // this software assert one — see decision register entry 24.
    const visible = panel
      // Drop the tooltips and the file's own commentary; what is left is
      // roughly what renders.
      .replace(/title="[^"]*"/g, '')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\/\/[^\n]*/g, '')
    for (const word of ['dyslex', 'adhd', 'disorder', 'diagnos', 'disabilit', 'impair']) {
      expect(
        visible.toLowerCase().includes(word),
        `TextSizeControl names a condition in visible copy: ${word}`,
      ).toBe(false)
    }
  })

  it('still carries the evidence in the tooltip, where a curious parent finds it', () => {
    const tooltips = panel.match(/title="[^"]*"/g)!.join(' ').toLowerCase()
    expect(tooltips).toContain('dyslex')
    expect(tooltips, 'the weak setting must still be labelled weak').toContain(
      'rather than a measured result',
    )
  })

  it('gates the spacing rows on there being a lesson to restyle', () => {
    expect(panel).toContain('const showSpacing = !!sessionConfig?.student_name')
    expect(panel).toContain('{showSpacing && (')
  })
})
