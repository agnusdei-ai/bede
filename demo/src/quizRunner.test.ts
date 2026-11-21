// The demo's quiz rules must be the product's: a different checker would
// demonstrate marking a family never gets.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('demo quiz runner parity', () => {
  it('is the same module as the app copy', () => {
    const demo = readFileSync(resolve(import.meta.dirname, 'quizRunner.ts'), 'utf8')
    const app = readFileSync(resolve(import.meta.dirname, '../../homeschool-tutor/src/utils/quizRunner.ts'), 'utf8')
    expect(demo).toBe(app)
  })
})

describe('demo quiz screen parity', () => {
  it('matches the app screen apart from the module path and header line', () => {
    const norm = (s: string) => s
      .replace("from '../utils/quizRunner'", "from './quizRunner'")
      .replace(/^ \* Mirror.*$/m, '')
    const demo = readFileSync(resolve(import.meta.dirname, 'QuizRunner.tsx'), 'utf8')
    const app = readFileSync(resolve(import.meta.dirname, '../../homeschool-tutor/src/components/QuizRunner.tsx'), 'utf8')
    expect(norm(demo)).toBe(norm(app))
  })
})
