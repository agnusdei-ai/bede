import { describe, expect, it } from 'vitest'
import { stripSpokenMarkers } from './useTextToSpeech'

describe('stripSpokenMarkers', () => {
  it('drops each tool-card marker and the space after it', () => {
    expect(stripSpokenMarkers('📖 Read this. 🔍 Look again. ✨ Well done. 🌿 A leaf. ⚠️ Careful.'))
      .toBe('Read this. Look again. Well done. A leaf. Careful.')
  })

  it('drops a warning sign written without its variation selector', () => {
    expect(stripSpokenMarkers('⚠ Careful')).toBe('Careful')
  })

  it('leaves every other emoji whole', () => {
    // 😊, 🙂 and 🎉 share their first UTF-16 half with the markers, which a
    // character class without the u flag stripped, leaving a lone surrogate.
    const line = 'Well done 😊 and 🙂 and 🎉'
    expect(stripSpokenMarkers(line)).toBe(line)
    expect(/[\uD800-\uDFFF]/u.test(stripSpokenMarkers('📖😊'))).toBe(false)
  })

  it('still drops stage directions', () => {
    expect(stripSpokenMarkers('Hello *smiles* there')).toBe('Hello  there')
  })
})
