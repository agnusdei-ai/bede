import { describe, expect, it } from 'vitest'
import { stripSpokenMarkers } from './useTextToSpeech'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const LINES: string[] = [
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

  it('has the same body as the app copy', () => {
    // Read as text rather than imported: importing the app hook pulls the
    // app's modules into the demo's type-check, which has other settings.
    const body = (path: string) => {
      const src = readFileSync(resolve(import.meta.dirname, path), 'utf8')
      const m = src.match(/export function stripSpokenMarkers[\s\S]*?\n}/)
      expect(m, path).not.toBeNull()
      return m![0]
    }
    expect(body('./useTextToSpeech.ts')).toBe(body('../../homeschool-tutor/src/hooks/useTextToSpeech.ts'))
  })
})
