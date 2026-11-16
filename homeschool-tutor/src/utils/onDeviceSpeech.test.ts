/**
 * On-device speech for K-2 practice: the browser's own speechSynthesis in
 * the session's language, never a network request.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { speakOnDevice, stopOnDeviceSpeech } from './onDeviceSpeech'

const spoken: { text: string; lang: string }[] = []
const fetchMock = vi.fn()

class Utterance { text: string; lang = ''; voice: unknown = null; rate = 1; pitch = 1
  constructor(text: string) { this.text = text } }

beforeEach(() => {
  spoken.length = 0
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('SpeechSynthesisUtterance', Utterance)
  vi.stubGlobal('speechSynthesis', {
    speak: (u: Utterance) => spoken.push({ text: u.text, lang: u.lang }),
    cancel: vi.fn(),
    getVoices: () => [{ name: 'Daniel', lang: 'en-GB' }, { name: 'Jorge', lang: 'es-MX' }],
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })
})
afterEach(async () => { vi.unstubAllGlobals(); await i18n.changeLanguage('en') })

describe('speakOnDevice', () => {
  it('speaks in the session language and makes no request', async () => {
    await i18n.changeLanguage('es')
    speakOnDevice('¿Cuál rima con cat?')
    await vi.waitFor(() => expect(spoken).toEqual([{ text: '¿Cuál rima con cat?', lang: 'es-MX' }]))
    await i18n.changeLanguage('en')
    speakOnDevice('Which one rhymes with cat?')
    await vi.waitFor(() => expect(spoken[1]).toEqual({ text: 'Which one rhymes with cat?', lang: 'en-GB' }))
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('a newer line replaces one still waiting, and stop silences it', async () => {
    speakOnDevice('first')
    speakOnDevice('second')
    await vi.waitFor(() => expect(spoken.map((s) => s.text)).toEqual(['second']))
    speakOnDevice('third')
    stopOnDeviceSpeech()
    await new Promise((r) => setTimeout(r, 20))
    expect(spoken.map((s) => s.text)).toEqual(['second'])
  })

  it('is silent, not broken, with no speech engine', () => {
    vi.stubGlobal('speechSynthesis', undefined)
    expect(() => speakOnDevice('hello')).not.toThrow()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
