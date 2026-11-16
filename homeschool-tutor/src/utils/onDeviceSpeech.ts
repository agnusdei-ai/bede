import i18n from '../i18n'
import { resolveVoice } from '../hooks/useTextToSpeech'

/**
 * Speech that never leaves the device: the browser's own speechSynthesis,
 * in the session's language, and nothing else.
 *
 * Bede's ordinary voice (`useTextToSpeech`) sends text to the server's
 * `/tutor/speak`, which passes it to a cloud speech provider. A K-2 practice
 * round promises that nothing from it reaches any AI provider
 * (docs/K2_PRACTICE.md §6), and every word, letter sound and "let's look
 * again" in a round is spoken, so a round must speak through this instead.
 *
 * Each new line replaces the one before it rather than queueing behind it:
 * a tapped letter's sound should be heard when it is tapped, not after the
 * instruction finishes. When the browser has no speech engine, nothing is
 * spoken and every line is still shown.
 */

let generation = 0

export function onDeviceSpeechSupported(): boolean {
  return typeof window !== 'undefined' && !!window.speechSynthesis
    && typeof window.SpeechSynthesisUtterance === 'function'
}

export function speakOnDevice(text: string): void {
  const line = (text ?? '').trim()
  if (!line || !onDeviceSpeechSupported()) return
  const mine = ++generation
  window.speechSynthesis.cancel()
  const langPrefix = i18n.language === 'es' ? 'es' : 'en'
  resolveVoice(langPrefix).then((voice) => {
    if (mine !== generation) return
    const utterance = new SpeechSynthesisUtterance(line)
    utterance.lang = langPrefix === 'es' ? 'es-MX' : 'en-GB'
    if (voice) utterance.voice = voice
    utterance.rate = 0.88
    utterance.pitch = 0.92
    window.speechSynthesis.speak(utterance)
  }).catch(() => { /* a missing voice is silence, never an error */ })
}

export function stopOnDeviceSpeech(): void {
  generation += 1
  if (onDeviceSpeechSupported()) window.speechSynthesis.cancel()
}
