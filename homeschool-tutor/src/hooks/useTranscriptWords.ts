import { useEffect, useRef } from 'react'

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

  // Read-only during render: diff against whatever the PREVIOUS commit left
  // in the ref. Do not write to the ref here — mutating a ref during render
  // is an impure side effect, and React 18 Strict Mode deliberately double-
  // invokes render bodies in development to catch exactly this. Double-
  // invoking this diff would otherwise have the second pass diff `words`
  // against itself (written by the first pass), always yielding zero new
  // words — silently breaking the settled/new split. Committing the write
  // in an effect (below), which Strict Mode does not double-fire on
  // updates, keeps render pure and the diff correct in both dev and prod.
  let commonPrefixLen = 0
  while (
    commonPrefixLen < words.length &&
    commonPrefixLen < prevWordsRef.current.length &&
    words[commonPrefixLen] === prevWordsRef.current[commonPrefixLen]
  ) {
    commonPrefixLen++
  }

  useEffect(() => {
    prevWordsRef.current = words
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `words` is
    // recomputed fresh from `interim` every render; depending on `interim`
    // (a primitive) rather than `words` (a new array each render) is what
    // actually keeps this effect from re-running redundantly.
  }, [interim])

  return words.map((text, i) => ({ text, key: i, isNew: i >= commonPrefixLen }))
}
