import { useRef } from 'react'

export interface TranscriptWord {
  text: string
  key: number
  // True for words that weren't present (at this position) in the previous
  // render of this same interim stream — i.e. the just-appeared tail. Once a
  // word survives to the *next* interim tick unchanged, it flips to false and
  // reads as "settled", mirroring how Claude/Gemini fade newly-heard words in
  // before they solidify rather than replacing the whole line on every tick.
  isNew: boolean
}

// Diffs consecutive interim transcript strings word-by-word so callers can
// render only the newly-appended/changed tail with an "arriving" style,
// while everything before the first point of divergence renders as settled.
// Web Speech API interim results only ever grow or get replaced wholesale on
// commit (never shrink mid-utterance), so a simple common-prefix diff against
// the previous call's words is sufficient — no need for a general LCS.
export function useTranscriptWords(interim: string): TranscriptWord[] {
  const prevWordsRef = useRef<string[]>([])
  const words = interim ? interim.split(/\s+/).filter(Boolean) : []

  let commonPrefixLen = 0
  while (
    commonPrefixLen < words.length &&
    commonPrefixLen < prevWordsRef.current.length &&
    words[commonPrefixLen] === prevWordsRef.current[commonPrefixLen]
  ) {
    commonPrefixLen++
  }

  prevWordsRef.current = words

  return words.map((text, i) => ({ text, key: i, isNew: i >= commonPrefixLen }))
}
