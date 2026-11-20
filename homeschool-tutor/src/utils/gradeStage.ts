import type { GradeStage } from '../types'

// The grades a family can pick, K through 12 (owner ruling 2026-11-19).
// Mirrors models/schemas.py's VALID_GRADES; the stored value is the bare
// string ('K', '1' ... '12'), exactly what the server's grade_to_stage reads.
export const FAMILY_GRADES = ['K', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'] as const

// Mirrors models/schemas.py's grade_to_stage: K-2 foundations, 3-5 core
// mastery, 6-12 independent. The independent stage keeps its stored value
// '6-8' (saved configs and the server enum are unchanged); only its label
// widens. A value that is not a K-12 grade (older free text) returns null so
// the caller leaves the parent's stage choice alone.
export function stageForGrade(grade: string): GradeStage | null {
  const g = grade.trim().toUpperCase()
  if (g === 'K') return 'K-2'
  const n = Number(g)
  if (!Number.isInteger(n) || String(n) !== g) return null
  if (n >= 1 && n <= 2) return 'K-2'
  if (n >= 3 && n <= 5) return '3-5'
  if (n >= 6 && n <= 12) return '6-8'
  return null
}
