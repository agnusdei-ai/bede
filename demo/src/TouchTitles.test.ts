import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('TouchTitles mirror', () => {
  it('is the app’s component, byte for byte apart from its mirror line', () => {
    const strip = (s: string) => s.replace(/^ \* Mirror[^\n]*\n/m, '')
    const demo = readFileSync(resolve(import.meta.dirname, 'TouchTitles.tsx'), 'utf8')
    const app = readFileSync(resolve(import.meta.dirname, '../../homeschool-tutor/src/components/TouchTitles.tsx'), 'utf8')
    expect(strip(demo)).toBe(strip(app))
  })
})
