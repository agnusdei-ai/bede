import { describe, expect, it } from 'vitest'
import { displayNameOf } from './displayName'

describe('displayNameOf', () => {
  it('uses the stable name when no preferred name is set', () => {
    expect(displayNameOf({ student_name: 'Sofia' })).toBe('Sofia')
    expect(displayNameOf({ student_name: 'Sofia', preferred_name: '' })).toBe('Sofia')
    expect(displayNameOf({ student_name: 'Sofia', preferred_name: '   ' })).toBe('Sofia')
  })

  it('uses the preferred name when an adult set one, without touching the key', () => {
    const config = { student_name: 'Sofia', preferred_name: 'Sofi' }
    expect(displayNameOf(config)).toBe('Sofi')
    expect(config.student_name).toBe('Sofia')
  })

  it('is empty, not an error, when there is no config yet', () => {
    expect(displayNameOf(null)).toBe('')
    expect(displayNameOf(undefined)).toBe('')
  })

  it('keeps two learners with the same first name distinct by their stable handles', () => {
    const a = { student_name: 'Sam', preferred_name: 'Sam' }
    const b = { student_name: "Sam (Ruth's)", preferred_name: 'Sam' }
    expect(displayNameOf(a)).toBe(displayNameOf(b))
    expect(a.student_name).not.toBe(b.student_name)
  })
})
