/**
 * On-device speech for K-2 practice: only voices installed on the device
 * (`localService === true`), in the session's language, and never a network
 * request. A network voice, or the unchecked browser default, is never used;
 * with no installed voice the round is silent and still shown.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { pickLocalVoice, speakOnDevice, stopOnDeviceSpeech } from './onDeviceSpeech'

type Voice = { name: string; lang: string; localService: boolean; default?: boolean }
const spoken: { text: string; lang: string; voice: Voice | null }[] = []
const fetchMock = vi.fn()
let voices: Voice[] = []

class Utterance { text: string; lang = ''; voice: Voice | null = null; rate = 1; pitch = 1
  constructor(text: string) { this.text = text } }

const LOCAL_EN = { name: 'Daniel', lang: 'en-GB', localService: true }
const LOCAL_ES = { name: 'Jorge', lang: 'es-MX', localService: true }
const NETWORK_EN = { name: 'Google UK English Male', lang: 'en-GB', localService: false }
const NETWORK_ES = { name: 'Google español', lang: 'es-ES', localService: false }

beforeEach(() => {
  spoken.length = 0
  voices = [LOCAL_EN, LOCAL_ES]
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('SpeechSynthesisUtterance', Utterance)
  vi.stubGlobal('speechSynthesis', {
    speak: (u: Utterance) => spoken.push({ text: u.text, lang: u.lang, voice: u.voice }),
    cancel: vi.fn(),
    getVoices: () => voices,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })
})
afterEach(async () => { vi.unstubAllGlobals(); await i18n.changeLanguage('en') })

const settle = () => new Promise((r) => setTimeout(r, 30))

describe('speakOnDevice', () => {
  it('speaks with an installed voice in the session language and makes no request', async () => {
    await i18n.changeLanguage('es')
    speakOnDevice('¿Cuál rima con cat?')
    await vi.waitFor(() => expect(spoken).toHaveLength(1))
    expect(spoken[0]).toMatchObject({ text: '¿Cuál rima con cat?', lang: 'es-MX', voice: LOCAL_ES })
    await i18n.changeLanguage('en')
    speakOnDevice('Which one rhymes with cat?')
    await vi.waitFor(() => expect(spoken).toHaveLength(2))
    expect(spoken[1]).toMatchObject({ lang: 'en-GB', voice: LOCAL_EN })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('skips a network voice for the language in favor of an installed one', async () => {
    voices = [NETWORK_EN, { ...LOCAL_EN, name: 'Arthur' }]
    speakOnDevice('Read the word.')
    await vi.waitFor(() => expect(spoken).toHaveLength(1))
    expect(spoken[0].voice?.name).toBe('Arthur')
    expect(spoken[0].voice?.localService).toBe(true)
  })

  it('speaks nothing when only network voices exist for the language', async () => {
    voices = [NETWORK_EN, LOCAL_ES]
    speakOnDevice('Read the word.')
    await settle()
    expect(spoken).toEqual([])
    await i18n.changeLanguage('es')
    voices = [NETWORK_ES, LOCAL_EN]
    speakOnDevice('Lee la palabra.')
    await settle()
    expect(spoken).toEqual([])
  })

  it('never falls back to a default voice that is a network voice', async () => {
    voices = [{ ...NETWORK_EN, name: 'Google US English', lang: 'en-US', default: true }]
    speakOnDevice('Read the word.')
    await settle()
    expect(spoken).toEqual([])
  })

  it('a newer line replaces one still waiting, and stop silences it', async () => {
    speakOnDevice('first')
    speakOnDevice('second')
    await vi.waitFor(() => expect(spoken.map((s) => s.text)).toEqual(['second']))
    speakOnDevice('third')
    stopOnDeviceSpeech()
    await settle()
    expect(spoken.map((s) => s.text)).toEqual(['second'])
  })

  it('is silent, not broken, with no speech engine', () => {
    vi.stubGlobal('speechSynthesis', undefined)
    expect(() => speakOnDevice('hello')).not.toThrow()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('pickLocalVoice', () => {
  const v = (x: Voice) => x as unknown as SpeechSynthesisVoice
  it('prefers the chat voice when installed, never when it is a network voice', () => {
    const preferredLocal = v({ name: 'Arthur', lang: 'en-GB', localService: true })
    expect(pickLocalVoice([v(LOCAL_EN), preferredLocal], 'en', preferredLocal)?.name).toBe('Arthur')
    expect(pickLocalVoice([v(NETWORK_EN), v(LOCAL_EN)], 'en', v(NETWORK_EN))?.name).toBe('Daniel')
    expect(pickLocalVoice([v(NETWORK_EN)], 'en', v(NETWORK_EN))).toBeNull()
  })
})
