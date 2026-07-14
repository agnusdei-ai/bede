/**
 * In-turn duplicate suppression for Bede's replies.
 *
 * The model sometimes says a thing twice in one turn: it streams the ask
 * as plain text ("Tell me everything you remember about the painting")
 * and then ALSO calls a tool whose card carries the same sentence — so
 * the child sees the identical prompt twice back-to-back, and TTS speaks
 * it twice. A prompt rule asks the model not to (see ai_service.py's
 * tools_guidance), but rules are soft; this is the deterministic CX
 * backstop: a tool card whose content adds nothing beyond what this turn
 * already said is not rendered and not spoken.
 *
 * Deliberately conservative: only suppresses when the card's normalized
 * text is fully contained in what was already said this turn — a card
 * that adds anything new (a fresh question after a recap, say) always
 * renders. Mirrored in demo/src/dedupe.ts.
 */

export function normalizeUtterance(s: string): string {
  return s
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^\p{L}\p{N}\s]/gu, '') // strip emoji + punctuation
    .replace(/\s+/g, ' ')
    .trim()
}

/** True when `candidate` repeats content already present in `saidSoFar`. */
export function isDuplicateUtterance(candidate: string, saidSoFar: string): boolean {
  const a = normalizeUtterance(candidate)
  if (a.length < 12) return false // too short to suppress safely ("Well done!")
  return normalizeUtterance(saidSoFar).includes(a)
}
