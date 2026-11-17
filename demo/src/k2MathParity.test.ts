import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const app = resolve(__dirname, '../../homeschool-tutor/src')
const demo = __dirname

function source(root: string, path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('demo Number Time mirrors', () => {
  it('keeps the shared UI, wire types, and classes aligned with the household app', () => {
    const appMath = source(app, 'components/K2MathPractice.tsx')
      .replace("../services/k2MathTypes", "./k2MathTypes")
      .replace("./routine/RoutineShell", "./RoutineShell")
    const demoMath = source(demo, 'K2MathPractice.tsx')
    const appPieces = source(app, 'components/MathPieces.tsx')
      .replace("../services/k2MathTypes", "./k2MathTypes")
    const demoPieces = source(demo, 'MathPieces.tsx')

    expect(demoMath).toBe(appMath)
    expect(demoPieces).toBe(appPieces)
    expect(source(demo, 'RoutineShell.tsx')).toBe(source(app, 'components/routine/RoutineShell.tsx'))
    expect(source(demo, 'practiceStyles.ts')).toBe(source(app, 'components/practiceStyles.ts'))
    expect(source(demo, 'k2MathTypes.ts')).toBe(source(app, 'services/k2MathTypes.ts'))
  })

  it('keeps runtime code independent of household source imports', () => {
    const runtime = [
      source(demo, 'App.tsx'),
      source(demo, 'api.ts'),
      source(demo, 'K2MathPractice.tsx'),
      source(demo, 'MathPieces.tsx'),
      source(demo, 'RoutineShell.tsx'),
    ].join('\n')
    expect(runtime).not.toMatch(/from\s+['"][^'"]*homeschool-tutor\/src/)
  })
})
