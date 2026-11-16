import i18n from '../i18n'
import { isFemaleVoiceName, resolveVoice } from '../hooks/useTextToSpeech'

/**
 * Speech for a K-2 practice round, through voices installed on the device
 * only, in the session's language.
 *
 * Bede's ordinary voice (`useTextToSpeech`) sends text to the server's
 * `/tutor/speak`, which passes it to a cloud speech provider. A K-2 practice
 * round promises that nothing from it reaches any AI provider
 * (docs/K2_PRACTICE.md §6), and every word, letter sound and "let's look
 * again" in a round is spoken, so a round speaks through this instead.
 *
 * The browser's own speechSynthesis is not automatically on-device: some
 * voices are network voices (`SpeechSynthesisVoice.localService === false`;
 * on Chrome desktop the "Google ..." voices send the text to Google's
 * servers). So a round speaks only with a voice whose `localService` is true,
 * and always names that voice on the utterance, since an utterance with no
 * voice uses the browser's default, which can itself be a network voice.
 * When the device has no installed voice for the session's language, nothing
 * is spoken and every line is still shown, the same as when the browser has
 * no speech engine at all.
 *
 * Each new line replaces the one before it rather than queueing behind it:
 * a tapped letter's sound should be heard when it is tapped, not after the
 * instruction finishes.
 */

let generation = 0

export function onDeviceSpeechSupported(): boolean {
  return typeof window !== 'undefined' && !!window.speechSynthesis
    && typeof window.SpeechSynthesisUtterance === 'function'
}

/**
 * An installed (local) voice for the language, or null. The voice Bede's
 * chat would pick is preferred when it is installed; otherwise any installed
 * voice for the language, avoiding one named as female first. Never a
 * network voice, and never the unchecked browser default.
 */
export function pickLocalVoice(
  voices: SpeechSynthesisVoice[], langPrefix: string, preferred: SpeechSynthesisVoice | null,
): SpeechSynthesisVoice | null {
  const local = voices.filter((v) => v.localService === true
    && (v.lang ?? '').toLowerCase().startsWith(langPrefix))
  if (preferred && preferred.localService === true && local.some((v) => v.name === preferred.name)) {
    return local.find((v) => v.name === preferred.name) ?? null
  }
  return local.find((v) => !isFemaleVoiceName(v.name)) ?? local[0] ?? null
}

/** Whether the device has an installed voice for the session's language,
 * so a round can be spoken at all. */
export function hasLocalVoice(): Promise<boolean> {
  if (!onDeviceSpeechSupported()) return Promise.resolve(false)
  const langPrefix = i18n.language === 'es' ? 'es' : 'en'
  return resolveVoice(langPrefix)
    .then((preferred) => pickLocalVoice(window.speechSynthesis.getVoices(), langPrefix, preferred) !== null)
    .catch(() => false)
}

export function speakOnDevice(text: string): void {
  const line = (text ?? '').trim()
  if (!line || !onDeviceSpeechSupported()) return
  const mine = ++generation
  window.speechSynthesis.cancel()
  const langPrefix = i18n.language === 'es' ? 'es' : 'en'
  resolveVoice(langPrefix).then((preferred) => {
    if (mine !== generation) return
    const voice = pickLocalVoice(window.speechSynthesis.getVoices(), langPrefix, preferred)
    // No installed voice for this language: stay silent; the line is shown.
    if (!voice) return
    const utterance = new SpeechSynthesisUtterance(line)
    utterance.lang = langPrefix === 'es' ? 'es-MX' : 'en-GB'
    utterance.voice = voice
    utterance.rate = 0.88
    utterance.pitch = 0.92
    window.speechSynthesis.speak(utterance)
  }).catch(() => { /* a missing voice is silence, never an error */ })
}

export function stopOnDeviceSpeech(): void {
  generation += 1
  if (onDeviceSpeechSupported()) window.speechSynthesis.cancel()
}
