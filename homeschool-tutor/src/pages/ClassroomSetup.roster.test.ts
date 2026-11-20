import { describe, expect, it } from 'vitest'
import { parseRoster } from './ClassroomSetup'

describe('roster grades', () => {
  it('accepts kindergarten through grade 12', () => {
    const grades = ['K', ...Array.from({ length: 12 }, (_, i) => String(i + 1))]
    const roster = parseRoster(grades.map((g, i) => `Learner ${i},${g}`).join('\n'))
    expect(roster.map((r) => r.grade)).toEqual(grades)
  })

  it('refuses grade 0, 13 and free text, saying K–12', () => {
    for (const grade of ['0', '13', '9a', 'eleven', '']) {
      expect(() => parseRoster(`Sample Learner,${grade}`)).toThrow(/grade K–12/)
    }
  })
})
