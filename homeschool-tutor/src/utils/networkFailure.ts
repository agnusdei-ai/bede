/**
 * Did this request fail at the network layer — never reaching a server at
 * all — rather than being refused by one?
 *
 * `fetch()` rejects with a `TypeError` for every transport-level failure,
 * and the message is deliberately opaque and browser-specific: "Load
 * failed" on Safari, "Failed to fetch" on Chrome, "NetworkError when
 * attempting to fetch resource." on Firefox. The message check is only a
 * fallback for anything that arrives already re-wrapped; `api.ts`'s own
 * rejections are plain `Error`s carrying our text, so they match neither
 * test and are never treated as a dropped connection.
 *
 * ## Why this is worth distinguishing, twice over
 *
 * **What the child reads.** "Something's wrong with the microphone" sends a
 * family off checking browser permissions for a mic that was working
 * perfectly, when the real answer is that the connection dropped and trying
 * again in a moment will work. The same applies to a lost tutoring turn:
 * "Load failed" is Safari's internal wording, and a child cannot act on it.
 *
 * **Whether retrying is reasonable.** A transport failure means no response
 * was received at all, so nothing has been shown, decided, or half-drawn —
 * the same request is safe to make again. A 4xx/5xx is a decision the
 * server actually made, and repeating it just asks to be refused twice.
 *
 * Lived in `useHybridVoiceInput.ts`, byte-identical in both apps, until the
 * chat turn needed the same question answered — see `services/api.ts`'s own
 * retry, and `docs/VOICE_SETUP.md`.
 */
export function isNetworkFailure(err: unknown): boolean {
  if (err instanceof TypeError) return true
  const message = err instanceof Error ? err.message : String(err)
  return /load failed|failed to fetch|network\s*(error|request failed)/i.test(message)
}

/**
 * What to put on screen for a failed turn.
 *
 * A dropped connection arrives here as Safari's "Load failed" or Chrome's
 * "Failed to fetch". Interpolating that into the chat — which is what both
 * apps did — tells a child that something called "Load" has "failed", in a
 * bubble sitting where Bede's answer should be. It reads as Bede breaking,
 * it names nothing they can act on, and it sent at least one family looking
 * for a fault in the app when the answer was a weak signal.
 *
 * `connectionMessage` is passed in already translated, so this stays a
 * decision about which message is true rather than a second place that
 * knows about i18n. Anything that is NOT a dropped connection keeps its own
 * text: those are our own sentences, written for a reader.
 */
export function readerFacingError(err: unknown, connectionMessage: string): string {
  if (isNetworkFailure(err)) return connectionMessage
  return err instanceof Error && err.message ? err.message : connectionMessage
}
