import { describe, expect, it } from 'vitest'
import { stripSpokenMarkers } from './useTextToSpeech'
import { stripSpokenMarkers as appStripSpokenMarkers } from '../../homeschool-tutor/src/hooks/useTextToSpeech'

const LINES = [
  '📖 Read this. 🔍 Look again. ✨ Well done. 🌿 A leaf. ⚠️ Careful.',
  '⚠ Careful',
  'Well done 😊 and 🙂 and 🎉',
  '📖😊',
  'Hello *smiles* there',
  '¡Muy bien! ✨ Vamos 🌿',
]

describe('stripSpokenMarkers (demo)', () => {
  it('drops each tool-card marker and the space after it', () => {
    expect(stripSpokenMarkers(LINES[0])).toBe('Read this. Look again. Well done. A leaf. Careful.')
    expect(stripSpokenMarkers('⚠ Careful')).toBe('Careful')
  })

  it('leaves every other emoji whole', () => {
    const line = 'Well done 😊 and 🙂 and 🎉'
    expect(stripSpokenMarkers(line)).toBe(line)
    expect(/[\uD800-\uDFFF]/u.test(stripSpokenMarkers('📖😊'))).toBe(false)
  })

  it('still drops stage directions', () => {
    expect(stripSpokenMarkers('Hello *smiles* there')).toBe('Hello  there')
  })

  it('agrees with the app on every line', () => {
    for (const line of LINES) expect(stripSpokenMarkers(line)).toBe(appStripSpokenMarkers(line))
  })
})
