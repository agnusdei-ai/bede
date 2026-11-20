import { describe, expect, it } from 'vitest'
import { FAMILY_GRADES, isUpperSchoolGrade, stageForGrade } from './gradeStage'

describe('stageForGrade', () => {
  it('maps every K-12 grade to the stage the server uses', () => {
    const expected: Record<string, string> = {
      K: 'K-2', '1': 'K-2', '2': 'K-2', '3': '3-5', '4': '3-5', '5': '3-5',
      '6': '6-8', '7': '6-8', '8': '6-8', '9': '6-8', '10': '6-8', '11': '6-8', '12': '6-8',
    }
    expect(FAMILY_GRADES.length).toBe(13)
    for (const g of FAMILY_GRADES) expect(stageForGrade(g)).toBe(expected[g])
  })
  it('leaves older free text and out-of-range values alone', () => {
    for (const g of ['', '4th', 'kindergarten', '0', '13', '4.5']) expect(stageForGrade(g)).toBeNull()
  })
})

describe('isUpperSchoolGrade', () => {
  it('is true for 9 through 12 only', () => {
    for (const g of ['9', '10', '11', '12']) expect(isUpperSchoolGrade(g)).toBe(true)
    for (const g of ['K', '1', '8', '13', '', 'ten']) expect(isUpperSchoolGrade(g)).toBe(false)
  })
})
