/**
 * Coverage for the word-level diffing behind the live interim transcript
 * bubble (see App.tsx): only the newly-appended/changed tail of each
 * SpeechRecognition interim tick should be flagged `isNew` so the UI can
 * fade just that tail in, while everything the recognizer already committed
 * to on a prior tick renders as settled — matching how Claude/Gemini's
 * voice UIs progressively solidify words instead of replacing the whole
 * line on every update.
 */
import { renderHook } from '@testing-library/react'
import { StrictMode } from 'react'
import { describe, expect, it } from 'vitest'
import { useTranscriptWords } from './useTranscriptWords'

describe('useTranscriptWords', () => {
  it('flags every word as new on the very first interim tick', () => {
    const { result } = renderHook(({ interim }) => useTranscriptWords(interim), {
      initialProps: { interim: 'hello there' },
    })
    expect(result.current).toEqual([
      { text: 'hello', key: 0, isNew: true },
      { text: 'there', key: 1, isNew: true },
    ])
  })

  it('keeps the previously-seen prefix settled and only flags the appended tail as new', () => {
    const { result, rerender } = renderHook(({ interim }) => useTranscriptWords(interim), {
      initialProps: { interim: 'hello there' },
    })
    rerender({ interim: 'hello there friend' })

    expect(result.current).toEqual([
      { text: 'hello', key: 0, isNew: false },
      { text: 'there', key: 1, isNew: false },
      { text: 'friend', key: 2, isNew: true },
    ])
  })

  it('re-flags a word as new if the recognizer revises it rather than just extending', () => {
    const { result, rerender } = renderHook(({ interim }) => useTranscriptWords(interim), {
      initialProps: { interim: 'i think its' },
    })
    rerender({ interim: "i think it's raining" })

    // "its" -> "it's" diverges at index 2, so it and everything after it
    // (including the genuinely new "raining") are flagged new; "i" and
    // "think" stay settled.
    expect(result.current).toEqual([
      { text: 'i', key: 0, isNew: false },
      { text: 'think', key: 1, isNew: false },
      { text: "it's", key: 2, isNew: true },
      { text: 'raining', key: 3, isNew: true },
    ])
  })

  it('settles a word on the tick after it first appeared, if unchanged', () => {
    const { result, rerender } = renderHook(({ interim }) => useTranscriptWords(interim), {
      initialProps: { interim: 'hello' },
    })
    expect(result.current[0].isNew).toBe(true)

    rerender({ interim: 'hello' })
    expect(result.current[0].isNew).toBe(false)
  })

  it('resets cleanly to an empty word list when interim clears (e.g. a new hold starts)', () => {
    const { result, rerender } = renderHook(({ interim }) => useTranscriptWords(interim), {
      initialProps: { interim: 'goodbye now' },
    })
    rerender({ interim: '' })
    expect(result.current).toEqual([])

    // A fresh hold's first word must NOT diff against the previous hold's
    // leftover words — it should read as new again, not accidentally settled.
    rerender({ interim: 'goodbye' })
    expect(result.current).toEqual([{ text: 'goodbye', key: 0, isNew: true }])
  })

  it('collapses repeated whitespace so it never produces empty-string words', () => {
    const { result } = renderHook(({ interim }) => useTranscriptWords(interim), {
      initialProps: { interim: '  hello   there  ' },
    })
    expect(result.current.map((w) => w.text)).toEqual(['hello', 'there'])
  })

  it('still produces a correct diff under Strict Mode\'s double-invoked renders', () => {
    // React 18 Strict Mode deliberately renders each component twice in
    // development to surface impure render-phase side effects. If the diff
    // ref were ever written during render (instead of in an effect), the
    // second invocation would diff `words` against itself and always report
    // zero new words — silently breaking the settled/new split in dev.
    const { result, rerender } = renderHook(({ interim }) => useTranscriptWords(interim), {
      initialProps: { interim: "i think it's" },
      wrapper: StrictMode,
    })
    rerender({ interim: "i think it's raining outside" })

    expect(result.current).toEqual([
      { text: 'i', key: 0, isNew: false },
      { text: 'think', key: 1, isNew: false },
      { text: "it's", key: 2, isNew: false },
      { text: 'raining', key: 3, isNew: true },
      { text: 'outside', key: 4, isNew: true },
    ])
  })
})
